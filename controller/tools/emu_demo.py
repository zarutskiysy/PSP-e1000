#!/usr/bin/env python3
"""Drive the deck app in PPSSPP (already running, bridged) and take screenshots for docs/img.

    python tools/ppsspp.py run controller/psp/EBOOT.PBP --port 45671
    python tools/ppsspp_bridge.py --port 45671 --listen 47181 &
    python controller/mac/psp_deck.py -t tcp:127.0.0.1:47181 --dry-run --events-log ev.jsonl --duration 60 &
    python controller/tools/emu_demo.py --port 45671 --out docs/img
"""
import argparse
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from ppsspp import Ppsspp  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, default=45671)
ap.add_argument("--out", default=str(ROOT / "docs" / "img"))
ap.add_argument("--slice-xy", default="0.87,-0.5",
                help="analog x,y (+y = up) that points at a slice; default = slice 2 (4 o'clock, Screenshot)")
a = ap.parse_args()
out = pathlib.Path(a.out)
out.mkdir(parents=True, exist_ok=True)
emu = Ppsspp(a.port)
sx, sy = map(float, a.slice_xy.split(","))

emu.screenshot(out / "deck_linked.png")
emu.analog(1.0, 0.0); time.sleep(1.5); emu.analog(0, 0)            # cursor right
emu.buttons(ltrigger=True); time.sleep(0.6); emu.buttons(ltrigger=False)  # left click
time.sleep(0.4)
emu.press("cross", frames=6); time.sleep(0.6)                       # return
emu.buttons(select=True); time.sleep(0.6)                           # open wheel
emu.analog(sx, sy); time.sleep(1.2)
emu.screenshot(out / "deck_wheel_open.png")
emu.buttons(select=False); emu.analog(0, 0)                         # release -> fire
time.sleep(3.0)
emu.screenshot(out / "deck_action_result.png")
print("ok", out)
