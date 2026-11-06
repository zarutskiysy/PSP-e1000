# Vendored: psplinkusb `usbhostfs` (PSP side)

- Source: https://github.com/pspdev/psplinkusb/tree/bae0ac40b2b52eb5762ecb52df4e7bb8e6c7ad5f/usbhostfs
- Commit `bae0ac40b2b52eb5762ecb52df4e7bb8e6c7ad5f` (2026-10-28) — the same commit the pspdev
  toolchain `v20261101` built its `usbhostfs_pc` host tool from (`~/pspdev/build.txt`), so both ends match.
- License: BSD-3-Clause (`LICENSE`, copied verbatim). Files are unmodified.
- Build: `make -C common/psp/usbhostfs` → `usbhostfs.prx` (kernel module, registers "USBHostFSDriver",
  PID 0x1C9; async channel 4 = ASYNC_USER is ours).
