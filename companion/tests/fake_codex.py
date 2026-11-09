#!/usr/bin/env python3
"""A scripted stand-in for `codex app-server` over stdio, so daemon tests spend no model quota.

The real protocol is checked separately by test_real_codex.py (opt-in). Behaviour:
  turn text containing "approve" -> requests a command approval, then reports the outcome;
  anything else                  -> completes straight away.
"""
import json
import sys

threads = 0
pending = {}


def send(msg):
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def notify(method, params):
    send({"method": method, "params": params})


def finish(thread, turn, status="completed"):
    notify("turn/completed", {"threadId": thread, "turn": {"id": turn, "status": status, "items": []}})


for line in sys.stdin:
    msg = json.loads(line)
    method, rid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if method == "initialize":
        send({"id": rid, "result": {"userAgent": "fake"}})
    elif method == "thread/start":
        threads += 1
        tid = f"00000000-0000-4000-8000-{threads:012d}"
        send({"id": rid, "result": {"thread": {"id": tid}}})
        notify("thread/started", {"thread": {"id": tid}})
    elif method == "turn/start":
        thread = params["threadId"]
        text = params["input"][0]["text"]
        turn = f"turn-{rid}"
        send({"id": rid, "result": {"turn": {"id": turn, "status": "inProgress", "items": []}}})
        notify("turn/started", {"threadId": thread, "turn": {"id": turn, "status": "inProgress"}})
        if "approve" in text:
            item = {"type": "commandExecution", "id": "cmd1", "command": "touch x", "status": "inProgress", "commandActions": []}
            notify("item/started", {"threadId": thread, "turnId": turn, "item": item})
            server_id = 9000 + rid
            pending[server_id] = (thread, turn)
            send({"id": server_id, "method": "item/commandExecution/requestApproval",
                  "params": {"threadId": thread, "turnId": turn, "itemId": "cmd1", "startedAtMs": 0, "command": "touch x", "cwd": "/"}})
        elif "hang" in text:
            pass
        else:
            finish(thread, turn)
    elif method == "turn/interrupt":
        send({"id": rid, "result": {}})
        finish(params["threadId"], params["turnId"], "interrupted")
    elif method == "thread/unsubscribe":
        send({"id": rid, "result": {}})
    elif rid in pending and ("result" in msg or "error" in msg):
        thread, turn = pending.pop(rid)
        decision = (msg.get("result") or {}).get("decision")
        notify("serverRequest/resolved", {"threadId": thread, "requestId": rid})
        with open(sys.argv[1], "a") if len(sys.argv) > 1 else open("/dev/null", "a") as f:
            f.write(f"{decision}\n")
        status = "completed" if decision == "accept" else "declined"
        item = {"type": "commandExecution", "id": "cmd1", "command": "touch x", "status": status, "exitCode": 0 if decision == "accept" else None}
        notify("item/completed", {"threadId": thread, "turnId": turn, "item": item})
        finish(thread, turn)
