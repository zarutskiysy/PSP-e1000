"""The real PSP deck app in PPSSPP <-> the real Mac daemon (--dry-run), via tools/ppsspp_bridge.py.

Builds controller/psp, launches it in PPSSPP (debugger port 45671 = this track's port), injects
nub/button input through the debugger, and checks what the daemon would have posted.
Skipped when PPSSPP or the pspdev toolchain is missing. Takes ~40 s (the bridge slows the emulator
to ~8 emulated frames per wall second, so every hold below is long)."""
import json
import os
import pathlib
import subprocess
import sys
import time

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

PPSSPP = os.environ.get("PPSSPP_BIN", "/Applications/PPSSPPSDL.app/Contents/MacOS/PPSSPPSDL")
PSPDEV = pathlib.Path(os.environ.get("PSPDEV", pathlib.Path.home() / "pspdev"))
PORT = int(os.environ.get("DECK_PPSSPP_PORT", "45671"))

pytestmark = pytest.mark.skipif(not (os.path.exists(PPSSPP) and (PSPDEV / "bin/psp-gcc").exists()),
                                reason="PPSSPP or pspdev toolchain not installed")


def wait_for(pred, timeout, step=0.2):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(step)
    return False


@pytest.fixture(scope="module")
def deck(tmp_path_factory):
    from ppsspp import Ppsspp

    tmp = tmp_path_factory.mktemp("emu")
    env = dict(os.environ, PATH=f"{PSPDEV}/bin:{os.environ['PATH']}", PSPDEV=str(PSPDEV))
    subprocess.run(["make", "-s", "-C", str(ROOT / "controller/psp")], check=True, env=env, capture_output=True)
    Ppsspp.kill(PORT)
    emu = Ppsspp.launch(ROOT / "controller/psp/EBOOT.PBP", PORT)
    br = subprocess.Popen([sys.executable, str(ROOT / "tools/ppsspp_bridge.py"), "--port", str(PORT), "--listen", "0",
                           "--quiet"], stdout=subprocess.PIPE, text=True)
    line = br.stdout.readline()
    assert line.startswith("LISTEN "), line
    events, summary = tmp / "ev.jsonl", tmp / "sum.json"
    d = subprocess.Popen([sys.executable, str(ROOT / "controller/mac/psp_deck.py"), "-t",
                          f"tcp:127.0.0.1:{line.split()[1]}", "--dry-run", "--events-log", str(events),
                          "--summary", str(summary), "--duration", "60", "--once"],
                         stderr=subprocess.PIPE, text=True)
    try:
        yield emu, d, events, summary
    finally:
        d.terminate()
        try:
            d.wait(10)
        except subprocess.TimeoutExpired:
            d.kill()
        br.terminate()
        emu.ws.close()
        Ppsspp.kill(PORT)


def read_events(p):
    return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []


def test_psp_app_drives_mac_daemon(deck):
    emu, d, events, summary = deck
    # handshake: the PSP streams INPUT_STATE only once the bridge is up; wait for the first events file
    assert wait_for(lambda: events.exists(), 30), "daemon did not start"
    time.sleep(3)  # HELLO / WHEEL_CONFIG round trips at ~4 Hz through the bridge
    emu.analog(1.0, 0.0)
    assert wait_for(lambda: any(e["ev"] == "mouse_move" and e["dx"] > 0 for e in read_events(events)), 15)
    emu.analog(0, 0)
    emu.buttons(ltrigger=True)
    time.sleep(1.5)
    emu.buttons(ltrigger=False)
    assert wait_for(lambda: [(e["ev"], e.get("down")) for e in read_events(events) if e["ev"] == "mouse_button"]
                    == [("mouse_button", True), ("mouse_button", False)], 15)
    # action wheel: hold SELECT, aim at slice 2 (Screenshot, 4 o'clock), release
    emu.buttons(select=True)
    time.sleep(1.5)
    emu.analog(0.87, -0.5)
    time.sleep(2.5)
    emu.buttons(select=False)
    emu.analog(0, 0)
    assert wait_for(lambda: any(e["ev"] == "key" and e["key"] == "cmd+shift+3" for e in read_events(events)), 20)
    d.terminate()
    d.wait(15)
    s = json.loads(summary.read_text())
    assert s["wheel_fires"] == 1 and s["results"][0]["ok"] and s["results"][0]["slice"] == 2
    assert s["peer"] == "psp_deck" and s["inputs"] > 20 and s["rtt_samples"] >= 1
