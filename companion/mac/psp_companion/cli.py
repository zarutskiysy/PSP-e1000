"""psp-companion: command line for the daemon, sessions, demo and installation."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

from . import install as inst
from .config import Paths, default_transport
from .ipc import DaemonNotRunning, call
from .rollout import recent_sessions

EX_NO_SESSION = 3
EX_SANDBOX = 75


def _daemon_argv(transport: str) -> list[str]:
    return [sys.executable, "-m", "psp_companion.cli", "daemon", "--foreground", "--transport", transport]


def ensure_daemon(paths: Paths, transport: str) -> tuple[dict, bool]:
    """Returns (ping reply, started_now). Safe to race: the daemon's file lock lets only one survive."""
    try:
        return call(paths.sock, "ping", timeout=2), False
    except DaemonNotRunning:
        if os.environ.get("CODEX_SANDBOX"):
            raise  # a daemon started here would inherit the sandbox and could never reach the USB port
    paths.ensure()
    with open(paths.home / "daemon.out", "ab") as out:
        subprocess.Popen(_daemon_argv(transport), stdin=subprocess.DEVNULL, stdout=out, stderr=out, cwd=str(paths.home),
                         start_new_session=True, close_fds=True)
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        try:
            return call(paths.sock, "ping", timeout=2), True
        except DaemonNotRunning:
            time.sleep(0.1)
    raise RuntimeError(f"daemon did not start; see {paths.log} and {paths.home / 'daemon.out'}")


def _blocked_by_sandbox(e: Exception) -> bool:
    cause = e.__cause__ if isinstance(e, DaemonNotRunning) else e
    return bool(os.environ.get("CODEX_SANDBOX")) and isinstance(cause or e, (PermissionError, OSError))


MODE_TEXT = {
    "observe": "Codex Desktop session, read-only (follows the session log)",
    "hooks": "Codex Desktop session, live through Codex hooks",
    "managed": "companion-managed App Server session",
    "demo": "demo",
}


def report(info: dict, status: dict, already: bool, hooks_file: bool) -> str:
    caps = info["capabilities"]
    lines = [
        ("Already attached:" if already else "Attached:") + f" {info['id']} ({info['label']})",
        f"Mode:      {MODE_TEXT.get(info['mode'], info['mode'])}",
        f"PSP:       {'linked' if status['psp']['linked'] else status['psp']['state']} [{status['psp']['transport']}]",
    ]
    if info["mode"] == "observe":
        lines.append("Shows:     turn start/end, reasoning, and commands and edits once they have finished")
        if hooks_file:
            lines.append("Hooks:     installed but no event received yet; if this persists, trust them in Codex Settings > Hooks")
        else:
            lines.append("Hooks:     not installed (optional: `psp-companion hooks install` adds live tool status and PSP approvals)")
    else:
        lines.append("Shows:     live turn, tool, command and edit status")
    lines.append("Approvals: " + ("answered with X/O on the PSP" if caps["approvals"] else "not on the PSP in this mode; approve in Codex Desktop"))
    lines.append("Actions:   " + ("available from the PSP menu" if caps["actions"] else "not available in this mode"))
    return "\n".join(lines)


def _wait_linked(paths: Paths, seconds: float) -> dict:
    deadline = time.monotonic() + seconds
    while True:
        st = call(paths.sock, "status")
        if st["psp"]["linked"] or time.monotonic() >= deadline:
            return st
        time.sleep(0.1)


def cmd_connect(a) -> int:
    paths = Paths.default()
    thread = a.thread or os.environ.get("CODEX_THREAD_ID")
    if a.managed:
        return cmd_start(a)
    if not thread and a.latest_in_cwd:
        found = recent_sessions(os.getcwd(), limit=1, max_age_s=900)
        if found:
            thread = found[0]["id"]
            print(f"Using the most recent session in this folder: {thread}")
    if not thread:
        print("Could not identify this Codex session: CODEX_THREAD_ID is not set.")
        found = recent_sessions(os.getcwd())
        if found:
            print("Recent sessions in this folder:")
            for f in found:
                print(f"  {f['id']}  ({f['age_s']} s ago)")
            print("Run again with --thread <id> (or --latest-in-cwd to take the newest).")
        else:
            print("No recent session was found in this folder. Run again with --thread <id>.")
        return EX_NO_SESSION
    try:
        _, started = ensure_daemon(paths, a.transport or default_transport(paths))
        r = call(paths.sock, "attach", thread_id=thread)
    except (DaemonNotRunning, PermissionError, OSError) as e:
        if _blocked_by_sandbox(e):
            print("Blocked by the Codex sandbox: this needs a local socket and USB access outside the workspace.")
            return EX_SANDBOX
        print(f"Cannot reach the companion daemon: {e}")
        return 1
    if not r.get("ok"):
        print(f"Could not attach: {r.get('error')}")
        return 1
    st = _wait_linked(paths, a.wait)
    if a.json:
        print(json.dumps({"attach": r, "status": st}, indent=2))
    else:
        print(report(r["session"], st, r.get("already", False), inst.hooks_installed()))
        if not st["psp"]["linked"]:
            print("The PSP is not linked yet. Connect the USB cable and open PSP AI Companion; the pet will pick this session up.")
    return 0


