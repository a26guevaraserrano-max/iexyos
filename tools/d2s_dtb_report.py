#!/usr/bin/env python3
"""Print a read-only summary of a flattened device tree (FDT) blob."""
import argparse
import json
import re
import struct
import sys
from pathlib import Path


FDT_MAGIC = 0xD00DFEED
FDT_BEGIN_NODE = 1
FDT_END_NODE = 2
FDT_PROP = 3
FDT_NOP = 4
FDT_END = 9
HEADER_SIZE = 40
PERIPHERAL_RE = re.compile(
    r"gic|interrupt-controller|timer|ufs|mali|decon|dpu|display|panel|"
    r"framebuffer|serial|uart",
    re.IGNORECASE,
)


class FdtError(ValueError):
    """The input is not a structurally valid FDT blob."""


def _u32(data, offset):
    if offset < 0 or offset + 4 > len(data):
        raise FdtError("truncated 32-bit value")
    return struct.unpack_from(">I", data, offset)[0]


def _read_c_string(data, offset, end):
    if offset < 0 or offset >= end:
        raise FdtError("string offset is outside its block")
    nul = data.find(b"\0", offset, end)
    if nul < 0:
        raise FdtError("unterminated string")
    return data[offset:nul].decode("utf-8", errors="replace"), nul + 1


def _string_list(value):
    return [part.decode("utf-8", errors="replace")
            for part in value.split(b"\0") if part]


def _align4(offset):
    return (offset + 3) & ~3


