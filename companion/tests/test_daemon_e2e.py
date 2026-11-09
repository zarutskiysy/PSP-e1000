"""The real daemon process, the real CLI and hook script, against a fake PSP and a scripted app-server."""
import json
import os
import pathlib
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid

import pytest

from fake_psp import FakePsp
from psp_companion import protocol as P

ROOT = pathlib.Path(__file__).resolve().parents[2]
CLI = ROOT / "tools" / "psp-companion"
FAKE_CODEX = ROOT / "companion" / "tests" / "fake_codex.py"
HOOK = ROOT / "companion" / "skills" / "psp-connect" / "scripts" / "psp_hook.py"


def short_tmp() -> str:
    d = tempfile.mkdtemp(prefix="pc")
    if len(d) + len("/daemon.sock") < 100:
        return d
    os.rmdir(d)
    return tempfile.mkdtemp(prefix="pc", dir="/tmp")  # AF_UNIX paths are limited to 104 bytes on macOS


class Env:
    def __init__(self):
        self.home = short_tmp()
        self.psp = FakePsp()
        self.codex_home = pathlib.Path(self.home) / "codex"
        self.decisions = pathlib.Path(self.home) / "decisions.txt"
        wrapper = pathlib.Path(self.home) / "fakecodex"
        wrapper.write_text(f'#!/bin/bash\nexec {sys.executable} {FAKE_CODEX} {self.decisions}\n')
        wrapper.chmod(0o755)
        self.environ = {
            **os.environ,
            "PSP_COMPANION_HOME": self.home,
            "PSP_COMPANION_TRANSPORT": f"tcp:127.0.0.1:{self.psp.port}",
            "PSP_COMPANION_CODEX": str(wrapper),
            "CODEX_HOME": str(self.codex_home),
        }
        self.environ.pop("CODEX_THREAD_ID", None)
        self.environ.pop("CODEX_SANDBOX", None)

    def run(self, *args, env=None, check=True, timeout=25):
        e = {**self.environ, **(env or {})}
        r = subprocess.run([str(CLI), *args], env=e, capture_output=True, text=True, timeout=timeout)
        if check and r.returncode != 0:
            raise AssertionError(f"{args}: rc={r.returncode}\n{r.stdout}\n{r.stderr}")
        return r

    def status(self):
        return json.loads(self.run("status", "--json").stdout)

    def make_rollout(self, cwd="/tmp/project", tid=None):
        tid = tid or str(uuid.uuid4())
        d = self.codex_home / "sessions/2026/11/09"
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"rollout-2026-11-09T10-00-00-{tid}.jsonl"
        path.write_text(json.dumps({"type": "session_meta", "payload": {"id": tid, "cwd": cwd}}) + "\n")
        return tid, path

    def close(self):
        self.run("stop", check=False)
        self.psp.close()
        shutil.rmtree(self.home, ignore_errors=True)


@pytest.fixture
def env():
    e = Env()
    yield e
    e.close()


def append(path, rec):
    with open(path, "a") as f:
        f.write(json.dumps(rec) + "\n")


def event(payload):
    return {"type": "event_msg", "payload": payload}


def test_daemon_starts_once_and_links(env):
    r1 = env.run("daemon")
    r2 = env.run("daemon")
    assert "started" in r1.stdout and "already" in r2.stdout
    env.psp.wait_linked()
    st = env.status()
    assert st["psp"]["linked"] is True and st["sessions"] == []


def test_state_directory_is_private(env):
    env.run("daemon")
    assert stat.S_IMODE(os.stat(env.home).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(f"{env.home}/daemon.sock").st_mode) == 0o600


def test_concurrent_start_leaves_one_daemon(env):
    procs = [subprocess.Popen([str(CLI), "daemon"], env=env.environ, stdout=subprocess.DEVNULL) for _ in range(5)]
    for p in procs:
        p.wait(timeout=20)
    pids = {json.loads(subprocess.check_output(["/bin/cat", f"{env.home}/daemon.lock"]) or b"0")}
    assert len(pids) == 1
    env.psp.wait_linked()
    time.sleep(0.5)
    assert env.psp.hellos == 1


def test_connect_identifies_session_and_follows_it(env):
    tid, path = env.make_rollout("/tmp/my-project")
    r = env.run("connect", env={"CODEX_THREAD_ID": tid})
    assert f"Attached: {tid}" in r.stdout and "read-only" in r.stdout and "approve in Codex Desktop" in r.stdout
    env.psp.wait(lambda: (env.psp.latest(P.T_CONN) or {}).get("label") == "my-project")
    append(path, event({"type": "task_started", "turn_id": "T1"}))
    env.psp.wait_state(P.Agent.THINKING)
    append(path, event({"type": "item_completed", "item": {"type": "FileChange", "changes": {"app/main.py": {}}}}))
    env.psp.wait_activity("Edited app/main.py")
    assert env.psp.latest(P.T_AGENT)["state"] == P.Agent.EDITING
    append(path, event({"type": "task_complete", "turn_id": "T1"}))
    env.psp.wait_state(P.Agent.SUCCESS)
    env.psp.wait(lambda: any(a["anim"] == P.Anim.CELEBRATE for a in env.psp.all(P.T_ANIM)))