def cmd_start(a) -> int:
    paths = Paths.default()
    cwd = os.path.realpath(a.cwd or os.getcwd())
    try:
        ensure_daemon(paths, a.transport or default_transport(paths))
        r = call(paths.sock, "start_managed", cwd=cwd, approval_policy=a.approval_policy, sandbox=a.sandbox, ephemeral=a.ephemeral, model=a.model)
    except (DaemonNotRunning, PermissionError, OSError) as e:
        if _blocked_by_sandbox(e):
            print("Blocked by the Codex sandbox: this needs a local socket and USB access outside the workspace.")
            return EX_SANDBOX
        print(f"Cannot reach the companion daemon: {e}")
        return 1
    if not r.get("ok"):
        print(f"Could not start a session: {r.get('error')}")
        return 1
    st = _wait_linked(paths, a.wait)
    print(json.dumps({"attach": r, "status": st}, indent=2) if a.json else report(r["session"], st, False, False))
    return 0


def cmd_disconnect(a) -> int:
    paths = Paths.default()
    thread = None if a.all else (a.thread or os.environ.get("CODEX_THREAD_ID"))
    if not thread and not a.all:
        print("Could not identify this Codex session. Use --thread <id>, or --all to detach every session.")
        return EX_NO_SESSION
    try:
        r = call(paths.sock, "detach", thread_id=thread)
    except (DaemonNotRunning, PermissionError, OSError) as e:
        if _blocked_by_sandbox(e):
            print("Blocked by the Codex sandbox: this needs a local socket outside the workspace.")
            return EX_SANDBOX
        print("The companion daemon is not running; nothing to disconnect.")
        return 0
    print(f"Detached: {', '.join(r['detached'])}" if r.get("detached") else "This session was not attached.")
    return 0


def cmd_status(a) -> int:
    paths = Paths.default()
    try:
        st = call(paths.sock, "status", timeout=3)
    except DaemonNotRunning:
        print("daemon: not running")
        return 1
    if a.json:
        print(json.dumps(st, indent=2))
        return 0
    print(f"daemon: running   psp: {'linked' if st['psp']['linked'] else st['psp']['state']} [{st['psp']['transport']}]")
    if not st["sessions"]:
        print("sessions: none")
    for s in st["sessions"]:
        mark = "*" if s["active"] else " "
        print(f" {mark} {s['id']}  {s['mode']:8} {s['state']:9} {s['activity']}  ({s['label']})")
    if st.get("demo"):
        print(f"demo: {st['demo']['phase']}")
    return 0


def cmd_select(a) -> int:
    r = call(Paths.default().sock, "select", thread_id=a.thread)
    print("selected" if r.get("ok") else "no such session")
    return 0 if r.get("ok") else 1


def cmd_prompt(a) -> int:
    r = call(Paths.default().sock, "prompt", thread_id=a.thread, text=a.text)
    print(f"started turn {r.get('turn_id')}" if r.get("ok") else f"failed: {r.get('error')}")
    return 0 if r.get("ok") else 1


def cmd_stop(a) -> int:
    paths = Paths.default()
    try:
        call(paths.sock, "shutdown", timeout=5)
    except DaemonNotRunning:
        print("daemon was not running")
        return 0
    for _ in range(60):
        try:
            call(paths.sock, "ping", timeout=1)
            time.sleep(0.1)
        except DaemonNotRunning:
            print("daemon stopped")
            return 0
    print("daemon is still shutting down")
    return 1


def cmd_daemon(a) -> int:
    paths = Paths.default()
    transport = a.transport or default_transport(paths)
    if not a.foreground:
        _, started = ensure_daemon(paths, transport)
        print("daemon started" if started else "daemon already running")
        return 0
    from .daemon import run_daemon

    rc = run_daemon(paths, transport, os.environ.get("PSP_COMPANION_CODEX"), True)
    return 0 if rc == 3 else rc


