#!/usr/bin/env python3
"""Runs the real EBOOT in PPSSPP against the real daemon through tools/ppsspp_bridge.py and walks the demo,
pressing the real emulated buttons and saving a screenshot per phase.

  python companion/tests/ppsspp_demo.py OUT_DIR [--button cross|circle]

Checks: the face animates with no Mac attached, the demo completes, X reaches the Mac, and the face keeps
animating while the link is down.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "companion/mac"), str(ROOT / "common/python")]

from ppsspp import Ppsspp  # noqa: E402

CLI = ROOT / "tools" / "psp-companion"
EBOOT = ROOT / "companion" / "psp" / "EBOOT.PBP"
EMU_PORT = 45695
TCP_PORT = 47195


def digest(png: bytes) -> str:
    return hashlib.sha1(png).hexdigest()[:10]


def shot(emu, path) -> bytes:
    """Reads both framebuffers and keeps the finished one: the CPU can be paused mid-draw on the back buffer,
    which then lacks whatever is drawn last (text, overlays)."""
    import io

    from PIL import Image

    best, best_n = b"", -1
    for addr in ("0x04000000", "0x04088000"):
        png = emu.screenshot(fb=f"{addr}:8888:512")
        im = Image.open(io.BytesIO(png)).convert("L").point(lambda v: 255 if v > 200 else 0)
        n = im.histogram()[255]
        if n > best_n:
            best, best_n = png, n
    pathlib.Path(path).write_bytes(best)
    return best


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--button", default="cross", choices=["cross", "circle"])
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PSP_COMPANION_TRANSPORT": f"tcp:127.0.0.1:{TCP_PORT}"}

    def cli(*args, check=True):
        r = subprocess.run([str(CLI), *args], env=env, capture_output=True, text=True, timeout=30)
        if check and r.returncode:
            raise RuntimeError(f"{args}: {r.stdout}{r.stderr}")
        return r

    emu = Ppsspp.launch(EBOOT, port=EMU_PORT)
    bridge = None
    failures: list[str] = []
    try:
        emu.wait_running()
        time.sleep(2.0)
        # 1. no Mac at all: the pet must still be moving
        frames = []
        for i in range(4):
            frames.append(digest(shot(emu, out / f"00_unlinked_{i}.png")))
            time.sleep(0.4)
        print("unlinked frames:", frames)
        if len(set(frames)) < 3:
            failures.append("face did not animate while unlinked")

        bridge = subprocess.Popen([sys.executable, str(ROOT / "tools/ppsspp_bridge.py"), "--port", str(EMU_PORT), "--listen", str(TCP_PORT), "--quiet"])
        cli("daemon", "--transport", f"tcp:127.0.0.1:{TCP_PORT}")
        for _ in range(100):
            st = json.loads(cli("status", "--json").stdout)
            if st["psp"]["linked"]:
                break
            time.sleep(0.2)
        else:
            raise RuntimeError(f"no link: {st['psp']}")
        print("linked over the bridge")
        time.sleep(1.0)
        shot(emu, out / "01_linked_no_session.png")

        demo = subprocess.Popen([str(CLI), "demo", "--transport", f"tcp:127.0.0.1:{TCP_PORT}"], env=env, stdout=subprocess.PIPE, text=True, bufsize=1)
        seen = set()
        pressed = False
        sock = pathlib.Path(os.environ.get("PSP_COMPANION_HOME") or "~/.psp-companion").expanduser() / "daemon.sock"
        from psp_companion.ipc import call

        while demo.poll() is None:
            d = call(sock, "demo_status", timeout=5).get("demo") or {}
            phase = d.get("phase") or ""
            key = phase.split(" ")[0]
            if key and key not in seen:
                seen.add(key)
                time.sleep(1.3 if not key.startswith("8") else 2.2)
                name = f"demo_{key.replace('-', '_').zfill(2)}.png"
                shot(emu, out / name)
                print("shot", name, "-", phase)
            if phase.startswith("8") and not pressed:
                emu.press(a.button, frames=4)
                pressed = True
                print("pressed", a.button)
            time.sleep(0.05)
        rest = demo.stdout.read()
        print(rest[-200:])
        if demo.returncode != 0:
            failures.append(f"demo exit {demo.returncode}")

        # 2. Buttons over the real path
        before = json.loads(cli("status", "--json").stdout)["stats"]["buttons"]
        emu.press("select", frames=4)
        time.sleep(1.2)
        after = json.loads(cli("status", "--json").stdout)["stats"]["buttons"]
        print("buttons", before, "->", after)
        if after <= before:
            failures.append("button press did not reach the Mac")
        shot(emu, out / "02_diag.png")
        emu.press("select", frames=4)

        # 3. Pull the link: the Mac must notice, the face must keep moving
        bridge.terminate()
        bridge.wait(timeout=5)
        bridge = None
        time.sleep(5.0)
        st = json.loads(cli("status", "--json").stdout)
        print("after bridge loss:", st["psp"])
        if st["psp"]["linked"]:
            failures.append("daemon still thinks the PSP is linked")
        frames = []
        for i in range(4):
            frames.append(digest(shot(emu, out / f"03_link_lost_{i}.png")))
            time.sleep(0.4)
        print("link-lost frames:", frames)
        if len(set(frames)) < 3:
            failures.append("face stopped animating after link loss")

        # 4. And come back
        bridge = subprocess.Popen([sys.executable, str(ROOT / "tools/ppsspp_bridge.py"), "--port", str(EMU_PORT), "--listen", str(TCP_PORT), "--quiet"])
        for _ in range(100):
            st = json.loads(cli("status", "--json").stdout)
            if st["psp"]["linked"]:
                print("relinked")
                break
            time.sleep(0.2)
        else:
            failures.append("daemon did not relink")
        time.sleep(1.0)
        shot(emu, out / "04_relinked.png")
    finally:
        cli("stop", check=False)
        if bridge is not None:
            bridge.terminate()
        try:
            emu.quit()
        except Exception:
            Ppsspp.kill(EMU_PORT)
    print("FAILURES:" if failures else "ALL OK", failures or "")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
