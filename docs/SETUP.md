# Setup (macOS, Apple Silicon)

Everything below was done on 2026-11-07 on macOS 26.6 / arm64 and is what the branches assume.

## 1. PSP toolchain (pspdev)

```bash
curl -L -o /tmp/pspdev.tar.gz https://github.com/pspdev/pspdev/releases/download/v20261101/pspdev-macos-latest-arm64.tar.gz
tar -xzf /tmp/pspdev.tar.gz -C ~        # -> ~/pspdev (psp-gcc 15.2.0, pspsdk, SDL2/SDL3, liblz4, usbhostfs_pc ...)
source tools/env.sh                     # PATH += ~/pspdev/bin and .venv/bin
```

`~/pspdev/build.txt` lists the exact component commits (pspsdk `c3da431`, psplinkusb `bae0ac4`, …).
Docker fallback (not needed here): `docker run -it -v $PWD:/src pspdev/pspdev`.

## 2. Mac-side Python

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
brew install libusb            # pyusb backend (/opt/homebrew/lib/libusb-1.0.dylib)
```

cmake comes from PyPI (`requirements.txt`) because `brew install cmake` tried to upgrade unrelated formulae.

## 3. PPSSPP

```bash
brew install --cask ppsspp-emulator     # PPSSPP 1.20.4, /Applications/PPSSPPSDL.app (universal x86_64+arm64)
```

No BIOS / firmware / game images are needed or used.

## 4. Build and run in the emulator

```bash
source tools/env.sh
make -C examples/hello                                   # EBOOT.PBP
python tools/ppsspp.py run examples/hello/EBOOT.PBP      # sandboxed HOME .ppsspp_home/45677, debugger on :45677
python tools/ppsspp.py shot /tmp/hello.png
python tools/ppsspp.py quit
```

`tools/ppsspp.py` drives PPSSPP's WebSocket debugger (`ws://127.0.0.1:<port>/debugger`, subprotocol
`debugger.ppsspp.org`): screenshots (GE output, or VRAM read when the app draws without the GE), button
and analog input, memory read/write. Several instances can run on different `--port`s.

## 5. Emulator ⇄ Mac link (no hardware)

PPSSPP cannot emulate USB to the host. Instead PSP apps use `common/psp/io_mailbox.c` when
`psp_is_emulator()` and `tools/ppsspp_bridge.py` shuttles the bytes to a normal TCP port:

```bash
make -C examples/echo
python tools/ppsspp.py run examples/echo/EBOOT.PBP
python tools/ppsspp_bridge.py --listen 47100 &
python tools/usb_probe.py echo --spec mock --sizes 1000,30000
```

Measured on this Mac: ~200 ms round trip, ~280 KiB/s each way (PPSSPP serves debugger requests once per
frame and polling harder stalls the emulated CPU). That limits emulator demos only.

## 6. Tests

```bash
make -C common/psp/test                   # C link logic on macOS (ASan/UBSan)
.venv/bin/python -m pytest -q common/python/tests   # protocol, C/Python golden vectors, mock e2e, emulator e2e
```

## 7. Real hardware

See `docs/HARDWARE_TEST.md` (USB smoke test with `examples/echo`), then each branch's `HARDWARE_TEST.md`.
