# Galaxy Note10+ (d2s, SM-N975F) bring-up record

This is a source-only starting point for the Exynos 9825 Note10+. It is not a
bootable port. No Note10+ device has been inspected or used in this work, and
the S7 (`herolte`) boot image, memory map, framebuffer addresses, and driver
registers must not be copied to this target.

Project credit: this work builds on [wardevsa/ios-a5xelte](https://github.com/wardevsa/ios-a5xelte),
especially its `herolte` port and existing XNU/shim work. Existing code and
hardware research remain credited to that project and its contributors; this
milestone adds only Note10+ bring-up documentation and a read-only host tool.

Target details supplied for this request are SM-N975F, Exynos 9825, 12 GB
RAM, Mali-G76 MP12, and bootloader binary S9. Only the product identity and
SoC family are corroborated by the source links below; the other values have
not been independently checked here.

## Confirmed from public source

The LineageOS `android_device_samsung_d2s` tree identifies `d2s` as
`SM-N975F`, selects `exynos9820-d2s_defconfig`, and includes the shared
Exynos9825 board configuration. Its product makefile specifies a
1440x3040 screen. The kernel's D2 EUR OPEN revision 24 overlay identifies
the board as based on `EXYNOS9825`; the SoC device tree is shared under the
`exynos9820` filename.

The LineageOS build configuration inherited by `d2s` selects Android boot
image header version 1, a 2048-byte mkbootimg page size, kernel base
`0x10000000`, and kernel offset `0x8000`. It also configures a separated
DTBO and builds a `dtb.img`. These are LineageOS build settings; they do not
prove that the stock Samsung BOOT partition has the same layout or that
S-Boot enters a replacement image at those addresses. The stock image and
actual handoff remain unverified.

The shared SoC DTS describes eight CPU nodes with MPIDR affinity values
`0x0` through `0x5`, then `0x100` and `0x101`. The CPU nodes use
`enable-method = "psci"`; PSCI is configured for SMC and `CPU_ON` function
`0xC4000003`. These are Linux device-tree declarations, not confirmation of
the Note10+'s S-Boot handoff, the boot CPU, or that XNU can start any
secondary processor.

The same base DTS declares three 2-GiB RAM ranges. That source declaration
does not match the user's 12-GB hardware description and does not establish
the active Note10+ RAM banks or reserved regions. The actual boot FDT must be
examined before using any RAM range in XNU.

The timer node declares a 26-MHz clock and the Exynos 9820-family DTS places
the UFS host at `0x13d60000`, the Mali node at `0x18500000`, and the main
DECON node at `0x19030000`. The D2 overlay selects a Mali revision-specific
include. These are Linux-source register descriptions, not validated XNU
mappings, handoff state, power sequences, or drivers.

Sources:

- [LineageOS d2s product makefile](https://github.com/LineageOS/android_device_samsung_d2s/blob/lineage-24.0/lineage_d2s.mk)
- [LineageOS d2s board configuration](https://github.com/LineageOS/android_device_samsung_d2s/blob/lineage-24.0/BoardConfig.mk)
- [LineageOS shared Exynos9825 board configuration](https://github.com/LineageOS/android_device_samsung_exynos9820-common/blob/lineage-24.0/BoardConfig9825.mk)
- [LineageOS inherited Pie-launched boot configuration](https://github.com/LineageOS/android_device_samsung_exynos9820-common/blob/lineage-24.0/BoardConfigPieLaunched.mk)
- [LineageOS shared boot and separated-DTBO configuration](https://github.com/LineageOS/android_device_samsung_exynos9820-common/blob/lineage-24.0/BoardConfigCommon.mk)
- [LineageOS shared DTB image build](https://github.com/LineageOS/android_device_samsung_exynos9820-common/blob/lineage-24.0/AndroidBoard.mk)
- [Exynos9825 D2 overlay](https://github.com/LineageOS/android_kernel_samsung_exynos9820/blob/lineage-24.0/arch/arm64/boot/dts/samsung/exynos9820-d2_eur_open_24.dts)
- [Exynos9820-family SoC DTS](https://github.com/LineageOS/android_kernel_samsung_exynos9820/blob/lineage-24.0/arch/arm64/boot/dts/exynos/exynos9820.dts)
- [Mali node DTS](https://github.com/LineageOS/android_kernel_samsung_exynos9820/blob/lineage-24.0/arch/arm64/boot/dts/exynos/exynos9820-mali_common.dtsi)

## Implemented in this milestone

`tools/d2s_dtb_report.py` reads a standalone flattened device-tree blob and
prints JSON for `/chosen`, the declared boot CPU, memory ranges and
reservations (including `/reserved-memory` children), CPU nodes, and nodes
whose names or compatible strings indicate GIC, timer, UFS, Mali, display, or
serial hardware. It validates the FDT header, block boundaries, and termination
of the memory-reservation map. It does not unpack an Android BOOT image or
DTBO, access a device, or write any data.

Run it only on an FDT file already available on the host:

```sh
python3 tools/d2s_dtb_report.py d2s.dtb
```

These are declarations in the supplied FDT, not proof of the live S-Boot
handoff. In particular, memory reservations and the DTB boot-CPU field must
be compared with the target's actual boot evidence before configuring XNU.

## Blockers before a target boot path

- The stock Note10+ BOOT image container and DTB/DTBO packaging, effective
  kernel load/entry state, boot arguments, and permitted boot method are not
  established. LineageOS build metadata is not evidence of the stock S-Boot
  handoff.
- The live boot FDT, actual memory map/reservations, boot CPU MPIDR, exception
  level, page granule, counter frequency, GIC handoff, framebuffer address,
  stride, format, and display-controller handoff have not been verified.
- The S7 loader and packer encode S7-specific assumptions and must not be used
  for d2s. No D2S XNU machine configuration, loader, display, SMP, or storage
  driver is enabled by this change.

Until these blockers are resolved from public source or a separately
authorized read-only artifact, this repository must not claim d2s boot
support. This work did not connect to, reboot, or write to a physical device,
and did not obtain or include Apple firmware or userland.