def parse_fdt(data):
    """Parse an FDT blob and return a small, JSON-friendly hardware summary."""
    if len(data) < HEADER_SIZE:
        raise FdtError("file is shorter than the FDT header")

    header = struct.unpack_from(">10I", data, 0)
    (magic, total_size, struct_offset, strings_offset, rsvmap_offset,
     version, last_compatible_version, _boot_cpu, strings_size,
     struct_size) = header
    if magic != FDT_MAGIC:
        raise FdtError("bad FDT magic")
    if version < 16 or last_compatible_version > 17:
        raise FdtError("unsupported FDT version")
    if total_size < HEADER_SIZE or total_size > len(data):
        raise FdtError("invalid FDT total size")
    struct_end = struct_offset + struct_size
    strings_end = strings_offset + strings_size
    if (rsvmap_offset < HEADER_SIZE or rsvmap_offset >= total_size or
            struct_offset < HEADER_SIZE or struct_end > total_size or
            strings_offset < HEADER_SIZE or strings_end > total_size):
        raise FdtError("FDT structure or strings block is out of bounds")

    strings = data[strings_offset:strings_end]
    nodes = []
    stack = []
    offset = struct_offset
    saw_end = False

    while offset + 4 <= struct_end:
        token = _u32(data, offset)
        offset += 4
        if token == FDT_BEGIN_NODE:
            name, offset = _read_c_string(data, offset, struct_end)
            offset = _align4(offset)
            parent = stack[-1] if stack else None
            path = "/" + name if parent is None else (
                parent["path"].rstrip("/") + "/" + name
            )
            node = {
                "name": name,
                "path": path,
                "parent": parent,
                "children": [],
                "properties": {},
            }
            if parent is not None:
                parent["children"].append(node)
            nodes.append(node)
            stack.append(node)
        elif token == FDT_END_NODE:
            if not stack:
                raise FdtError("unbalanced FDT end-node token")
            stack.pop()
        elif token == FDT_PROP:
            if not stack or offset + 8 > struct_end:
                raise FdtError("property token has no node or header")
            length = _u32(data, offset)
            name_offset = _u32(data, offset + 4)
            offset += 8
            value_end = offset + length
            if value_end > struct_end or name_offset >= len(strings):
                raise FdtError("property value or name is out of bounds")
            name, _ = _read_c_string(strings, name_offset, len(strings))
            stack[-1]["properties"][name] = data[offset:value_end]
            offset = _align4(value_end)
        elif token == FDT_NOP:
            continue
        elif token == FDT_END:
            if stack:
                raise FdtError("FDT ended before all nodes were closed")
            saw_end = True
            break
        else:
            raise FdtError("unknown FDT structure token 0x%x" % token)

    if not saw_end or not nodes or nodes[0]["name"] != "":
        raise FdtError("missing FDT end token or root node")

    root = nodes[0]

    def prop_strings(node, name):
        return _string_list(node["properties"].get(name, b""))

    def cell_count(node, name, default):
        raw = node["properties"].get(name)
        if raw is None:
            return default
        if len(raw) != 4:
            raise FdtError("%s at %s is not one cell" % (name, node["path"]))
        return _u32(raw, 0)

    def decode_reg(node):
        raw = node["properties"].get("reg")
        if raw is None:
            return []
        parent = node["parent"]
        address_cells = cell_count(parent, "#address-cells", 2)
        size_cells = cell_count(parent, "#size-cells", 1)
        tuple_cells = address_cells + size_cells
        if tuple_cells == 0 or len(raw) % (tuple_cells * 4):
            return [{"raw": raw.hex()}]

        entries = []
        cell_offset = 0
        while cell_offset < len(raw):
            address = 0
            for _ in range(address_cells):
                address = (address << 32) | _u32(raw, cell_offset)
                cell_offset += 4
            size = 0
            for _ in range(size_cells):
                size = (size << 32) | _u32(raw, cell_offset)
                cell_offset += 4
            entries.append({"address": hex(address), "size": hex(size)})
        return entries

    def basic_node(node):
        result = {
            "path": node["path"],
            "compatible": prop_strings(node, "compatible"),
        }
        status = prop_strings(node, "status")
        if status:
            result["status"] = status[0]
        if "reg" in node["properties"]:
            result["reg"] = decode_reg(node)
        if "interrupts" in node["properties"]:
            raw = node["properties"]["interrupts"]
            if len(raw) % 4:
                result["interrupts_raw"] = raw.hex()
            else:
                result["interrupts"] = [
                    hex(_u32(raw, i)) for i in range(0, len(raw), 4)
                ]
        if "interrupt-names" in node["properties"]:
            result["interrupt_names"] = prop_strings(node, "interrupt-names")
        return result

    chosen = next((node for node in nodes if node["path"] == "/chosen"), None)
    chosen_report = {}
    if chosen:
        for key in ("bootargs", "linux,initrd-start", "linux,initrd-end"):
            raw = chosen["properties"].get(key)
            if raw is None:
                continue
            if key == "bootargs":
                chosen_report[key] = raw.split(b"\0", 1)[0].decode(
                    "utf-8", errors="replace"
                )
            else:
                chosen_report[key] = [
                    hex(_u32(raw, i)) for i in range(0, len(raw), 4)
                ] if len(raw) % 4 == 0 else raw.hex()
        if "kaslr-seed" in chosen["properties"]:
            chosen_report["kaslr-seed"] = "present"

    memory = [
        basic_node(node)
        for node in nodes
        if node["parent"] is root and
        prop_strings(node, "device_type") == ["memory"]
    ]

    cpu_parent = next((node for node in nodes if node["path"] == "/cpus"),
                      None)
    cpus = []
    if cpu_parent:
        for node in cpu_parent["children"]:
            if prop_strings(node, "device_type") != ["cpu"]:
                continue
            item = basic_node(node)
            method = prop_strings(node, "enable-method")
            if method:
                item["enable_method"] = method[0]
            cpus.append(item)

    peripherals = []
    for node in nodes:
        if node is root:
            continue
        compatible = prop_strings(node, "compatible")
        if PERIPHERAL_RE.search(node["name"]) or any(
                PERIPHERAL_RE.search(item) for item in compatible):
            peripherals.append(basic_node(node))

    return {
        "fdt_version": version,
        "root": {
            "model": (prop_strings(root, "model") or [None])[0],
            "compatible": prop_strings(root, "compatible"),
        },
        "chosen": chosen_report,
        "memory": memory,
        "cpus": cpus,
        "peripherals": peripherals,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Inspect a standalone FDT blob without modifying it."
    )
    parser.add_argument("fdt", type=Path, help="path to a raw FDT blob")
    args = parser.parse_args(argv)
    try:
        report = parse_fdt(args.fdt.read_bytes())
    except (OSError, FdtError) as exc:
        parser.error(str(exc))
    json.dump(report, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
