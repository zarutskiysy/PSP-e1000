"""Normalises the three Codex event sources into one small vocabulary, and turns that into pet state.

Sources (all pure functions of the raw data, so they are unit-tested against real payload shapes):
  from_appserver  JSON-RPC notifications from `codex app-server` (live, per-item start and end)
  from_hook       official Codex lifecycle hooks (live tool start/end, approvals)
  from_rollout    the session's rollout .jsonl (read-only; items appear when they COMPLETE)
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .protocol import Agent, Anim
from .text import ellipsize, is_test_command, shorten_path, summarize_command, to_ascii


@dataclass
class Ev:
    kind: str
    text: str = ""
    turn_id: str | None = None
    ok: bool | None = None
    is_test: bool = False


def _paths_of(changes) -> list[str]:
    if isinstance(changes, dict):
        return [str(k) for k in changes]
    if isinstance(changes, list):
        return [str(c.get("path", "")) for c in changes if isinstance(c, dict) and c.get("path")]
    return []


def _editing_text(paths: list[str], verb: str = "Editing") -> str:
    if not paths:
        return f"{verb} files"
    more = f" (+{len(paths) - 1})" if len(paths) > 1 else ""
    return f"{verb} {shorten_path(paths[0], 44)}{more}"


def _command_event(command, actions) -> Ev:
    if is_test_command(command):
        return Ev("running", "Running tests", is_test=True)
    for a in actions or []:
        if not isinstance(a, dict):
            continue
        t = a.get("type")
        if t == "read":
            return Ev("running", f"Reading {shorten_path(str(a.get('name') or a.get('path') or 'file'), 48)}")
        if t in ("listFiles", "list_files"):
            return Ev("running", "Listing files")
        if t == "search":
            q = a.get("query")
            return Ev("running", f"Searching: {ellipsize(to_ascii(str(q)), 48)}" if q else "Searching files")
    return Ev("running", f"Running: {summarize_command(command, 58)}")


def _command_finished(command, exit_code, status=None) -> list[Ev]:
    test = is_test_command(command)
    if status in ("declined", "Declined"):
        return [Ev("command_done", "Command declined", ok=None)]
    if exit_code is None:
        return [Ev("command_done", "", ok=None, is_test=test)]
    ok = exit_code == 0
    if test:
        return [Ev("command_done", "Tests passed" if ok else "Tests failed", ok=ok, is_test=True)]
    return [Ev("command_done", "" if ok else "Command failed", ok=ok)]


# ---- App Server --------------------------------------------------------------
def from_appserver(method: str, p: dict) -> list[Ev]:
    if method == "turn/started":
        return [Ev("turn_start", turn_id=(p.get("turn") or {}).get("id"))]
    if method == "turn/completed":
        t = p.get("turn") or {}
        tid, st = t.get("id"), t.get("status")
        if st == "completed":
            return [Ev("turn_done", turn_id=tid)]
        if st == "interrupted":
            return [Ev("turn_interrupted", turn_id=tid)]
        msg = ((t.get("error") or {}).get("message")) or "Task failed"
        return [Ev("turn_failed", ellipsize(to_ascii(str(msg)), 64), turn_id=tid)]
    if method == "item/started":
        it = p.get("item") or {}
        ty = it.get("type")
        if ty == "userMessage":
            parts = [c.get("text", "") for c in it.get("content") or [] if isinstance(c, dict) and c.get("type") == "text"]
            return [Ev("user_msg", "New task: " + ellipsize(to_ascii(" ".join(parts)), 58))] if "".join(parts).strip() else []
        if ty == "reasoning" or ty == "plan":
            return [Ev("thinking")]
        if ty == "commandExecution":
            return [_command_event(it.get("command"), it.get("commandActions"))]
        if ty == "fileChange":
            return [Ev("editing", _editing_text(_paths_of(it.get("changes"))))]
        if ty == "agentMessage":
            return [Ev("reply", "Writing reply")]
        if ty == "mcpToolCall":
            return [Ev("tool", ellipsize(to_ascii(f"Using {it.get('server')}: {it.get('tool')}"), 64))]
        if ty == "dynamicToolCall":
            return [Ev("tool", ellipsize(to_ascii(f"Using {it.get('tool')}"), 64))]
        if ty == "webSearch":
            return [Ev("tool", "Searching the web")]
        if ty in ("collabAgentToolCall", "subAgentActivity"):
            return [Ev("tool", "Working with a sub-agent")]
        if ty == "contextCompaction":
            return [Ev("tool", "Compacting context")]
        if ty == "imageGeneration":
            return [Ev("tool", "Generating an image")]
        return []
    if method == "item/completed":
        it = p.get("item") or {}
        ty = it.get("type")
        if ty == "commandExecution":
            return _command_finished(it.get("command"), it.get("exitCode"), it.get("status"))
        if ty == "fileChange":
            return [Ev("file_done", ok=it.get("status") == "completed")]
        return []
    if method == "error":
        err = p.get("error") or {}
        msg = ellipsize(to_ascii(str(err.get("message") or "Codex error")), 64)
        return [Ev("retrying", "Reconnecting to the model...")] if p.get("willRetry") else [Ev("error", msg)]
    return []


# ---- Hooks ---------------------------------------------------------------------
_PATCH_FILE_RE = re.compile(r"^\*\*\* (?:Update|Add|Delete) File: (.+)$", re.M)
_EXIT_RE = re.compile(r"[Ee]xit(?:ed with)?(?: code| status)?:?\s*(-?\d+)")


def patch_paths(tool_input) -> list[str]:
    text = tool_input.get("command") if isinstance(tool_input, dict) else None
    return _PATCH_FILE_RE.findall(text) if isinstance(text, str) else []


def _tool_label(name: str) -> str:
    if name.startswith("mcp__"):
        parts = name.split("__")
        if len(parts) >= 3:
            return ellipsize(to_ascii(f"Using {parts[1]}: {parts[2]}"), 64)
    return ellipsize(to_ascii(f"Using {name}"), 64)


def from_hook(p: dict) -> list[Ev]:
    event, turn = p.get("hook_event_name"), p.get("turn_id")
    tool, tin = str(p.get("tool_name") or ""), p.get("tool_input") or {}
    if event == "UserPromptSubmit":
        return [Ev("turn_start", turn_id=turn)]
    if event == "PreToolUse":
        if tool == "Bash":
            return [_command_event(tin.get("command") if isinstance(tin, dict) else None, None)]
        if tool == "apply_patch":
            return [Ev("editing", _editing_text(patch_paths(tin)))]
        return [Ev("tool", _tool_label(tool))]
    if event == "PostToolUse":
        if tool == "Bash":
            m = _EXIT_RE.search(str(p.get("tool_response") or ""))
            return _command_finished(tin.get("command") if isinstance(tin, dict) else None, int(m.group(1)) if m else None)
        if tool == "apply_patch":
            return [Ev("file_done", ok=True)]
        return [Ev("command_done", ok=None)]
    if event == "Stop":
        return [Ev("turn_done", turn_id=turn)]
    if event == "Interrupt":
        return [Ev("turn_interrupted", turn_id=turn)]
    if event == "PreCompact":
        return [Ev("tool", "Compacting context")]
    if event == "SessionEnd":
        return [Ev("session_end")]
    return []


# ---- Rollout -------------------------------------------------------------------
def from_rollout(rec: dict) -> list[Ev]:
    t, p = rec.get("type"), rec.get("payload") or {}
    if not isinstance(p, dict):
        return []
    if t == "event_msg":
        k = p.get("type")
        if k == "task_started":
            return [Ev("turn_start", turn_id=p.get("turn_id"))]
        if k == "task_complete":
            return [Ev("turn_done", turn_id=p.get("turn_id"))]
        if k == "turn_aborted":
            return [Ev("turn_interrupted", turn_id=p.get("turn_id"))]
        if k != "item_completed":
            return []
        it = p.get("item") or {}
        ty = it.get("type")
        if ty == "Reasoning":
            return [Ev("thinking")]
        if ty == "CommandExecution":
            cmd, code = it.get("command"), it.get("exit_code")
            first = Ev("tool", f"Ran: {summarize_command(cmd, 60)}")
            if is_test_command(cmd):
                first = Ev("tool", "Ran tests")
            return [first] + ([e for e in _command_finished(cmd, code, it.get("status")) if e.text])
        if ty == "FileChange":
            return [Ev("editing", _editing_text(_paths_of(it.get("changes")), "Edited"))]
        if ty == "AgentMessage":
            return [Ev("reply", "Writing reply")] if it.get("phase") != "final_answer" else []
        if ty == "McpToolCall":
            return [Ev("tool", ellipsize(to_ascii(f"Used {it.get('server')}: {it.get('tool')}"), 64))]
        if ty == "ContextCompaction":
            return [Ev("tool", "Compacted context")]
        if ty in ("SubAgentActivity", "CollabAgentToolCall"):
            return [Ev("tool", "Working with a sub-agent")]
        return []
    if t == "response_item" and p.get("type") in ("custom_tool_call", "function_call", "local_shell_call"):
        return [Ev("tool", "Working...")]
    return []


# ---- State machine -------------------------------------------------------------
DWELL_S = 1.4       # a pass/fail flash stays visible at least this long
SUCCESS_HOLD_S = 4.0
FAILED_HOLD_S = 5.0


class AgentMachine:
    """Reduces events to (state, activity) plus one-shot animations. No I/O; time is passed in."""

    def __init__(self) -> None:
        self.state = Agent.IDLE
        self.activity = "Idle"
        self.turn_id: str | None = None
        self.waiting_approval = False
        self.dwell_until = 0.0
        self.deferred: Ev | None = None
        self.hold_until = 0.0  # terminal state: return to idle at this time
        self.before_approval: tuple[Agent, str] | None = None

    @property
    def turn_active(self) -> bool:
        return self.turn_id is not None or self.state in (Agent.THINKING, Agent.EDITING, Agent.RUNNING, Agent.TESTING, Agent.TALKING, Agent.WORKING)

    def _set(self, state: Agent, text: str) -> None:
        self.state, self.activity = state, text

    def _work_state(self) -> None:
        self._set(Agent.THINKING, "Thinking...")

    def set_approval(self, waiting: bool) -> None:
        self.waiting_approval = waiting
        if waiting:
            if self.state != Agent.APPROVAL:
                self.before_approval = (self.state, self.activity)
            self._set(Agent.APPROVAL, "Waiting for approval")
        elif self.state == Agent.APPROVAL:
            # back to what it was doing: an allowed command is about to run, not "thinking"
            state, text = self.before_approval or (Agent.THINKING, "Thinking...")
            self.before_approval = None
            self._set(state, text)

    def apply(self, ev: Ev, now: float) -> Anim:
        k = ev.kind
        if k in ("turn_done", "turn_failed", "turn_interrupted", "error", "session_end", "turn_start"):
            self.dwell_until = 0.0
            self.deferred = None
        elif now < self.dwell_until:
            self.deferred = ev
            return Anim.NONE
        return self._apply(ev, now)

    def _apply(self, ev: Ev, now: float) -> Anim:
        k = ev.kind
        if k == "turn_start":
            self.turn_id = ev.turn_id or self.turn_id or "?"
            self.hold_until = 0.0
            self._set(Agent.THINKING, "Thinking...")
            return Anim.BOUNCE
        if k == "turn_done":
            self.turn_id = None
            self.waiting_approval = False
            self._set(Agent.SUCCESS, "Task complete")
            self.hold_until = now + SUCCESS_HOLD_S
            return Anim.CELEBRATE
        if k == "turn_failed":
            self.turn_id = None
            self.waiting_approval = False
            self._set(Agent.FAILED, ev.text or "Task failed")
            self.hold_until = now + FAILED_HOLD_S
            return Anim.FAIL
        if k == "turn_interrupted":
            self.turn_id = None
            self.waiting_approval = False
            self._set(Agent.IDLE, "Interrupted")
            return Anim.NONE
        if k == "session_end":
            self.turn_id = None
            self.waiting_approval = False
            self._set(Agent.SLEEPING, "Session ended")
            return Anim.NONE
        if k == "error":
            self._set(Agent.FAILED, ev.text or "Codex error")
            self.hold_until = now + FAILED_HOLD_S
            return Anim.FAIL
        if self.waiting_approval:  # the pet stays visibly anxious until the approval resolves
            return Anim.NONE
        if k == "sleep":
            self._set(Agent.SLEEPING, ev.text or "Zzz...")
        elif k == "wake":
            self._set(Agent.IDLE, ev.text or "Idle")
            return Anim.WAKE
        elif k == "user_msg":
            self._set(Agent.THINKING, ev.text)
        elif k == "thinking":
            self._set(Agent.THINKING, "Thinking...")
        elif k == "editing":
            self._set(Agent.EDITING, ev.text)
        elif k == "running":
            self._set(Agent.TESTING if ev.is_test else Agent.RUNNING, ev.text)
        elif k == "tool":
            self._set(Agent.WORKING, ev.text)
        elif k == "reply":
            self._set(Agent.TALKING, ev.text)
        elif k == "retrying":
            self.activity = ev.text
        elif k == "file_done":
            self._work_state()
        elif k == "command_done":
            if ev.ok is False:
                self._set(Agent.FAILED, ev.text or "Command failed")
                self.dwell_until = now + DWELL_S
                return Anim.FAIL
            if ev.is_test and ev.ok:
                self._set(Agent.SUCCESS, ev.text or "Tests passed")
                self.dwell_until = now + DWELL_S
                return Anim.BOUNCE
            if ev.text:
                self.activity = ev.text
            self._work_state()
        return Anim.NONE

    def tick(self, now: float) -> Anim:
        if self.dwell_until and now >= self.dwell_until:
            self.dwell_until = 0.0
            pending, self.deferred = self.deferred, None
            if pending is not None:
                return self._apply(pending, now)
            if self.turn_active and self.state in (Agent.FAILED, Agent.SUCCESS):
                self._work_state()
        if self.hold_until and now >= self.hold_until:
            self.hold_until = 0.0
            if self.state in (Agent.SUCCESS, Agent.FAILED) and self.turn_id is None:
                self._set(Agent.IDLE, "Idle")
        return Anim.NONE
