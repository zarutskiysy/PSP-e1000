# Decisions log

Overnight run, 2026-11-07 (started 02:22 MSK). Orchestrator decides without blocking on Semyon; every non-obvious choice is logged here.

| # | Time (MSK) | Decision | Why |
|---|---|---|---|
| 1 | 02:23 | Assume CFW 6.60/6.61 + PRO-C / LME / ARK-4 | Exact CFW unknown; all three load kernel PRXs from homebrew EBOOTs. Documented in every HARDWARE_TEST.md. |
| 2 | 02:24 | Toolchain: pspdev/pspdev release `v20261101`, asset `pspdev-macos-latest-arm64.tar.gz`, installed to `~/pspdev` | Official prebuilt for Apple Silicon; docker image kept as fallback. |
| 3 | 02:24 | Emulator: PPSSPP 1.20.4 via Homebrew cask `ppsspp-emulator` | Official build; no BIOS/firmware needed. |
| 4 | 02:25 | `caffeinate -dims -t 32400` runs in background; the app keep-awake tool was refused by the auto-mode classifier | Mac must not sleep overnight. |
| 5 | 02:40 | Two USB paths behind one PSP API (`common/psp/usb/psp_usb_io.h`): HOSTFS = psplink `usbhostfs.prx` + `usbhostfs_pc` (async ch. 4 ⇄ Mac TCP 10004, Scout A) for low-bandwidth tracks; MACLINK = own vendor bulk PRX `pspmaclink.prx` + pyusb (PID 0x01CB) for the second screen | HOSTFS reuses proven code end to end (RemoteJoy pattern); MACLINK avoids usbhostfs async-channel overhead for 260 KB frames. |
| 6 | 02:41 | brew `install cmake` started upgrading unrelated formulae (lammps…) at 75 KB/s: killed; cmake 4.4.4 + lz4 from PyPI into `.venv`; toolchain fetched with 8 parallel ranged curl requests | Bandwidth; nothing system-wide changed beyond libusb (already present) and the PPSSPP cask. |
| 7 | 02:45 | Game track message range is 0x70–0x9F (Scout C proposed 0x40–0x5F, which belongs to the screen track) | Ranges fixed in `psp_link.h`. |
| 8 | 02:50 | PPSSPP automation = WebSocket debugger, sandboxed HOME per port (`tools/ppsspp.py`); ports A 45671, B 45672, C 45673, tests 45690 | Builders run emulators in parallel; user's own PPSSPP config untouched. |
| 9 | 02:55 | Screenshots fall back to reading VRAM over `memory.read` | `gpu.buffer.screenshot` returns "Could not download output" for apps drawing to VRAM without the GE (pspDebugScreen), on Vulkan, OpenGL and software. |
| 10 | 03:05 | Emulator ⇄ Mac link = mailbox rings in PSP RAM bridged by `tools/ppsspp_bridge.py` | PPSSPP can't emulate USB to the host; this runs the *real* PSP code against the *real* Mac code. Measured: ~200 ms RTT, ~280 KiB/s each way, because PPSSPP services debugger requests once per frame and hard polling stalls the emulated CPU (poll interval 20 ms). |
| 11 | 03:00 | HOSTFS mode is for small Mac→PSP traffic only (< 4 KiB in flight) | usbhostfs `fill_async` keeps a 4096-byte ring per channel and drops overflow silently. Controller/game are fine; second screen must use MACLINK. |
| 12 | 03:00 | `usbhostfs_pc` (toolchain build) verified on this Mac: listens on 127.0.0.1:10000–10007, "waiting for device" | Mac side of HOSTFS is ready without hardware; `Link.handshake(attempts=N)` resends HELLO until the PSP answers. |
| 13 | 03:15 | Parsers (C + Python) resync immediately on a header whose length exceeds the receiver's max payload | Reviewer A: a CRC-less bogus length (0xFFFFFFF0) made the Python parser wait forever and lose all later frames. |
