#!/usr/bin/env python3
"""Codex lifecycle hook: forwards the event to the PSP companion daemon.

Installed by `psp-companion hooks install`. Silent and harmless when the daemon is not running or the
session is not attached: it exits 0 with no output, which Codex treats as "no opinion". It prints a
decision only for a PermissionRequest that a person answered on the PSP.
"""
import json
import os
import socket
import sys


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    home = os.path.expanduser(os.environ.get("PSP_COMPANION_HOME") or "~/.psp-companion")
    wait = 125.0 if payload.get("hook_event_name") == "PermissionRequest" else 2.0
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(wait)
    try:
        s.connect(os.path.join(home, "daemon.sock"))
        s.sendall(json.dumps({"op": "hook", "payload": payload}).encode() + b"\n")
        data = b""
        while b"\n" not in data:
            chunk = s.recv(65536)
            if not chunk:
                break
            data += chunk
    except OSError:
        return 0
    finally:
        s.close()
    try:
        reply = json.loads(data.split(b"\n", 1)[0])
    except ValueError:
        return 0
    if isinstance(reply, dict) and reply.get("hookSpecificOutput"):
        print(json.dumps({"hookSpecificOutput": reply["hookSpecificOutput"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
