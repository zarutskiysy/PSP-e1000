"""End-to-end, headless: the Mac game (game/mac/blackwater.py) against
  1. tools/fake_psp.py + tools/fake_psp_game.py (Python bot console),
  2. game/psp/host/psp_host (the PSP console C code built for macOS, bot input),
  3. the real EBOOT in PPSSPP via tools/ppsspp_bridge.py (slow; skipped without PPSSPP/pspdev,
     or unless BW_EMU=1).
"""
import json
import os
import pathlib
import socket
import subprocess
import sys
import time

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
PY = sys.executable
GAME = ROOT / "game/mac/blackwater.py"


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def run_mac(port, tmp, *extra, timeout=120):
    summary = tmp / "mac.json"
    cmd = [PY, str(GAME), "--transport", f"tcp:127.0.0.1:{port}", "--headless", "--bot", "--easy", "--speed", "4",
           "--exit-on-over", "--max-seconds", "90", "--quiet", "--summary", str(summary), *extra]
    subprocess.run(cmd, check=True, timeout=timeout, capture_output=True)
    return json.loads(summary.read_text())


@pytest.mark.parametrize("spec", ["foo", "tcp:127.0.0.1", "usb", "tcp::1", "tcp:h:99999"])
def test_bad_transport_exits_2(spec):
    r = subprocess.run([PY, str(GAME), "--transport", spec, "--headless"], capture_output=True, text=True, timeout=20)
    assert r.returncode == 2 and "bad --transport" in r.stderr


def test_mac_vs_python_fake_psp(tmp_path):
    port = free_port()
    fs = tmp_path / "fake.json"
    fake = subprocess.Popen([PY, str(ROOT / "tools/fake_psp.py"), "--port", str(port), "--app", "3", "--once",
                             "--quiet", "--plugin", str(ROOT / "tools/fake_psp_game.py"), "--", "--mark",
                             "--fail-first", "--listen-every", "4", "--summary", str(fs)])
    try:
        time.sleep(0.5)
        shot = tmp_path / "end.png"
        m = run_mac(port, tmp_path, "--shot", str(shot))
    finally:
        fake.wait(timeout=10)
    f = json.loads(fs.read_text())
    assert m["outcome"] in ("won", "lost")
    assert m["stats"]["hacks_failed"] >= 1  # --fail-first: alarm path exercised
    assert m["gates_open"] == 2 or m["outcome"] == "lost"
    assert m["stats"]["marks"] >= 1 and m["stats"]["listens"] >= 1
    assert f["echoes"] == m["echoes_sent"] and f["games"] == 1
    assert m["rx_frames"].get("PING_CMD", 0) >= 3
    assert shot.exists() and shot.stat().st_size > 5000


def test_mac_vs_psp_c_console_host_build(tmp_path):
    subprocess.run(["make", "-s", "-C", str(ROOT / "game/psp/host"), "psp_host"], check=True)
    port = free_port()
    ppm = tmp_path / "psp.ppm"
    psp = subprocess.Popen([str(ROOT / "game/psp/host/psp_host"), "--tcp", str(port), "--bot", "--shot", str(ppm)],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    time.sleep(0.3)
    m = run_mac(port, tmp_path)
    out, _ = psp.communicate(timeout=10)
    p = json.loads(out.strip().splitlines()[-1])
    assert m["outcome"] in ("won", "lost")
    assert p["phase"] == 3 and p["outcome"] == (1 if m["outcome"] == "won" else 2)
    assert p["pings"] == m["stats"]["pings"] and p["echoes"] == m["echoes_sent"]
    assert p["hacks_ok"] == m["stats"]["hacks_ok"] >= 1
    assert ppm.exists()


PPSSPP = os.environ.get("PPSSPP_BIN", "/Applications/PPSSPPSDL.app/Contents/MacOS/PPSSPPSDL")
PSPDEV = pathlib.Path(os.environ.get("PSPDEV", pathlib.Path.home() / "pspdev"))


@pytest.mark.skipif(not (os.environ.get("BW_EMU") == "1" and os.path.exists(PPSSPP)
                         and (PSPDEV / "bin/psp-gcc").exists()),
                    reason="set BW_EMU=1 (needs PPSSPP + pspdev; ~2 min)")
def test_mac_vs_eboot_in_ppsspp(tmp_path):
    port = os.environ.get("BW_EMU_PORT", "45673")  # track C's PPSSPP debugger port
    r = subprocess.run([PY, str(ROOT / "tools/play_emulator_game.py"), "--port", port, "--out", str(tmp_path)],
                       capture_output=True, text=True, timeout=400)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    res = json.loads(r.stdout.strip().splitlines()[-1])
    assert res["hacks_solved_on_psp"] >= 1 and res["mac"]["gates_open"] >= 1
