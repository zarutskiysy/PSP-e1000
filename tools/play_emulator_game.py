#!/usr/bin/env python3
"""play_emulator_game.py — one full Blackwater Ping loop: Mac game (pygame, headless) <-> the real PSP
EBOOT running in PPSSPP, linked by tools/ppsspp_bridge.py. A scripted "PSP player" presses buttons
in the emulator through the WebSocket debugger (START, X pings, D-pad to crack the locks) and
screenshots are saved from both screens.

    python tools/play_emulator_game.py [--port 45673] [--out docs/img] [--keep]

The lock solution is computed from the HACK_REQ seed with bw_proto.hack_generate(), the Python
mirror of the C puzzle generator (the PSP itself never tells the Mac the answer).
Prints a JSON summary; exit code 0 when the game ended and both locks were opened via the PSP.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "game" / "mac"))
import bw_proto as G  # noqa: E402
from ppsspp import Ppsspp  # noqa: E402

PSPDEV = pathlib.Path(os.environ.get("PSPDEV", pathlib.Path.home() / "pspdev"))


def tap(emu: Ppsspp, button: str, gap: float = 0.12) -> None:
    emu.press(button, 3)
    time.sleep(gap)  # the console is edge-triggered: leave release frames between presses


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=45673, help="PPSSPP debugger port (track C uses 45673)")
    ap.add_argument("--out", default=str(ROOT / "docs" / "img"))
    ap.add_argument("--max-seconds", type=float, default=240)
    ap.add_argument("--ping-every", type=float, default=3.0)
    ap.add_argument("--keep", action="store_true", help="leave PPSSPP running at the end")
    a = ap.parse_args(argv)
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="bw_emu_"))
    evlog = tmp / "events.jsonl"
    evlog.write_text("")

    env = dict(os.environ, PATH=f"{PSPDEV}/bin:{os.environ['PATH']}", PSPDEV=str(PSPDEV))
    subprocess.run(["make", "-s", "-C", str(ROOT / "game/psp")], check=True, env=env)
    Ppsspp.kill(a.port)
    emu = Ppsspp.launch(ROOT / "game/psp/EBOOT.PBP", a.port)
    br = subprocess.Popen([sys.executable, str(ROOT / "tools/ppsspp_bridge.py"), "--port", str(a.port),
                           "--listen", "0", "--quiet"], stdout=subprocess.PIPE, text=True)
    line = br.stdout.readline()
    if not line.startswith("LISTEN "):
        raise SystemExit(f"bridge failed: {line!r}")
    lport = int(line.split()[1])
    summary_path = tmp / "mac_summary.json"
    mac = subprocess.Popen([sys.executable, str(ROOT / "game/mac/blackwater.py"), "--transport",
                            f"tcp:127.0.0.1:{lport}", "--headless", "--bot", "--easy", "--exit-on-over",
                            "--state-hz", "8", "--max-seconds", str(a.max_seconds), "--event-log", str(evlog),
                            "--summary", str(summary_path), "--shot-hack", str(out / "mac_emu_hack.png"),
                            "--shot-ping", str(out / "mac_emu_ping.png"), "--shot", str(out / "mac_emu_end.png"),
                            "--quiet"])
    res = {"hacks_solved_on_psp": 0, "pings_pressed": 0}
    try:
        time.sleep(4.0)  # link up: Mac HELLO -> bridge -> mailbox -> PSP
        emu.screenshot(out / "psp_emu_title.png")
        tap(emu, "start")
        seen = 0
        last_ping = 0.0
        shot_play = False
        t0 = time.monotonic()
        while mac.poll() is None and time.monotonic() - t0 < a.max_seconds:
            recs = [json.loads(x) for x in evlog.read_text().splitlines() if x.strip()]
            new = recs[seen:]
            seen = len(recs)
            for r in new:
                if r["ev"] == "hack_req":
                    time.sleep(1.0)  # HACK_REQ travels through the bridge (~100-200 ms) + puzzle draws
                    target, start = G.hack_generate(r["seed"], r["difficulty"])
                    if res["hacks_solved_on_psp"] == 0:
                        emu.screenshot(out / "psp_emu_hack.png")
                    for i, (t, s) in enumerate(zip(target, start)):
                        for _ in range((t - s) % 8):
                            tap(emu, "up")
                        if i + 1 < len(target):
                            tap(emu, "right")
                    if res["hacks_solved_on_psp"] == 0:
                        emu.screenshot(out / "psp_emu_hack_solved.png")
                    tap(emu, "cross")
                    res["hacks_solved_on_psp"] += 1
                elif r["ev"] == "over":
                    time.sleep(1.0)
                    emu.screenshot(out / "psp_emu_over.png")
            if not new and time.monotonic() - last_ping > a.ping_every:
                tap(emu, "cross")
                last_ping = time.monotonic()
                res["pings_pressed"] += 1
                if res["pings_pressed"] == 3 and not shot_play:
                    time.sleep(0.6)
                    emu.screenshot(out / "psp_emu_sonar.png")
                    shot_play = True
            time.sleep(0.1)
        mac.wait(timeout=30)
    finally:
        if mac.poll() is None:
            mac.terminate()
        br.terminate()
        if not a.keep:
            emu.quit()
    mac_sum = json.loads(summary_path.read_text()) if summary_path.exists() else {}
    res["mac"] = mac_sum
    print(json.dumps(res))
    ok = mac_sum.get("outcome") in ("won", "lost") and mac_sum.get("gates_open", 0) >= 1
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
