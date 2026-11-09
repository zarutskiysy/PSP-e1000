"""All daemon state and policy. Single-threaded: every call runs on the daemon's core loop, so no locks.

Everything external is injected (PSP link, Codex App Server, rollout tailers, the clock), which is what
makes the approval and session rules testable without hardware or a model.

Safety rules enforced here:
  * An approval is decided only by APPROVAL_RESP from the PSP. The IPC surface has no verb for it.
  * A response must name the approval currently on screen for the active session, its turn must still
    be the running one, and it must not have expired or been answered already.
  * "Allow" means once. acceptForSession and execpolicy amendments are never sent.
  * Timeout or PSP disconnect never allows: App Server requests are declined, hook requests return
    no decision (Codex then shows its own prompt).
"""
from __future__ import annotations

import logging
import os
import secrets
import time
from dataclasses import dataclass, field
from typing import Callable

from . import protocol as P
from .events import AgentMachine, Ev, from_appserver, from_hook, from_rollout
from .text import ellipsize, shorten_path, summarize_command, to_ascii

log = logging.getLogger("psp_companion.core")

APPROVAL_TIMEOUT_S = 120.0
HOOK_APPROVAL_TIMEOUT_S = 110.0  # the installed hook's own timeout is longer than this
SAFE_POLICIES = ("untrusted", "on-request")
SAFE_SANDBOXES = ("read-only", "workspace-write")

PROMPTS = {
    P.Action.CONTINUE: "Continue working on the current task.",
    P.Action.SUMMARIZE: "Summarize the progress so far in a few short bullet points. Do not change any files.",
    P.Action.TESTS: (
        "Run this project's test suite from the current working directory and report the result. "
        "If you cannot determine how to run the tests, say so instead of guessing."
    ),
    P.Action.ERRORS: "Inspect the most recent errors in this session and explain the likely cause. Do not change any files.",
}
ACTION_LABELS = {
    P.Action.CONTINUE: "Continue",
    P.Action.SUMMARIZE: "Summary",
    P.Action.TESTS: "Tests",
    P.Action.ERRORS: "Error check",
    P.Action.INTERRUPT: "Interrupt",
}
MODE_NAMES = {
    P.Mode.OBSERVE: "observe",
    P.Mode.HOOKS: "hooks",
    P.Mode.MANAGED: "managed",
    P.Mode.DEMO: "demo",
}

APPROVAL_METHODS = (
    "item/commandExecution/requestApproval",
    "item/fileChange/requestApproval",
    "item/permissions/requestApproval",
)


@dataclass
class Approval:
    req_id: int
    sid: str
    kind: int
    title: str
    detail: str
    responder: Callable[[P.Decision | None], None]
    deadline: float
    timeout_s: int
    turn_id: str | None = None
    rpc_id: object = None
    actionable: bool = True
    demo: bool = False
    closed: bool = False


@dataclass
class Session:
    sid: str
    mode: P.Mode
    cwd: str
    label: str
    machine: AgentMachine = field(default_factory=AgentMachine)
    conn: P.Conn = P.Conn.ATTACHED
    approvals: list[Approval] = field(default_factory=list)
    tail: object = None
    hooks_seen: bool = False
    file_items: dict = field(default_factory=dict)
    action_ack: tuple[int, str] | None = None  # (req, label) of a quick action whose turn is running
    action_busy: bool = False                  # a turn/start is in flight
    source: str = ""


