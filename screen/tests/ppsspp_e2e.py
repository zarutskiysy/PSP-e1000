#!/usr/bin/env python3
"""Runs the real PSP app (screen/psp/EBOOT.PBP) in PPSSPP and checks what it shows, pixel-exactly.

  replay (default): the Mac encoder records a stream (psp_screen.py --transport record:...), the EBOOT
                    replays it from its folder (screen.cfg = replay). Deterministic, no bridge needed.
  mailbox:          the live sender streams through tools/ppsspp_bridge.py (PPSSPP WebSocket debugger
                    memory access) -> fps is debugger-bound; reported, not asserted.

The check reads the 565 framebuffer straight from emulated VRAM (0x04000000, stride 512) and compares
rows 0..263 (the last 8 rows hold the stats line) with the source frame converted to PSP 565.

    python screen/tests/ppsspp_e2e.py [--mode replay|mailbox] [--source image:screen/tests/data/desktop.png]
                                      [--shot docs/img/x.png] [--port 45672]
Exit code 0 = pixel-exact.
"""
from __future__ import annotations

import argparse
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "screen" / "mac")]

import numpy as np  # noqa: E402

from ppsspp import Ppsspp  # noqa: E402
from sources import make_source  # noqa: E402

PY = sys.executable


def read_fb(emu: Ppsspp) -> np.ndarray:
    raw = emu.read(0x04000000, 512 * 272 * 2)
    return np.frombuffer(raw, "<u2").reshape(272, 512)[:, :480]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="replay", choices=["replay", "mailbox"])
    ap.add_argument("--source", default="image:screen/tests/data/desktop.png")
    ap.add_argument("--frames", type=int, default=60)
    ap.add_argument("--port", type=int, default=45672)
    ap.add_argument("--shot", help="also save a PPSSPP screenshot PNG here")
    ap.add_argument("--wait", type=float, default=6.0)
    ap.add_argument("--fps", type=float, default=30.0, help="mailbox: sender target fps")
    ap.add_argument("--lz4", default="auto")
    ap.add_argument("--keep", action="store_true", help="leave PPSSPP running")
    a = ap.parse_args()

    import os
    pspdev = os.environ.get("PSPDEV", os.path.expanduser("~/pspdev"))
    env = dict(os.environ, PATH=f"{pspdev}/bin:" + os.environ["PATH"])
    subprocess.run(["make", "-s", "-C", str(ROOT / "screen" / "psp")], check=True, env=env)
    run = pathlib.Path(tempfile.mkdtemp(prefix="pspscreen_"))
    shutil.copy(ROOT / "screen" / "psp" / "EBOOT.PBP", run / "EBOOT.PBP")
    (run / "screen.cfg").write_text(a.mode + "\n")
    sender = None
    if a.mode == "replay":
        subprocess.run([PY, str(ROOT / "screen/mac/psp_screen.py"), "--transport", f"record:{run / 'stream.bin'}",
                        "--source", a.source, "--fps", "0", "--frames", str(a.frames), "--key-interval", "0"],
                       check=True, cwd=ROOT)
    Ppsspp.kill(a.port)
    emu = Ppsspp.launch(run / "EBOOT.PBP", a.port)
    try:
        if a.mode == "mailbox":
            bridge = subprocess.Popen([PY, str(ROOT / "tools/ppsspp_bridge.py"), "--port", str(a.port),
                                       "--listen", "47102"], cwd=ROOT)
            time.sleep(2)
            sender = subprocess.Popen([PY, str(ROOT / "screen/mac/psp_screen.py"), "--transport", "tcp:127.0.0.1:47102",
                                       "--source", a.source, "--fps", str(a.fps), "--frames", str(a.frames), "--lz4", a.lz4,
                                       "--ack-timeout", "20", "--handshake-timeout", "30"], cwd=ROOT)
            sender.wait(timeout=600)
            bridge.terminate()
        else:
            time.sleep(a.wait)
        emu.request("cpu.stepping", _by_event=True)
        try:
            got = read_fb(emu).copy()
        finally:
            emu.request("cpu.resume", _by_event=True)
        if a.shot:
            emu.screenshot(a.shot, fb="0x04000000:565:512")
        src = make_source(a.source)
        want = src.frame(a.frames - 1)
        diff = np.argwhere(got[:264] != want[:264])
        print(f"[e2e] {a.mode}: {len(diff)} differing pixels in rows 0..263"
              + (f", first at {diff[0].tolist()}" if len(diff) else " -> PIXEL-EXACT"))
        return 0 if len(diff) == 0 else 1
    finally:
        if not a.keep:
            emu.quit()


if __name__ == "__main__":
    sys.exit(main())
