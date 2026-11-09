#!/usr/bin/env python3
"""Real Codex against the real EBOOT (in PPSSPP). Uses a few small model turns of the user's Codex quota.
Codex's sandbox stays on throughout; nothing here disables it or bypasses approvals.

  python companion/tests/ppsspp_real_codex.py OUT_DIR

A) A real `codex exec` in workspace-write: the installed $psp-connect skill must report the sandbox block
   (exit 75), the session's CODEX_THREAD_ID must match, and attaching that thread from outside must follow
   its real events on the PSP.
B) A companion-managed App Server session (approval policy untrusted): real approvals answered with
   emulated X and O, then quick actions and interrupt.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "companion/tests")]

from ppsspp import Ppsspp  # noqa: E402
from ppsspp_demo import CLI, EBOOT, EMU_PORT, TCP_PORT, shot  # noqa: E402


def main() -> int:
    out = pathlib.Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    project = pathlib.Path(tempfile.mkdtemp(prefix="psp_codex_test_", dir=out))
    transport = f"tcp:127.0.0.1:{TCP_PORT}"
    env = {**os.environ, "PSP_COMPANION_TRANSPORT": transport}
    results: list[tuple[str, bool, str]] = []

    def cli(*args, check=True, timeout=60):
        r = subprocess.run([str(CLI), *args], env=env, capture_output=True, text=True, timeout=timeout)
        if check and r.returncode:
            raise RuntimeError(f"{args}: {r.stdout}{r.stderr}")
        return r

    def status():
        return json.loads(cli("status", "--json").stdout)

    def check(name, ok, detail=""):
        results.append((name, bool(ok), str(detail)))
        print(("PASS " if ok else "FAIL ") + name, str(detail)[:200])

    def wait_for(pred, timeout=120.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            st = status()
            v = pred(st)
            if v:
                return v
            time.sleep(0.25)
        return None

    emu = Ppsspp.launch(EBOOT, port=EMU_PORT)
    bridge = None
    try:
        emu.wait_running()
        time.sleep(1.5)
        bridge = subprocess.Popen([sys.executable, str(ROOT / "tools/ppsspp_bridge.py"), "--port", str(EMU_PORT), "--listen", str(TCP_PORT), "--quiet"])
        cli("daemon", "--transport", transport)
        check("psp linked", wait_for(lambda s: s["psp"]["linked"], 25))

        # ---- A: a real Codex session with its sandbox on ------------------------------------
        prompt = ("$psp-connect\n\nWhatever that reports, also run these shell commands one at a time: "
                  "printenv CODEX_THREAD_ID, then sleep 6 && ls -la, then false. Then answer with the single word DONE.")
        log_path = out / "codex_exec.jsonl"
        log = open(log_path, "w")
        codex = subprocess.Popen(["codex", "exec", "--skip-git-repo-check", "--json", "-s", "workspace-write", "-C", str(project),
                                  "-c", 'model_reasoning_effort="low"', prompt], stdout=log, stderr=subprocess.STDOUT, env=os.environ)
        seen: list[tuple[str, str]] = []
        tid = None
        attached = None
        shots = 0
        end = time.monotonic() + 240
        while codex.poll() is None and time.monotonic() < end:
            if tid is None:
                for line in open(log_path):
                    if line.startswith("{") and '"thread.started"' in line:
                        tid = json.loads(line).get("thread_id")
            elif attached is None:
                r = cli("connect", "--thread", tid, "--json", check=False)
                if r.returncode == 0:
                    attached = json.loads(r.stdout)["attach"]["session"]
            st = status()
            if st["sessions"]:
                s = st["sessions"][0]
                cur = (s["state"], s["activity"])
                if not seen or seen[-1] != cur:
                    seen.append(cur)
                    print("   ", cur)
                    if shots < 8:
                        time.sleep(0.5)
                        shot(emu, out / f"session_{shots}_{s['state'].lower()}.png")
                        shots += 1
            time.sleep(0.25)
        codex.wait(timeout=10)
        time.sleep(1.5)
        final = status()["sessions"]
        text = log_path.read_text()
        check("codex exec finished", codex.returncode == 0, codex.returncode)
        check("skill was invoked and reported the sandbox block", "blocked by the codex sandbox" in text.lower())  # the agent may paraphrase
        check("CODEX_THREAD_ID inside Codex is this session", tid and text.count(tid) >= 2, tid)
        check("attached that real session", attached is not None and attached["id"] == tid)
        check("attached in observe mode", attached and attached["mode"] == "observe")
        check("real events changed the pet", len(seen) >= 3, seen)
        check("a real finished command was shown", any("Ran:" in t or t == "Command failed" for _, t in seen), seen)
        check("real turn completion was shown", any(a == "SUCCESS" for a, _ in seen) or (final and final[0]["state"] in ("SUCCESS", "IDLE")), final and final[0]["activity"])

        r = cli("connect", "--thread", tid)
        check("reconnecting is idempotent", "Already attached" in r.stdout and len(status()["sessions"]) == 1, r.stdout.splitlines()[0])
        r = cli("disconnect", "--thread", tid)
        check("disconnect", status()["sessions"] == [], r.stdout.strip())

        # ---- B: managed session, real approvals -----------------------------------------------
        r = json.loads(cli("start", "--cwd", str(project), "--approval-policy", "untrusted", "--ephemeral", "--json").stdout)
        check("managed session started", r["attach"]["ok"], r["attach"].get("thread_id"))
        time.sleep(1.0)

        def approval_round(fname, button):
            cli("prompt", f"Use the shell to run exactly this command and nothing else: touch {fname}")
            got = wait_for(lambda s: s["sessions"] and s["sessions"][0]["pending_approvals"] > 0, 90)
            check(f"real approval request reached the PSP ({button})", got)
            time.sleep(1.8)  # past the arm delay, and let the overlay land
            shot(emu, out / f"approval_{button}.png")
            emu.press(button, frames=4)
            done = wait_for(lambda s: s["sessions"] and s["sessions"][0]["turn_id"] is None and s["sessions"][0]["pending_approvals"] == 0, 120)
            check(f"turn finished after {button}", done)
            return (project / fname).exists()

        check("X allowed: the command really ran", approval_round("psp_allowed.txt", "cross") is True)
        time.sleep(5.0)
        check("O denied: the command did not run", approval_round("psp_denied.txt", "circle") is False)
        time.sleep(5.0)

        # quick action: DOWN selects "Summarize progress", X runs it
        emu.press("down", frames=4)
        time.sleep(1.0)
        shot(emu, out / "action_chip.png")
        emu.press("cross", frames=4)
        began = wait_for(lambda s: s["sessions"][0]["turn_id"] is not None, 30)
        check("quick action started a real turn", began)
        ended = wait_for(lambda s: s["sessions"][0]["turn_id"] is None, 120)
        check("quick action turn completed", ended)
        time.sleep(5.0)

        # interrupt: a long command, then DOWN x3 to "Interrupt task", X twice
        cli("prompt", "Use the shell to run exactly: sleep 60")
        wait_for(lambda s: s["sessions"][0]["pending_approvals"] > 0 or s["sessions"][0]["state"] in ("RUNNING", "WORKING"), 90)
        if status()["sessions"][0]["pending_approvals"]:
            time.sleep(1.8)
            emu.press("cross", frames=4)
            wait_for(lambda s: s["sessions"][0]["pending_approvals"] == 0, 20)
        time.sleep(2.0)
        for _ in range(3):
            emu.press("down", frames=4)
            time.sleep(0.35)
        emu.press("cross", frames=4)
        time.sleep(0.8)
        shot(emu, out / "interrupt_confirm.png")
        emu.press("cross", frames=4)
        stopped = wait_for(lambda s: s["sessions"][0]["turn_id"] is None, 40)
        st = status()["sessions"][0]
        check("interrupt stopped the real turn", stopped and st["activity"] == "Interrupted", st["activity"])
    finally:
        cli("stop", check=False)
        if bridge is not None:
            bridge.terminate()
        try:
            emu.quit()
        except Exception:
            Ppsspp.kill(EMU_PORT)
    bad = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(bad)} passed, {len(bad)} failed")
    for name, _ok, detail in bad:
        print(" FAILED:", name, detail[:300])
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