class Core:
    def __init__(self, psp, codex=None, start_tail: Callable | None = None, clock=time.monotonic):
        self.psp = psp
        self.codex = codex
        self.start_tail = start_tail
        self.clock = clock
        self.sessions: dict[str, Session] = {}
        self.order: list[str] = []
        self.active: str | None = None
        self.approvals: dict[int, Approval] = {}
        self.shown: int | None = None
        self.psp_up = False
        self.psp_boot: int | None = None
        self.sent: dict[int, bytes] = {}
        self.demo = None
        self.last_demo: dict | None = None
        self.stats = {"bad_frames": 0, "stale_responses": 0, "buttons": 0}
        self.last_error: str | None = None

    # ---- helpers ----------------------------------------------------------
    @property
    def current(self) -> Session | None:
        return self.sessions.get(self.active) if self.active else None

    def _send(self, type_: int, payload: bytes) -> None:
        if self.psp_up:
            self.psp.send(type_, payload)

    def _send_changed(self, type_: int, payload: bytes) -> None:
        if self.sent.get(type_) != payload:
            self.sent[type_] = payload
            self._send(type_, payload)

    def _anim(self, a: P.Anim) -> None:
        if a != P.Anim.NONE:
            self._send(P.T_ANIM, P.anim(a))

    def _new_req_id(self) -> int:
        while True:  # random, so an id from an earlier connection or app run cannot match
            v = secrets.randbelow(0xFFFFFFFF) + 1
            if v not in self.approvals:
                return v

    @staticmethod
    def _caps(s: Session) -> int:
        if s.mode == P.Mode.MANAGED:
            return P.CAP_APPROVALS | P.CAP_ACTIONS | P.CAP_LIVE_TOOLS
        if s.mode in (P.Mode.HOOKS, P.Mode.DEMO):
            return P.CAP_APPROVALS | P.CAP_LIVE_TOOLS
        return 0

    def _action_table(self) -> list[tuple[int, bool, str]]:
        s = self.current
        ids = [P.Action.CONTINUE, P.Action.SUMMARIZE, P.Action.TESTS, P.Action.ERRORS, P.Action.INTERRUPT]
        if s is None:
            return [(i, False, "No session attached") for i in ids]
        if s.mode == P.Mode.DEMO:
            return [(i, False, "Not available in demo") for i in ids]
        if s.mode != P.Mode.MANAGED:
            return [(i, False, "Use Codex Desktop for this") for i in ids]
        if s.conn != P.Conn.ATTACHED:
            return [(i, False, "Codex is reconnecting") for i in ids]
        running = s.machine.turn_id is not None or s.action_busy
        out: list[tuple[int, bool, str]] = []
        for i in ids:
            if i == P.Action.INTERRUPT:
                ok = s.machine.turn_id is not None
                out.append((i, ok, "" if ok else "No turn is running"))
            else:
                out.append((i, not running, "" if not running else "Agent is busy"))
        return out

    def _sync(self) -> None:
        if not self.psp_up:
            return
        s = self.current
        if s is None:
            self._send_changed(P.T_CONN, P.conn(P.Conn.NONE, P.Mode.NONE, 0, 0, 0, ""))
            self._send_changed(P.T_AGENT, P.agent(P.Agent.SLEEPING))
            self._send_changed(P.T_ACTIVITY, P.activity(""))
        else:
            conn = s.conn
            if s.mode == P.Mode.DEMO and self.demo is not None and self.demo.hide_conn:
                conn = P.Conn.NONE
            self._send_changed(P.T_CONN, P.conn(conn, s.mode, self._caps(s), self.order.index(s.sid), len(self.order), s.label))
            self._send_changed(P.T_AGENT, P.agent(s.machine.state))
            self._send_changed(P.T_ACTIVITY, P.activity(s.machine.activity))
        self._send_changed(P.T_ACTIONS, P.actions(self._action_table()))
        self._present_approval()

    def _present_approval(self) -> None:
        s = self.current
        head = s.approvals[0] if s and s.approvals else None
        wanted = head.req_id if head is not None else None
        if wanted != self.shown:
            if self.shown is not None:  # still pending, but not for the session on screen
                self._send(P.T_APPROVAL_CLOSE, P.approval_close(self.shown, P.Close.HIDDEN))
                self.shown = None
            if head is not None:
                flags = (P.AF_ACTIONABLE if head.actionable else 0) | (P.AF_DEMO if head.demo else 0)
                left = max(0, int(head.deadline - self.clock()))
                self._send(P.T_APPROVAL_REQ, P.approval_req(head.req_id, head.kind, flags, left, len(s.approvals), head.title, head.detail))
                self.shown = head.req_id

    def _refresh_waiting(self, s: Session) -> None:
        s.machine.set_approval(bool(s.approvals))

    # ---- approvals ---------------------------------------------------------
    def add_approval(self, s: Session, *, kind: int, title: str, detail: str, responder, turn_id=None, rpc_id=None,
                     timeout: float = APPROVAL_TIMEOUT_S, actionable: bool = True, demo: bool = False) -> Approval:
        a = Approval(self._new_req_id(), s.sid, kind, ellipsize(to_ascii(title), P.TITLE_MAX), ellipsize(to_ascii(detail), P.DETAIL_MAX),
                     responder, self.clock() + timeout, int(timeout), turn_id, rpc_id, actionable, demo)
        s.approvals.append(a)
        self.approvals[a.req_id] = a
        self._refresh_waiting(s)
        log.info("approval %08x opened sid=%s turn=%s kind=%d", a.req_id, s.sid, turn_id, kind)
        self._sync()
        return a

    def _close_approval(self, a: Approval, reason: P.Close, text: str = "", decision: P.Decision | None = None, respond: bool = True) -> None:
        if a.closed:
            return
        a.closed = True
        self.approvals.pop(a.req_id, None)
        s = self.sessions.get(a.sid)
        if s is not None and a in s.approvals:
            s.approvals.remove(a)
        delivered = True
        if respond:
            try:
                a.responder(decision)
            except Exception as e:  # the decision did not reach Codex: say so instead of claiming success
                delivered = False
                log.warning("approval %08x: could not deliver decision: %s", a.req_id, e)
        if self.shown == a.req_id:
            self.shown = None
            if not delivered:
                self._send(P.T_APPROVAL_CLOSE, P.approval_close(a.req_id, P.Close.FAILED, "Could not reach Codex"))
            else:
                self._send(P.T_APPROVAL_CLOSE, P.approval_close(a.req_id, reason, text))
        log.info("approval %08x closed reason=%s decision=%s delivered=%s", a.req_id, P.Close(reason).name, decision and decision.name, delivered)
        if s is not None:
            self._refresh_waiting(s)

    def _on_approval_resp(self, m: P.ApprovalResp) -> None:
        a = self.approvals.get(m.req_id)
        s = self.current
        if a is None or a.closed or s is None or a.sid != s.sid or self.shown != m.req_id or not a.actionable:
            self.stats["stale_responses"] += 1
            log.warning("stale approval response id=%08x shown=%s", m.req_id, self.shown)
            self._send(P.T_APPROVAL_CLOSE, P.approval_close(m.req_id, P.Close.STALE, "Request is no longer active"))
            return
        if a.turn_id and s.machine.turn_id and a.turn_id != s.machine.turn_id:
            self.stats["stale_responses"] += 1
            self._close_approval(a, P.Close.STALE, "That turn has ended", None)
            return
        if self.clock() > a.deadline:
            self._close_approval(a, P.Close.TIMEOUT, "Timed out: not allowed", None)
            return
        d = P.Decision(m.decision)
        if d == P.Decision.ALLOW:
            self._close_approval(a, P.Close.ALLOWED, "Allowed once", d)
        else:
            self._close_approval(a, P.Close.DENIED, "Denied", d)

    def _fail_all_approvals(self, reason: P.Close, text: str) -> None:
        for a in list(self.approvals.values()):
            self._close_approval(a, reason, text, None)

    # ---- PSP link ------------------------------------------------------------
    def on_psp_link(self, up: bool) -> None:
        if up == self.psp_up:
            return
        log.info("psp link %s", "up" if up else "down")
        if not up:
            self.psp_up = False
            self._fail_all_approvals(P.Close.DISCONNECT, "PSP disconnected")
            self.shown = None
            self.psp_boot = None
            self.sent.clear()
            return
        self.psp_up = True
        self.sent.clear()
        self.shown = None
        self._sync()
        s = self.current
        if s is not None and s.mode != P.Mode.DEMO:
            self._anim(P.Anim.WAKE)

    def on_psp_frame(self, type_: int, payload: bytes) -> None:
        if type_ == 0x07:  # PSP_LINK_T_ERROR
            log.warning("psp reported error: %r", payload[:40])
            self.last_error = f"PSP: {payload[2:].decode('ascii', 'replace')}"
            return
        if not (P.T_CONN <= type_ <= P.T_APPROVAL_RESP):
            return
        try:
            m = P.decode_inbound(type_, payload)
        except P.ProtoError as e:
            self.stats["bad_frames"] += 1
            log.warning("bad frame type=0x%02X: %s", type_, e)
            return
        if isinstance(m, P.Heartbeat):
            if self.psp_boot is not None and m.boot_id != self.psp_boot:
                log.info("psp app restarted")  # its screen is blank again, so resend everything
                self.sent.clear()
                self.shown = None
            self.psp_boot = m.boot_id
            self._sync()
        elif isinstance(m, P.Button):
            self.stats["buttons"] += 1
            log.debug("button %s %s", m.name, "down" if m.down else "up")
        elif isinstance(m, P.ApprovalResp):
            self._on_approval_resp(m)
            self._sync()
        elif isinstance(m, P.ActionMsg):
            self._on_action(m)
            self._sync()

    # ---- quick actions -------------------------------------------------------
    def _ack(self, req: int, status: P.Ack, text: str) -> None:
        self._send(P.T_ACTION_ACK, P.action_ack(req, status, ellipsize(to_ascii(text), P.TEXT_MAX)))

    def _on_action(self, m: P.ActionMsg) -> None:
        if m.action in (P.Action.SESSION_PREV, P.Action.SESSION_NEXT):
            self.switch(-1 if m.action == P.Action.SESSION_PREV else 1)
            return
        table = {i: (en, why) for i, en, why in self._action_table()}
        if m.action not in table:
            self._ack(m.req, P.Ack.UNAVAILABLE, "Unknown action")
            return
        enabled, why = table[m.action]
        if not enabled:
            self._ack(m.req, P.Ack.UNAVAILABLE, why or "Unavailable")
            return
        s = self.current
        action = P.Action(m.action)
        label = ACTION_LABELS[action]
        assert s is not None
        if action == P.Action.INTERRUPT:
            def done(result, error):
                self._ack(m.req, P.Ack.FAILED if error else P.Ack.ACCEPTED, "Interrupt failed" if error else "Interrupt requested")
                if not error:
                    s.action_ack = (m.req, label)

            self.codex.request("turn/interrupt", {"threadId": s.sid, "turnId": s.machine.turn_id}, done)
            return

        def started(result, error):
            s.action_busy = False
            if error:
                self._ack(m.req, P.Ack.FAILED, f"{label} failed to start")
                log.warning("turn/start failed: %s", error)
            else:
                s.action_ack = (m.req, label)
                self._ack(m.req, P.Ack.ACCEPTED, f"{label}: started")
            self._sync()

        s.action_busy = True
        self.codex.request("turn/start", {"threadId": s.sid, "input": [{"type": "text", "text": PROMPTS[action], "text_elements": []}]}, started)

    def send_prompt(self, sid: str | None, text: str, reply) -> None:
        s = self.sessions.get(sid) if sid else self.current
        if s is None or s.mode != P.Mode.MANAGED:
            reply({"ok": False, "error": "prompts can only be sent to a companion-managed session"})
            return
        if s.machine.turn_id is not None or s.action_busy:
            reply({"ok": False, "error": "a turn is already running"})
            return

        def started(result, error):
            s.action_busy = False
            reply({"ok": False, "error": str(error)} if error else {"ok": True, "turn_id": (result.get("turn") or {}).get("id")})
            self._sync()

        s.action_busy = True
        self.codex.request("turn/start", {"threadId": s.sid, "input": [{"type": "text", "text": text, "text_elements": []}]}, started)
        self._sync()

    # ---- event plumbing --------------------------------------------------------
    def emit(self, s: Session, ev: Ev) -> None:
        anim = s.machine.apply(ev, self.clock())
        if s.sid == self.active:
            self._sync()
            self._anim(anim)

    def apply_raw_notification(self, s: Session, method: str, params: dict) -> None:
        """The one path every App-Server-shaped notification takes, real or demo."""
        if method == "item/started" and (params.get("item") or {}).get("type") == "fileChange":
            item = params["item"]
            changes = item.get("changes") or []
            s.file_items[item.get("id")] = [str(c.get("path")) for c in changes if isinstance(c, dict)]
        for ev in from_appserver(method, params):
            self.emit(s, ev)

    # ---- App Server ------------------------------------------------------------
    def on_appserver(self, msg: dict) -> None:
        method = msg.get("method", "")
        params = msg.get("params") or {}
        if "id" in msg:
            self._on_server_request(msg["id"], method, params)
            return
        s = self.sessions.get(params.get("threadId", ""))
        if s is None or s.mode != P.Mode.MANAGED:
            return
        if method == "serverRequest/resolved":
            for a in list(s.approvals):
                if a.rpc_id == params.get("requestId"):
                    self._close_approval(a, P.Close.ELSEWHERE, "Answered in Codex", respond=False)
            self._sync()
            return
        if method == "turn/completed":
            turn = params.get("turn") or {}
            for a in list(s.approvals):
                if a.turn_id == turn.get("id"):
                    self._close_approval(a, P.Close.ELSEWHERE, "Turn ended", respond=False)
            self.apply_raw_notification(s, method, params)
            if s.action_ack is not None:
                req, label = s.action_ack
                s.action_ack = None
                st = turn.get("status")
                if st == "completed" or (label == ACTION_LABELS[P.Action.INTERRUPT] and st == "interrupted"):
                    self._ack(req, P.Ack.DONE, "Interrupted" if st == "interrupted" else f"{label}: done")
                else:
                    self._ack(req, P.Ack.FAILED, f"{label}: {st}")
            self._sync()
            return
        self.apply_raw_notification(s, method, params)

    def _on_server_request(self, rpc_id, method: str, params: dict) -> None:
        if method not in APPROVAL_METHODS:
            # Questions, elicitations and tool calls cannot be answered from a PSP. Fail rather than guess.
            log.info("rejecting unsupported server request %s", method)
            self.codex.respond_error(rpc_id, -32601, f"{method} is not supported by the PSP companion")
            s = self.sessions.get(params.get("threadId", ""))
            if s is not None and method == "item/tool/requestUserInput" and s.sid == self.active:
                self.emit(s, Ev("tool", "Codex asked a question it cannot show here"))
            return
        s = self.sessions.get(params.get("threadId", ""))

        def decide(d: P.Decision | None) -> None:
            if method == "item/permissions/requestApproval":
                req = params.get("permissions") or {}
                granted = {k: v for k, v in req.items() if k in ("network", "fileSystem") and v} if d == P.Decision.ALLOW else {}
                self.codex.respond(rpc_id, {"permissions": granted, "scope": "turn"})
            else:
                self.codex.respond(rpc_id, {"decision": "accept" if d == P.Decision.ALLOW else "decline"})

        if s is None or s.mode != P.Mode.MANAGED or not self.psp_up:
            log.info("declining %s: %s", method, "no PSP link" if s is not None else "unknown thread")
            decide(None)
            return
        kind, title, detail = self._describe(s, method, params)
        self.add_approval(s, kind=kind, title=title, detail=detail, responder=decide, turn_id=params.get("turnId"), rpc_id=rpc_id)

    @staticmethod
    def _describe(s: Session, method: str, params: dict) -> tuple[int, str, str]:
        reason = str(params.get("reason") or "")
        if method == "item/commandExecution/requestApproval":
            net = params.get("networkApprovalContext")
            if isinstance(net, dict) and net.get("host"):
                return P.Kind.PERMISSION, "Allow network access?", f"{net.get('protocol', '')} {net['host']}".strip()
            cmd = params.get("command")
            return P.Kind.COMMAND, "Run command?", summarize_command(cmd, P.DETAIL_MAX) if cmd else (reason or "Command")
        if method == "item/fileChange/requestApproval":
            paths = s.file_items.get(params.get("itemId")) or []
            if paths:
                more = f" (+{len(paths) - 1})" if len(paths) > 1 else ""
                return P.Kind.FILE, "Apply file changes?", f"{shorten_path(paths[0], 90)}{more}"
            return P.Kind.FILE, "Apply file changes?", reason or "File changes"
        return P.Kind.PERMISSION, "Grant permissions?", reason or "Extra permissions for this turn"

    def on_appserver_exit(self) -> None:
        for s in self.sessions.values():
            if s.mode == P.Mode.MANAGED:
                s.conn = P.Conn.RECONNECTING
                s.action_busy = False
                s.action_ack = None
                s.machine.apply(Ev("turn_interrupted"), self.clock())
                s.machine.activity = "Codex app-server stopped"
                for a in list(s.approvals):
                    self._close_approval(a, P.Close.ELSEWHERE, "Codex stopped", respond=False)
        self._sync()

    def start_managed(self, cwd: str, policy: str, sandbox: str, reply, ephemeral: bool = False, model: str | None = None) -> None:
        if policy not in SAFE_POLICIES or sandbox not in SAFE_SANDBOXES:
            reply({"ok": False, "error": f"refusing unsafe settings: approval={policy} sandbox={sandbox}"})
            return
        if self.demo is not None:
            self.demo.stop("a real session was attached")

        def done(result, error):
            if error:
                reply({"ok": False, "error": str(error)})
                return
            tid = result["thread"]["id"]
            s = self._add_session(tid, P.Mode.MANAGED, cwd, "app-server")
            reply({"ok": True, "thread_id": tid, "session": self._session_info(s)})

        params = {"cwd": cwd, "approvalPolicy": policy, "sandbox": sandbox, "serviceName": "psp_companion", "ephemeral": ephemeral}
        if model:
            params["model"] = model
        self.codex.request("thread/start", params, done)

    # ---- hooks -------------------------------------------------------------------
    def on_hook(self, p: dict, reply) -> None:
        s = self.sessions.get(str(p.get("session_id") or ""))
        if s is None or s.mode in (P.Mode.DEMO, P.Mode.MANAGED):
            reply({})  # not ours: leave the session completely alone
            return
        if not s.hooks_seen:
            s.hooks_seen = True
            s.mode = P.Mode.HOOKS
            log.info("hooks active for %s", s.sid)
        if p.get("hook_event_name") == "PermissionRequest":
            self._on_hook_permission(s, p, reply)
            return
        event, turn = p.get("hook_event_name"), p.get("turn_id")
        if event == "Stop":
            for a in list(s.approvals):
                self._close_approval(a, P.Close.ELSEWHERE, "Turn ended", None)
        for ev in from_hook(p):
            self.emit(s, ev)
        if turn and event not in ("Stop", "Interrupt", "SessionEnd") and s.machine.turn_id in (None, "?"):
            s.machine.turn_id = turn  # attached mid-turn: learn which turn is running
        reply({})
        self._sync()

    def _on_hook_permission(self, s: Session, p: dict, reply) -> None:
        if not self.psp_up or s.sid != self.active:
            reply({})  # no decision: Codex shows its normal prompt
            return
        tin = p.get("tool_input") or {}
        tool = str(p.get("tool_name") or "tool")
        if tool == "Bash":
            kind, title, detail = P.Kind.COMMAND, "Run command?", summarize_command(tin.get("command"), P.DETAIL_MAX)
        elif tool == "apply_patch":
            kind, title, detail = P.Kind.FILE, "Apply file changes?", str(tin.get("description") or "File changes")
        else:
            kind, title, detail = P.Kind.OTHER, "Allow tool?", tool

        def decide(d: P.Decision | None) -> None:
            if d is None:
                reply({})
                return
            decision: dict = {"behavior": "allow" if d == P.Decision.ALLOW else "deny"}
            if d == P.Decision.DENY:
                decision["message"] = "Denied on the PSP"
            reply({"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": decision}})

        self.add_approval(s, kind=kind, title=title, detail=detail, responder=decide, turn_id=p.get("turn_id"), timeout=HOOK_APPROVAL_TIMEOUT_S)

    # ---- rollout -----------------------------------------------------------------
    def on_rollout(self, sid: str, rec: dict) -> None:
        s = self.sessions.get(sid)
        if s is None or s.hooks_seen:
            return  # hooks are live and richer; do not let the delayed rollout fight them
        for ev in from_rollout(rec):
            self.emit(s, ev)

    # ---- sessions ------------------------------------------------------------------
    def _add_session(self, sid: str, mode: P.Mode, cwd: str, source: str) -> Session:
        label = ellipsize(to_ascii(os.path.basename(cwd.rstrip("/")) or "session"), P.LABEL_MAX)
        s = Session(sid, mode, cwd, label, source=source)
        self.sessions[sid] = s
        self.order.append(sid)
        self.select(sid, wake=True)
        return s

    def attach_observe(self, sid: str, cwd: str, path: str, running: bool, turn_id: str | None) -> dict:
        if self.demo is not None:
            self.demo.stop("a real session was attached")
        existing = self.sessions.get(sid)
        if existing is not None:
            self.select(sid, wake=False)
            return {"ok": True, "already": True, "session": self._session_info(existing)}
        s = self._add_session(sid, P.Mode.OBSERVE, cwd, "rollout")
        if self.start_tail:
            s.tail = self.start_tail(sid, path)
        if running:
            self.emit(s, Ev("turn_start", turn_id=turn_id))
        return {"ok": True, "already": False, "session": self._session_info(s)}

    def select(self, sid: str, wake: bool = False) -> bool:
        if sid not in self.sessions:
            return False
        self.active = sid
        self._sync()
        if wake:
            self.emit(self.sessions[sid], Ev("wake", "Connected"))
        return True

    def switch(self, step: int) -> None:
        if len(self.order) < 2 or self.active is None:
            return
        i = self.order.index(self.active)
        self.select(self.order[(i + step) % len(self.order)])

    def detach(self, sid: str | None) -> list[str]:
        targets = [sid] if sid else list(self.sessions)
        gone: list[str] = []
        for t in targets:
            s = self.sessions.get(t)
            if s is None:
                continue
            for a in list(s.approvals):
                self._close_approval(a, P.Close.ELSEWHERE, "Session detached", None)
            if s.tail is not None:
                s.tail.stop()
            del self.sessions[t]
            self.order.remove(t)
            if s.mode == P.Mode.MANAGED and self.codex is not None:
                self.codex.request("thread/unsubscribe", {"threadId": t}, lambda r, e: None)
            gone.append(t)
            if self.active == t:
                self.active = self.order[-1] if self.order else None
        self._sync()
        return gone

    # ---- periodic ----------------------------------------------------------------
    def tick(self) -> None:
        now = self.clock()
        for s in list(self.sessions.values()):
            a = s.machine.tick(now)
            if s.sid == self.active:
                self._anim(a)
            for ap in list(s.approvals):
                if now > ap.deadline:
                    self._close_approval(ap, P.Close.TIMEOUT, "Timed out: not allowed", None)
        if self.demo is not None:
            self.demo.tick(now)
        self._sync()

    def shutdown(self) -> None:
        self._fail_all_approvals(P.Close.DISCONNECT, "Companion stopped")
        for s in self.sessions.values():
            if s.tail is not None:
                s.tail.stop()

    # ---- reporting -----------------------------------------------------------------
    def _session_info(self, s: Session) -> dict:
        return {
            "id": s.sid,
            "mode": MODE_NAMES[s.mode],
            "cwd": s.cwd,
            "label": s.label,
            "active": s.sid == self.active,
            "state": s.machine.state.name,
            "activity": s.machine.activity,
            "turn_id": s.machine.turn_id,
            "pending_approvals": len(s.approvals),
            "hooks_active": s.hooks_seen,
            "capabilities": {
                "approvals": bool(self._caps(s) & P.CAP_APPROVALS),
                "actions": bool(self._caps(s) & P.CAP_ACTIONS),
                "live_tools": bool(self._caps(s) & P.CAP_LIVE_TOOLS),
            },
        }

    def status(self) -> dict:
        return {
            "psp": {"linked": self.psp_up, "state": getattr(self.psp, "status_text", "?"), "transport": getattr(self.psp, "spec", "?")},
            "sessions": [self._session_info(self.sessions[i]) for i in self.order],
            "active": self.active,
            "demo": self.demo.info() if self.demo is not None else None,
            "stats": dict(self.stats),
            "last_error": self.last_error,
        }
