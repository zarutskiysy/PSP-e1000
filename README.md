# PSP E1000 × Mac

Proof-of-concept links between a PSP E1000 (PSP Street, CFW, no Wi-Fi) and an Apple Silicon Mac over USB.

| Branch | What |
|---|---|
| `main` | toolchain setup, shared PSP⇄Mac link code (`common/`), research (`docs/research/`) |
| `feat/mac-controller` | PSP as a Mac control deck (nub → mouse, buttons → keys, action wheel) |
| `feat/second-screen` | PSP as a 480×272 second display streamed over USB |
| `feat/dual-screen-game` | original asymmetric game: Mac main screen + PSP console |

Start with `docs/MORNING_REPORT.md`, then `docs/SETUP.md`.

## Layout

```
common/
  protocol/   framed protocol: C header (psp_link.h) + Python mirror (psp_link.py)
  psp/        PSP-side protocol logic (plain C, unit-tested on macOS) + USB bulk PRX
  mac/        Mac-side transports: libusb (pyusb) and mock (TCP)
tools/        fake_psp.py, PPSSPP automation helpers, toolchain env script
docs/         STATUS, DECISIONS, research, SETUP, MORNING_REPORT
```
