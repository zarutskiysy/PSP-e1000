# PSP E1000 × Mac

Proof-of-concept links between a PSP E1000 (PSP Street, CFW, no Wi-Fi) and an Apple Silicon Mac over USB.
Start with [`docs/MORNING_REPORT.md`](docs/MORNING_REPORT.md), then [`docs/SETUP.md`](docs/SETUP.md) and the USB
smoke test [`docs/HARDWARE_TEST.md`](docs/HARDWARE_TEST.md).

| Branch | What |
|---|---|
| `main` | toolchain setup, shared PSP⇄Mac link code (`common/`), emulator tooling (`tools/`), research (`docs/research/`) |
| `feat/mac-controller` | PSP as a Mac control deck (nub → mouse, buttons → keys, action wheel) |
| `feat/second-screen` | PSP as a 480×272 second display streamed over USB |
| `feat/dual-screen-game` | original asymmetric game: Mac main screen + PSP console |

## How the pieces fit

```
 PSP app (C, pspdev)                               Mac app (Python 3.12)
 ┌──────────────────────────┐                      ┌───────────────────────────┐
 │ track logic              │                      │ track logic               │
 │ common/psp/link.c        │  framed protocol     │ pspmac.Link               │
 │   psp_link_io_t ─────────┼── 'P''L' type seq ───┼─ pspmac.transport         │
 └───┬──────────┬───────────┘   len payload crc16  └──┬─────────┬──────────┬───┘
     │          │                                     │         │          │
  USB HOSTFS  USB MACLINK        PPSSPP mailbox       "hostfs"  "usb"     "mock"/tcp
  usbhostfs   pspmaclink.prx     io_mailbox.c          TCP:10004 pyusb     TCP:47100
  .prx (ch 4) (own bulk drv)     ⇅ ws debugger         via       054C:01CB  tools/fake_psp.py or
     │          │                tools/ppsspp_bridge   usbhostfs_pc         tools/ppsspp_bridge.py
     └── real hardware only ──┘  (emulator only)
```

## Layout

```
common/protocol/psp_link.h       framed protocol (C, header-only); Python mirror common/python/pspmac/protocol.py
common/psp/                      PSP-side link logic + transports (pipe, posix tcp, mailbox, usb/)
common/psp/usb/prx/              pspmaclink.prx kernel module (UNTESTED on hardware)
common/psp/usbhostfs/            vendored psplinkusb usbhostfs (BSD-3)
common/python/pspmac/            Mac side: Link, transports (mock, hostfs, usb, tcp)
examples/hello, examples/echo    minimal EBOOTs (echo = USB/emulator reference app)
tools/                           env.sh, fake_psp.py, ppsspp.py, ppsspp_bridge.py, usb_probe.py
docs/                            STATUS, DECISIONS, SETUP, HARDWARE_TEST, research/, img/
```

## Quick check

```bash
source tools/env.sh
make -C common/psp/test && .venv/bin/python -m pytest -q common/python/tests
make -C examples/echo USB=1
```