def cmd_demo(a) -> int:
    paths = Paths.default()
    ensure_daemon(paths, a.transport or default_transport(paths))
    print("Open PSP AI Companion on the PSP. Waiting for the link...")
    deadline = time.monotonic() + a.wait
    while True:
        r = call(paths.sock, "demo_start", speed=a.speed, approval_timeout=a.approval_timeout)
        if r.get("ok"):
            break
        if not r.get("retry") or time.monotonic() >= deadline:
            print(f"Cannot start the demo: {r.get('error')}")
            return 1
        time.sleep(0.2)
    print("Demo running. Nothing here touches Codex. Press X or O on the PSP when it asks.")
    last = None
    try:
        while True:
            d = call(paths.sock, "demo_status", timeout=5).get("demo") or {}
            if d.get("phase") != last and d.get("phase"):
                last = d["phase"]
                print(f"  {last}")
            if d.get("finished"):
                print(f"Demo {d.get('outcome')}.")
                return 0 if d.get("outcome") == "completed" else 1
            time.sleep(0.1)
    except KeyboardInterrupt:
        call(paths.sock, "demo_stop", timeout=5)
        print("\nDemo stopped.")
        return 130


def cmd_install(a) -> int:
    r = inst.install(a.force, a.transport)
    print(f"Project:  {r['root']}\nSkills:   {', '.join(r['skills'])}\nLauncher: {r['launcher']}\nConfig:   {r['config']}")
    print("Done. In Codex, type $psp-connect.")
    return 0


def cmd_uninstall(a) -> int:
    print("Removed:", ", ".join(inst.uninstall()) or "nothing")
    return 0


def cmd_hooks(a) -> int:
    if a.action == "install":
        path = inst.hooks_install()
        print(f"Wrote {path}.")
        print("Codex runs a new hook only after you review and trust it: Codex Desktop > Settings > Hooks (or /hooks in the CLI).")
    elif a.action == "uninstall":
        print("Removed the PSP hooks." if inst.hooks_uninstall() else "No PSP hooks were installed.")
    else:
        print("installed" if inst.hooks_installed() else "not installed")
    return 0


def cmd_logs(a) -> int:
    path = Paths.default().log
    try:
        lines = path.read_text().splitlines()[-a.lines :]
    except OSError:
        print("no log yet")
        return 1
    print("\n".join(lines))
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="psp-companion")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, **kw):
        p = sub.add_parser(name, **kw)
        p.set_defaults(fn=fn)
        return p

    def managed_opts(p):
        p.add_argument("--cwd")
        p.add_argument("--approval-policy", default="on-request", choices=["on-request", "untrusted"])
        p.add_argument("--sandbox", default="workspace-write", choices=["workspace-write", "read-only"])
        p.add_argument("--ephemeral", action="store_true")
        p.add_argument("--model")

    p = add("connect", cmd_connect, help="attach this Codex session to the PSP")
    p.add_argument("--thread")
    p.add_argument("--latest-in-cwd", action="store_true", help="use the newest session started in this folder")
    p.add_argument("--managed", action="store_true", help="start a companion-managed App Server session instead")
    p.add_argument("--transport")
    p.add_argument("--wait", type=float, default=2.5, help="seconds to wait for the PSP link before reporting")
    p.add_argument("--json", action="store_true")
    managed_opts(p)

    p = add("start", cmd_start, help="start a companion-managed App Server session")
    p.add_argument("--transport")
    p.add_argument("--wait", type=float, default=2.5)
    p.add_argument("--json", action="store_true")
    managed_opts(p)

    p = add("disconnect", cmd_disconnect, help="detach a session")
    p.add_argument("--thread")
    p.add_argument("--all", action="store_true")

    p = add("status", cmd_status, help="show the daemon, PSP and sessions")
    p.add_argument("--json", action="store_true")

    p = add("select", cmd_select, help="show another attached session")
    p.add_argument("thread")

    p = add("prompt", cmd_prompt, help="send a prompt to a managed session")
    p.add_argument("text")
    p.add_argument("--thread")

    add("stop", cmd_stop, help="stop the daemon")

    p = add("daemon", cmd_daemon, help="start the daemon")
    p.add_argument("--foreground", action="store_true")
    p.add_argument("--transport")

    p = add("demo", cmd_demo, help="run the scripted demo on the PSP")
    p.add_argument("--transport")
    p.add_argument("--wait", type=float, default=60.0)
    p.add_argument("--speed", type=float, default=1.0)
    p.add_argument("--approval-timeout", type=float, default=45.0)

    p = add("install", cmd_install, help="install the global skills and launcher")
    p.add_argument("--force", action="store_true")
    p.add_argument("--transport")

    add("uninstall", cmd_uninstall, help="remove the skills and launcher")

    p = add("hooks", cmd_hooks, help="optional Codex hooks for Desktop sessions")
    p.add_argument("action", choices=["install", "uninstall", "status"])

    p = add("logs", cmd_logs, help="print the daemon log")
    p.add_argument("-n", "--lines", type=int, default=40)
    return ap


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