def test_repeated_connect_is_safe(env):
    tid, _ = env.make_rollout()
    env.run("connect", env={"CODEX_THREAD_ID": tid})
    pid = open(f"{env.home}/daemon.lock").read()
    r = env.run("connect", env={"CODEX_THREAD_ID": tid})
    assert "Already attached" in r.stdout
    assert open(f"{env.home}/daemon.lock").read() == pid
    assert len(env.status()["sessions"]) == 1
    assert env.psp.hellos == 1


def test_connect_without_identity_attaches_nothing(env):
    tid, _ = env.make_rollout(os.getcwd())
    r = subprocess.run([str(CLI), "connect"], env=env.environ, capture_output=True, text=True, timeout=20, cwd=os.getcwd())
    assert r.returncode == 3 and "CODEX_THREAD_ID is not set" in r.stdout and tid in r.stdout
    assert not os.path.exists(f"{env.home}/daemon.sock")  # no guess, nothing started


def test_sandboxed_connect_never_starts_a_daemon(env):
    tid, _ = env.make_rollout()
    r = env.run("connect", "--thread", tid, env={"CODEX_SANDBOX": "seatbelt"}, check=False)
    assert r.returncode == 75 and "Blocked by the Codex sandbox" in r.stdout
    assert not os.path.exists(f"{env.home}/daemon.sock")


def test_connect_rejects_bad_or_unknown_ids(env):
    r = env.run("connect", "--thread", "../../etc/passwd", check=False)
    assert r.returncode == 1 and "not a Codex thread id" in r.stdout
    r = env.run("connect", "--thread", str(uuid.uuid4()), check=False)
    assert r.returncode == 1 and "no rollout found" in r.stdout


def test_connect_rejects_mismatched_rollout(env):
    tid, path = env.make_rollout()
    path.write_text(json.dumps({"type": "session_meta", "payload": {"id": str(uuid.uuid4()), "cwd": "/x"}}) + "\n")
    r = env.run("connect", "--thread", tid, check=False)
    assert r.returncode == 1 and "does not belong" in r.stdout


def test_disconnect(env):
    tid, _ = env.make_rollout()
    env.run("connect", env={"CODEX_THREAD_ID": tid})
    r = env.run("disconnect", env={"CODEX_THREAD_ID": tid})
    assert tid in r.stdout and env.status()["sessions"] == []
    env.psp.wait(lambda: env.psp.latest(P.T_CONN)["conn"] == P.Conn.NONE)
    assert "not attached" in env.run("disconnect", env={"CODEX_THREAD_ID": tid}).stdout


def test_reconnects_after_cable_pull(env):
    tid, path = env.make_rollout()
    env.run("connect", env={"CODEX_THREAD_ID": tid})
    env.psp.wait_linked()
    n = env.psp.hellos
    env.psp.drop()
    env.psp.wait(lambda: env.psp.hellos > n, timeout=10)
    env.psp.wait(lambda: env.status()["psp"]["linked"], timeout=5)
    assert env.status()["sessions"][0]["id"] == tid  # the session survives the replug


def test_detects_a_silent_psp(env):
    env.psp.heartbeat = False
    env.run("daemon")
    env.psp.wait_linked()
    n = env.psp.hellos
    env.psp.wait(lambda: env.psp.hellos > n, timeout=8)  # watchdog dropped it and reconnected


def test_refuses_wrong_app(env):
    env.psp.app = 1
    env.run("daemon")
    env.psp.wait(lambda: env.psp.hellos >= 2, timeout=10)
    st = env.status()
    assert st["psp"]["linked"] is False and "another app" in st["psp"]["state"]


def managed(env):
    r = env.run("start", "--cwd", env.home, "--json")
    tid = json.loads(r.stdout)["attach"]["thread_id"]
    env.psp.wait(lambda: (env.psp.latest(P.T_CONN) or {}).get("mode") == P.Mode.MANAGED)
    return tid


def test_managed_session_approval_allow(env):
    managed(env)
    assert "started" in env.run("prompt", "please approve this").stdout
    req = env.psp.wait_approval()
    assert req["title"] == "Run command?" and req["detail"] == "touch x"
    env.psp.wait_state(P.Agent.APPROVAL)
    env.psp.respond(req["id"], P.Decision.ALLOW)
    assert env.psp.wait_close(req["id"])["reason"] == P.Close.ALLOWED
    env.psp.wait_state(P.Agent.SUCCESS)
    assert env.decisions.read_text() == "accept\n"


def test_managed_session_approval_deny(env):
    managed(env)
    env.run("prompt", "please approve this")
    req = env.psp.wait_approval()
    env.psp.respond(req["id"], P.Decision.DENY)
    assert env.psp.wait_close(req["id"])["reason"] == P.Close.DENIED
    env.psp.wait(lambda: env.decisions.exists())
    assert env.decisions.read_text() == "decline\n"


def test_psp_loss_declines_pending_approval(env):
    managed(env)
    env.run("prompt", "please approve this")
    env.psp.wait_approval()
    env.psp.reconnect = True
    env.psp.drop()
    env.psp.wait(lambda: env.decisions.exists(), timeout=8)
    assert env.decisions.read_text() == "decline\n"


