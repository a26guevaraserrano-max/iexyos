#!/usr/bin/env python3
"""Focused tests for the standalone, read-only FDT inspector."""
import contextlib
import io
import json
import struct
import tempfile
import unittest
from pathlib import Path

from d2s_dtb_report import FDT_MAGIC, FdtError, main, parse_fdt


def make_fdt():
    strings = bytearray()
    string_offsets = {}

    def add_string(value):
        if value not in string_offsets:
            string_offsets[value] = len(strings)
            strings.extend(value.encode("ascii") + b"\0")
        return string_offsets[value]

    structure = bytearray()

    def token(value):
        structure.extend(struct.pack(">I", value))

    def begin(name):
        token(1)
        structure.extend(name.encode("ascii") + b"\0")
        structure.extend(b"\0" * ((-len(structure)) % 4))

    def end_node():
        token(2)

    def prop(name, value):
        token(3)
        structure.extend(struct.pack(">II", len(value), add_string(name)))
        structure.extend(value)
        structure.extend(b"\0" * ((-len(structure)) % 4))

    def word(value):
        return struct.pack(">I", value)

    begin("")
    prop("#address-cells", word(2))
    prop("#size-cells", word(1))
    prop("model", b"Samsung D2 test\0")
    prop("compatible", b"samsung,EXYNOS9825\0samsung,armv8\0")

    begin("chosen")
    prop("bootargs", b"debug=0xc\0")
    prop("kaslr-seed", bytes(range(8)))
    end_node()

    begin("memory@80000000")
    prop("device_type", b"memory\0")
    prop("reg", word(0) + word(0x80000000) + word(0x80000000))
    end_node()

    begin("cpus")
    prop("#address-cells", word(2))
    prop("#size-cells", word(0))
    begin("cpu@100")
    prop("device_type", b"cpu\0")
    prop("compatible", b"arm,cheetah\0arm,armv8\0")
    prop("reg", word(0) + word(0x100))
    prop("enable-method", b"psci\0")
    end_node()
    end_node()

    begin("soc")
    prop("#address-cells", word(2))
    prop("#size-cells", word(2))
    begin("ufs@13d60000")
    prop("compatible", b"samsung,exynos-ufs\0")
    prop("reg", word(0) + word(0x13D60000) + word(0) + word(0x10000))
    prop("interrupts", word(0) + word(42) + word(4))
    end_node()
    end_node()

    end_node()
    token(9)

    rsvmap_offset = 40
    reserve_map = b"\0" * 16
    struct_offset = rsvmap_offset + len(reserve_map)
    strings_offset = struct_offset + len(structure)
    total_size = strings_offset + len(strings)
    header = struct.pack(
        ">10I", FDT_MAGIC, total_size, struct_offset, strings_offset,
        rsvmap_offset, 17, 16, 0, len(strings), len(structure)
    )
    return bytes(header + reserve_map + structure + strings)


class D2sDtbReportTests(unittest.TestCase):
    def test_reports_chosen_memory_cpu_and_peripheral_registers(self):
        report = parse_fdt(make_fdt())

        self.assertEqual(report["root"]["model"], "Samsung D2 test")
        self.assertEqual(report["chosen"]["bootargs"], "debug=0xc")
        self.assertEqual(report["chosen"]["kaslr-seed"], "present")
        self.assertEqual(report["memory"][0]["reg"], [
            {"address": "0x80000000", "size": "0x80000000"}
        ])
        self.assertEqual(report["cpus"][0]["reg"], [
            {"address": "0x100", "size": "0x0"}
        ])
        self.assertEqual(report["cpus"][0]["enable_method"], "psci")
        ufs = next(item for item in report["peripherals"]
                   if item["path"] == "/soc/ufs@13d60000")
        self.assertEqual(ufs["reg"], [
            {"address": "0x13d60000", "size": "0x10000"}
        ])
        self.assertEqual(ufs["interrupts"], ["0x0", "0x2a", "0x4"])

    def test_rejects_bad_magic_and_truncated_header(self):
        blob = bytearray(make_fdt())
        struct.pack_into(">I", blob, 0, 0)
        with self.assertRaisesRegex(FdtError, "magic"):
            parse_fdt(bytes(blob))
        with self.assertRaisesRegex(FdtError, "header"):
            parse_fdt(b"\xd0\x0d")

    def test_rejects_out_of_bounds_structure(self):
        blob = bytearray(make_fdt())
        struct.pack_into(">I", blob, 8, len(blob) + 1)
        with self.assertRaisesRegex(FdtError, "out of bounds"):
            parse_fdt(bytes(blob))

    def test_cli_reads_a_standalone_blob_and_emits_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "d2s.dtb"
            path.write_bytes(make_fdt())
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = main([str(path)])

        self.assertEqual(result, 0)
        self.assertEqual(json.loads(output.getvalue())["root"]["model"],
                         "Samsung D2 test")


if __name__ == "__main__":
    unittest.main()