def test_no_ipc_operation_can_decide_an_approval(env):
    from psp_companion.ipc import call

    managed(env)
    env.run("prompt", "please approve this")
    req = env.psp.wait_approval()
    sock = pathlib.Path(env.home) / "daemon.sock"
    for op in ("approve", "approval", "respond", "decide", "approval_resp"):
        r = call(sock, op, req_id=req["id"], id=req["id"], decision="accept")
        assert r["ok"] is False and "unknown op" in r["error"]
    assert not env.decisions.exists() and env.status()["sessions"][0]["pending_approvals"] == 1


def test_quick_action_runs_in_the_connected_session(env):
    managed(env)
    env.psp.wait(lambda: dict((i, e) for i, e, _ in env.psp.latest(P.T_ACTIONS)["items"]).get(P.Action.TESTS))
    req = env.psp.action(P.Action.TESTS)
    env.psp.wait(lambda: any(a["req"] == req and a["status"] == P.Ack.ACCEPTED for a in env.psp.all(P.T_ACTION_ACK)))
    env.psp.wait(lambda: any(a["req"] == req and a["status"] == P.Ack.DONE for a in env.psp.all(P.T_ACTION_ACK)))


def test_buttons_reach_the_mac(env):
    env.run("daemon")
    env.psp.wait_linked()
    env.psp.button(4)
    env.psp.button(4, False)
    env.psp.wait(lambda: env.status()["stats"]["buttons"] == 2)


def run_hook(env, payload):
    return subprocess.Popen([sys.executable, "-I", "-S", str(HOOK)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                            env={"PSP_COMPANION_HOME": env.home})


def test_hook_script_full_decision(env):
    tid, _ = env.make_rollout()
    env.run("connect", env={"CODEX_THREAD_ID": tid})
    p = run_hook(env, None)
    p.stdin.write(json.dumps({"hook_event_name": "PermissionRequest", "session_id": tid, "turn_id": "T1", "tool_name": "Bash", "tool_input": {"command": "rm -rf build"}, "cwd": "/x"}))
    p.stdin.close()
    req = env.psp.wait_approval()
    assert req["detail"] == "rm -rf build" and req["flags"] & P.AF_ACTIONABLE
    env.psp.wait(lambda: env.psp.latest(P.T_CONN)["mode"] == P.Mode.HOOKS)
    env.psp.respond(req["id"], P.Decision.ALLOW)
    out = p.stdout.read()
    assert p.wait(timeout=5) == 0
    assert json.loads(out) == {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {"behavior": "allow"}}}


def test_hook_script_is_silent_for_other_sessions(env):
    env.run("daemon")
    p = run_hook(env, None)
    out, _ = p.communicate(json.dumps({"hook_event_name": "PermissionRequest", "session_id": str(uuid.uuid4()), "tool_name": "Bash", "tool_input": {"command": "x"}}), timeout=10)
    assert p.returncode == 0 and out == ""


def test_hook_script_is_silent_without_a_daemon(env):
    p = run_hook(env, None)
    out, _ = p.communicate(json.dumps({"hook_event_name": "PermissionRequest"}), timeout=10)
    assert p.returncode == 0 and out == ""


def test_demo_command_end_to_end(env):
    env.run("daemon")
    env.psp.wait_linked()
    proc = subprocess.Popen([str(CLI), "demo", "--speed", "12"], env=env.environ, stdout=subprocess.PIPE, text=True)
    req = env.psp.wait_approval(timeout=20)
    assert req["flags"] & P.AF_DEMO
    time.sleep(0.5)  # the CLI polls progress, so stay on this step long enough to be reported
    env.psp.respond(req["id"], P.Decision.ALLOW)
    out, _ = proc.communicate(timeout=30)
    assert proc.returncode == 0 and "Demo completed." in out
    assert "8 permission request" in out and "15 back to idle" in out
    assert env.status()["sessions"] == []
    assert not env.decisions.exists()


def test_demo_refuses_while_a_real_session_is_attached(env):
    tid, _ = env.make_rollout()
    env.run("connect", env={"CODEX_THREAD_ID": tid})
    env.psp.wait_linked()
    r = env.run("demo", "--wait", "1", check=False)
    assert r.returncode == 1 and "real session" in r.stdout


def test_clean_shutdown(env):
    env.run("daemon")
    env.psp.wait_linked()
    assert "stopped" in env.run("stop").stdout
    assert not os.path.exists(f"{env.home}/daemon.sock")
    env.psp.wait(lambda: env.psp.link is None, timeout=5)
    assert "not running" in env.run("status", check=False).stdout


def test_daemon_recovers_a_stale_socket(env):
    env.run("daemon")
    pid = int(open(f"{env.home}/daemon.lock").read())
    os.kill(pid, 9)
    time.sleep(0.3)
    assert os.path.exists(f"{env.home}/daemon.sock")  # left behind by the crash
    assert "started" in env.run("daemon").stdout
    env.psp.wait_linked(timeout=10)
