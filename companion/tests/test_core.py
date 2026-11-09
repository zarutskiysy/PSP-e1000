"""Session and approval rules, with every external dependency faked and time controlled."""
import pytest

from psp_companion import protocol as P
from psp_companion.core import APPROVAL_TIMEOUT_S, Core
from psp_companion.demo import Demo

SID = "019a0000-0000-7000-8000-000000000001"
SID2 = "019a0000-0000-7000-8000-000000000002"


class Port:
    status_text, spec = "connected", "fake"

    def __init__(self):
        self.sent = []

    def send(self, t, p):
        self.sent.append(P.decode_outbound(t, p))

    def of(self, t):
        return [m.fields for m in self.sent if m.type == t]

    def last(self, t):
        v = self.of(t)
        return v[-1] if v else None


class Codex:
    def __init__(self):
        self.calls, self.responses, self.errors = [], [], []
        self.fail_respond = False

    def request(self, method, params, cb):
        self.calls.append((method, params, cb))

    def respond(self, rid, result):
        if self.fail_respond:
            raise OSError("pipe closed")
        self.responses.append((rid, result))

    def respond_error(self, rid, code, msg):
        self.errors.append((rid, code, msg))

    def answer(self, index=-1, result=None, error=None):
        self.calls[index][2](result if result is not None else {}, error)


class Clock:
    t = 100.0

    def __call__(self):
        return self.t


class Tail:
    stopped = False

    def stop(self):
        self.stopped = True


@pytest.fixture
def env():
    port, codex, clock = Port(), Codex(), Clock()
    core = Core(port, codex, lambda sid, path: Tail(), clock)
    core.on_psp_link(True)
    return core, port, codex, clock


def managed(core, codex, sid=SID, cwd="/repo"):
    box = {}
    core.start_managed(cwd, "on-request", "workspace-write", box.update)
    codex.calls[-1][2]({"thread": {"id": sid}}, None)
    assert box["ok"]
    return core.sessions[sid]


def turn_started(core, sid=SID, turn="T1"):
    core.on_appserver({"method": "turn/started", "params": {"threadId": sid, "turn": {"id": turn}}})


def ask(core, sid=SID, turn="T1", rid=77, cmd="npm test"):
    core.on_appserver({"id": rid, "method": "item/commandExecution/requestApproval",
                       "params": {"threadId": sid, "turnId": turn, "itemId": "i", "startedAtMs": 0, "command": cmd}})


def respond(core, req_id, decision):
    core.on_psp_frame(P.T_APPROVAL_RESP, bytes([P.VERSION]) + req_id.to_bytes(4, "little") + bytes([decision]))


# ---- view ---------------------------------------------------------------------------
def test_link_up_sends_full_view(env):
    core, port, _, _ = env
    assert port.last(P.T_CONN)["conn"] == P.Conn.NONE
    assert port.last(P.T_AGENT)["state"] == P.Agent.SLEEPING
    assert all(not e for _, e, _ in port.last(P.T_ACTIONS)["items"])


def test_only_changes_are_sent(env):
    core, port, _, clock = env
    n = len(port.sent)
    for _ in range(50):
        clock.t += 0.05
        core.tick()
    assert len(port.sent) == n


def test_psp_restart_resends_everything(env):
    core, port, _, _ = env
    core.on_psp_frame(P.T_HEARTBEAT, P.heartbeat(1, 0))
    n = len(port.of(P.T_CONN))
    core.on_psp_frame(P.T_HEARTBEAT, P.heartbeat(1, 1000))
    assert len(port.of(P.T_CONN)) == n
    core.on_psp_frame(P.T_HEARTBEAT, P.heartbeat(2, 10))
    assert len(port.of(P.T_CONN)) == n + 1


def test_bad_frames_are_counted_not_fatal(env):
    core, _, _, _ = env
    core.on_psp_frame(P.T_APPROVAL_RESP, b"\x01\x00")
    core.on_psp_frame(P.T_ACTION, b"\x09\x00\x00\x00")
    core.on_psp_frame(P.T_APPROVAL_RESP, bytes([P.VERSION]) + (5).to_bytes(4, "little") + bytes([9]))
    assert core.stats["bad_frames"] == 3


# ---- sessions --------------------------------------------------------------------------
def test_attach_is_idempotent(env):
    core, port, _, _ = env
    r1 = core.attach_observe(SID, "/repo/a", "/p", False, None)
    r2 = core.attach_observe(SID, "/repo/a", "/p", False, None)
    assert r1["already"] is False and r2["already"] is True
    assert list(core.sessions) == [SID]
    c = port.last(P.T_CONN)
    assert (c["conn"], c["mode"], c["count"], c["label"]) == (P.Conn.ATTACHED, P.Mode.OBSERVE, 1, "a")


def test_attach_mid_turn_shows_it(env):
    core, port, _, _ = env
    core.attach_observe(SID, "/repo", "/p", True, "T9")
    assert port.last(P.T_AGENT)["state"] == P.Agent.THINKING
    assert core.current.machine.turn_id == "T9"


def test_switching_sessions(env):
    core, port, _, _ = env
    core.attach_observe(SID, "/repo/a", "/p", False, None)
    core.attach_observe(SID2, "/repo/b", "/p2", False, None)
    assert core.active == SID2
    core.on_psp_frame(P.T_ACTION, bytes([P.VERSION, 1, 0, P.Action.SESSION_NEXT]))
    assert core.active == SID and port.last(P.T_CONN)["label"] == "a"
    core.on_psp_frame(P.T_ACTION, bytes([P.VERSION, 2, 0, P.Action.SESSION_PREV]))
    assert core.active == SID2


def test_events_from_another_session_do_not_reach_the_screen(env):
    core, port, _, _ = env
    core.attach_observe(SID, "/a", "/p", False, None)
    core.attach_observe(SID2, "/b", "/p2", False, None)
    core.on_rollout(SID, {"type": "event_msg", "payload": {"type": "task_started", "turn_id": "x"}})
    assert port.last(P.T_AGENT)["state"] == P.Agent.IDLE
    assert core.sessions[SID].machine.state == P.Agent.THINKING


def test_detach(env):
    core, port, _, _ = env
    core.attach_observe(SID, "/a", "/p", False, None)
    tail = core.sessions[SID].tail
    assert core.detach(SID) == [SID]
    assert tail.stopped and core.current is None
    assert port.last(P.T_CONN)["conn"] == P.Conn.NONE
    assert core.detach(SID) == []


# ---- approvals over App Server -----------------------------------------------------------
def test_allow_sends_one_decision_for_one_use(env):
    core, port, codex, _ = env
    managed(core, codex)
    turn_started(core)
    ask(core)
    req = port.last(P.T_APPROVAL_REQ)
    assert (req["title"], req["detail"]) == ("Run command?", "npm test") and req["flags"] & P.AF_ACTIONABLE
    assert port.last(P.T_AGENT)["state"] == P.Agent.APPROVAL
    respond(core, req["id"], P.Decision.ALLOW)
    assert codex.responses == [(77, {"decision": "accept"})]
    assert port.last(P.T_APPROVAL_CLOSE)["reason"] == P.Close.ALLOWED
    # pressing again changes nothing
    respond(core, req["id"], P.Decision.ALLOW)
    assert len(codex.responses) == 1 and port.last(P.T_APPROVAL_CLOSE)["reason"] == P.Close.STALE


def test_deny(env):
    core, port, codex, _ = env
    managed(core, codex)
    turn_started(core)
    ask(core)
    respond(core, port.last(P.T_APPROVAL_REQ)["id"], P.Decision.DENY)
    assert codex.responses == [(77, {"decision": "decline"})]
    assert port.last(P.T_APPROVAL_CLOSE)["reason"] == P.Close.DENIED


def test_wrong_id_decides_nothing(env):
    core, port, codex, _ = env
    managed(core, codex)
    turn_started(core)
    ask(core)
    real = port.last(P.T_APPROVAL_REQ)["id"]
    respond(core, (real + 1) & 0xFFFFFFFF or 1, P.Decision.ALLOW)
    assert codex.responses == [] and core.stats["stale_responses"] == 1
    assert core.current.approvals  # the real one is still waiting


def test_timeout_never_allows(env):
    core, port, codex, clock = env
    managed(core, codex)
    turn_started(core)
    ask(core)
    clock.t += APPROVAL_TIMEOUT_S + 1
    core.tick()
    assert codex.responses == [(77, {"decision": "decline"})]
    assert port.last(P.T_APPROVAL_CLOSE)["reason"] == P.Close.TIMEOUT


def test_late_response_after_deadline_is_refused(env):
    core, port, codex, clock = env
    managed(core, codex)
    turn_started(core)
    ask(core)
    req = port.last(P.T_APPROVAL_REQ)["id"]
    clock.t += APPROVAL_TIMEOUT_S + 1  # the press arrives before the next tick
    respond(core, req, P.Decision.ALLOW)
    assert codex.responses == [(77, {"decision": "decline"})]


def test_disconnect_never_allows(env):
    core, port, codex, _ = env
    managed(core, codex)
    turn_started(core)
    ask(core)
    core.on_psp_link(False)
    assert codex.responses == [(77, {"decision": "decline"})]


def test_request_with_no_psp_is_declined_at_once(env):
    core, port, codex, _ = env
    managed(core, codex)
    turn_started(core)
    core.on_psp_link(False)
    ask(core)
    assert codex.responses == [(77, {"decision": "decline"})]


def test_stale_turn_is_refused(env):
    core, port, codex, _ = env
    managed(core, codex)
    turn_started(core, turn="T1")
    ask(core, turn="T1")
    req = port.last(P.T_APPROVAL_REQ)["id"]
    turn_started(core, turn="T2")  # a new turn began while the overlay was up
    respond(core, req, P.Decision.ALLOW)
    assert codex.responses == [(77, {"decision": "decline"})]
    assert port.last(P.T_APPROVAL_CLOSE)["reason"] == P.Close.STALE


def test_resolved_elsewhere_closes_without_a_second_answer(env):
    core, port, codex, _ = env
    managed(core, codex)
    turn_started(core)
    ask(core)
    req = port.last(P.T_APPROVAL_REQ)["id"]
    core.on_appserver({"method": "serverRequest/resolved", "params": {"threadId": SID, "requestId": 77}})
    assert codex.responses == [] and port.last(P.T_APPROVAL_CLOSE)["reason"] == P.Close.ELSEWHERE
    respond(core, req, P.Decision.ALLOW)
    assert codex.responses == []


def test_turn_end_clears_its_approvals(env):
    core, port, codex, _ = env
    managed(core, codex)
    turn_started(core)
    ask(core)
    core.on_appserver({"method": "turn/completed", "params": {"threadId": SID, "turn": {"id": "T1", "status": "interrupted"}}})
    assert not core.current.approvals and codex.responses == []


def test_undeliverable_decision_is_reported(env):
    core, port, codex, _ = env
    managed(core, codex)
    turn_started(core)
    ask(core)
    codex.fail_respond = True
    respond(core, port.last(P.T_APPROVAL_REQ)["id"], P.Decision.ALLOW)
    assert port.last(P.T_APPROVAL_CLOSE)["reason"] == P.Close.FAILED


def test_queue_shows_one_at_a_time(env):
    core, port, codex, _ = env
    managed(core, codex)
    turn_started(core)
    ask(core, rid=1, cmd="a")
    ask(core, rid=2, cmd="b")
    assert len(port.of(P.T_APPROVAL_REQ)) == 1
    respond(core, port.last(P.T_APPROVAL_REQ)["id"], P.Decision.DENY)
    assert port.last(P.T_APPROVAL_REQ)["detail"] == "b"
    assert port.last(P.T_AGENT)["state"] == P.Agent.APPROVAL


def test_hidden_session_cannot_be_answered(env):
    core, port, codex, _ = env
    managed(core, codex, SID)
    turn_started(core, SID)
    ask(core, SID, rid=1)
    req = port.last(P.T_APPROVAL_REQ)["id"]
    core.attach_observe(SID2, "/other", "/p", False, None)  # takes over the screen
    assert port.last(P.T_APPROVAL_CLOSE) == {"id": req, "reason": P.Close.HIDDEN, "text": ""}
    respond(core, req, P.Decision.ALLOW)
    assert codex.responses == []
    # going back presents it again, and now it can be answered
    core.select(SID)
    assert port.last(P.T_APPROVAL_REQ)["id"] == req
    respond(core, req, P.Decision.ALLOW)
    assert codex.responses == [(1, {"decision": "accept"})]


def test_file_change_approval_names_the_file(env):
    core, port, codex, _ = env
    managed(core, codex)
    turn_started(core)
    core.on_appserver({"method": "item/started", "params": {"threadId": SID, "turnId": "T1", "item": {"type": "fileChange", "id": "f", "changes": [{"path": "a/b.py", "kind": "update", "diff": ""}]}}})
    core.on_appserver({"id": 5, "method": "item/fileChange/requestApproval", "params": {"threadId": SID, "turnId": "T1", "itemId": "f", "startedAtMs": 0}})
    r = port.last(P.T_APPROVAL_REQ)
    assert (r["kind"], r["detail"]) == (P.Kind.FILE, "a/b.py")


def test_permissions_are_turn_scoped(env):
    core, port, codex, _ = env
    managed(core, codex)
    turn_started(core)
    params = {"threadId": SID, "turnId": "T1", "itemId": "p", "startedAtMs": 0, "cwd": "/", "permissions": {"network": {"enabled": True}}}
    core.on_appserver({"id": 6, "method": "item/permissions/requestApproval", "params": params})
    respond(core, port.last(P.T_APPROVAL_REQ)["id"], P.Decision.ALLOW)
    assert codex.responses[-1] == (6, {"permissions": {"network": {"enabled": True}}, "scope": "turn"})
    core.on_appserver({"id": 7, "method": "item/permissions/requestApproval", "params": params})
    respond(core, port.last(P.T_APPROVAL_REQ)["id"], P.Decision.DENY)
    assert codex.responses[-1] == (7, {"permissions": {}, "scope": "turn"})


def test_unsupported_requests_fail_rather_than_guess(env):
    core, port, codex, _ = env
    managed(core, codex)
    for i, m in enumerate(("item/tool/requestUserInput", "mcpServer/elicitation/request", "item/tool/call", "execCommandApproval")):
        core.on_appserver({"id": i, "method": m, "params": {"threadId": SID}})
    assert [e[0] for e in codex.errors] == [0, 1, 2, 3] and codex.responses == []


def test_unknown_thread_is_declined(env):
    core, port, codex, _ = env
    ask(core, sid="other")
    assert codex.responses == [(77, {"decision": "decline"})]


def test_refuses_unsafe_managed_settings(env):
    core, _, codex, _ = env
    for policy, sandbox in (("never", "workspace-write"), ("on-request", "danger-full-access")):
        box = {}
        core.start_managed("/x", policy, sandbox, box.update)
        assert box["ok"] is False
    assert codex.calls == []


# ---- approvals through hooks ----------------------------------------------------------------
def perm(core, sid=SID, turn="T1", cmd="rm -rf build"):
    out = []
    core.on_hook({"hook_event_name": "PermissionRequest", "session_id": sid, "turn_id": turn, "tool_name": "Bash", "tool_input": {"command": cmd}}, out.append)
    return out


def allow_output():
    return {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {"behavior": "allow"}}}


def test_hook_ignores_unattached_sessions(env):
    core, port, _, _ = env
    n = len(port.sent)
    assert perm(core, sid="not-attached") == [{}]
    assert len(port.sent) == n


def test_hook_upgrades_session_and_gets_a_real_decision(env):
    core, port, _, _ = env
    core.attach_observe(SID, "/a", "/p", False, None)
    core.on_hook({"hook_event_name": "UserPromptSubmit", "session_id": SID, "turn_id": "T1", "prompt": "x"}, lambda r: None)
    assert port.last(P.T_CONN)["mode"] == P.Mode.HOOKS
    out = perm(core)
    assert out == []  # the hook blocks until a person answers
    respond(core, port.last(P.T_APPROVAL_REQ)["id"], P.Decision.ALLOW)
    assert out == [allow_output()]


def test_hook_deny_explains_itself(env):
    core, port, _, _ = env
    core.attach_observe(SID, "/a", "/p", False, None)
    out = perm(core)
    respond(core, port.last(P.T_APPROVAL_REQ)["id"], P.Decision.DENY)
    assert out[0]["hookSpecificOutput"]["decision"]["behavior"] == "deny"


@pytest.mark.parametrize("trigger", ["disconnect", "timeout", "stop"])
def test_hook_never_allows_on_failure(env, trigger):
    core, port, _, clock = env
    core.attach_observe(SID, "/a", "/p", False, None)
    out = perm(core)
    if trigger == "disconnect":
        core.on_psp_link(False)
    elif trigger == "timeout":
        clock.t += 500
        core.tick()
    else:
        core.on_hook({"hook_event_name": "Stop", "session_id": SID, "turn_id": "T1"}, lambda r: None)
    assert out == [{}]  # no decision: Codex falls back to its own prompt


def test_hook_with_no_psp_or_hidden_session_does_not_wait(env):
    core, port, _, _ = env
    core.attach_observe(SID, "/a", "/p", False, None)
    core.attach_observe(SID2, "/b", "/p2", False, None)
    assert perm(core, sid=SID) == [{}]  # SID2 is on screen
    core.on_psp_link(False)
    assert perm(core, sid=SID2) == [{}]


def test_rollout_is_ignored_once_hooks_are_live(env):
    core, port, _, _ = env
    core.attach_observe(SID, "/a", "/p", False, None)
    core.on_hook({"hook_event_name": "PreToolUse", "session_id": SID, "turn_id": "T1", "tool_name": "Bash", "tool_input": {"command": "ls"}}, lambda r: None)
    core.on_rollout(SID, {"type": "event_msg", "payload": {"type": "task_complete", "turn_id": "T1"}})
    assert port.last(P.T_AGENT)["state"] == P.Agent.RUNNING


# ---- quick actions -----------------------------------------------------------------------------
def action(core, a, req=1):
    core.on_psp_frame(P.T_ACTION, bytes([P.VERSION]) + req.to_bytes(2, "little") + bytes([a]))


def test_observe_mode_reports_unavailable(env):
    core, port, codex, _ = env
    core.attach_observe(SID, "/a", "/p", False, None)
    assert all(not e and r for _, e, r in port.last(P.T_ACTIONS)["items"])
    action(core, P.Action.TESTS)
    assert port.last(P.T_ACTION_ACK)["status"] == P.Ack.UNAVAILABLE and codex.calls == []


def test_action_is_not_done_until_codex_says_so(env):
    core, port, codex, _ = env
    managed(core, codex)
    action(core, P.Action.TESTS, 9)
    method, params, _ = codex.calls[-1]
    assert method == "turn/start" and params["threadId"] == SID and "test suite" in params["input"][0]["text"]
    assert port.of(P.T_ACTION_ACK) == []  # delivered over USB is not started
    codex.answer(result={"turn": {"id": "T5"}})
    assert port.last(P.T_ACTION_ACK)["status"] == P.Ack.ACCEPTED
    turn_started(core, turn="T5")
    core.on_appserver({"method": "turn/completed", "params": {"threadId": SID, "turn": {"id": "T5", "status": "failed"}}})
    last = port.last(P.T_ACTION_ACK)
    assert last["status"] == P.Ack.FAILED and last["req"] == 9


def test_action_start_failure_is_reported(env):
    core, port, codex, _ = env
    managed(core, codex)
    action(core, P.Action.CONTINUE)
    codex.answer(error={"message": "nope"})
    assert port.last(P.T_ACTION_ACK)["status"] == P.Ack.FAILED
    assert not core.current.action_busy


def test_busy_and_interrupt_availability(env):
    core, port, codex, _ = env
    managed(core, codex)
    table = lambda: {i: e for i, e, _ in port.last(P.T_ACTIONS)["items"]}
    assert table()[P.Action.INTERRUPT] is False and table()[P.Action.CONTINUE] is True
    turn_started(core, turn="T7")
    assert table()[P.Action.INTERRUPT] is True and table()[P.Action.CONTINUE] is False
    n = len(codex.calls)
    action(core, P.Action.CONTINUE)
    assert len(codex.calls) == n and port.last(P.T_ACTION_ACK)["status"] == P.Ack.UNAVAILABLE
    action(core, P.Action.INTERRUPT, 3)
    assert codex.calls[-1][0] == "turn/interrupt" and codex.calls[-1][1] == {"threadId": SID, "turnId": "T7"}
    codex.answer()
    core.on_appserver({"method": "turn/completed", "params": {"threadId": SID, "turn": {"id": "T7", "status": "interrupted"}}})
    assert port.last(P.T_ACTION_ACK)["status"] == P.Ack.DONE


def test_double_press_starts_one_turn(env):
    core, port, codex, _ = env
    managed(core, codex)
    action(core, P.Action.SUMMARIZE, 1)
    action(core, P.Action.SUMMARIZE, 2)
    assert len([c for c in codex.calls if c[0] == "turn/start"]) == 1


def test_appserver_exit_marks_sessions(env):
    core, port, codex, _ = env
    managed(core, codex)
    turn_started(core)
    ask(core)
    core.on_appserver_exit()
    assert port.last(P.T_CONN)["conn"] == P.Conn.RECONNECTING
    assert not core.current.approvals
    assert all(not e for _, e, _ in port.last(P.T_ACTIONS)["items"])


# ---- demo isolation ----------------------------------------------------------------------------
def run_demo(core, port, clock, decision):
    d = Demo(core, speed=1.0, approval_timeout=30)
    core.demo = d
    d.start()
    seen, answered = [], False
    for _ in range(4000):
        clock.t += 0.05
        core.tick()
        if d.phase not in seen:
            seen.append(d.phase)
        if not answered and d.approval is not None:
            req = port.last(P.T_APPROVAL_REQ)
            if req is not None:
                assert req["flags"] & P.AF_DEMO
                if decision is not None:
                    clock.t += 1
                    respond(core, req["id"], decision)
                answered = True
        if d.finished:
            break
    assert d.finished and d.outcome == "completed"
    return seen


@pytest.mark.parametrize("decision", [P.Decision.ALLOW, P.Decision.DENY, None])
def test_demo_runs_all_steps_and_never_touches_codex(env, decision):
    core, port, codex, clock = env
    seen = run_demo(core, port, clock, decision)
    assert len(seen) == 14
    assert codex.calls == [] and codex.responses == [] and codex.errors == []
    assert core.sessions == {}
    states = [m["state"] for m in port.of(P.T_AGENT)]
    for s in (P.Agent.SLEEPING, P.Agent.IDLE, P.Agent.THINKING, P.Agent.EDITING, P.Agent.TESTING, P.Agent.APPROVAL, P.Agent.SUCCESS):
        assert s in states
    if decision == P.Decision.ALLOW:
        assert P.Agent.FAILED in states


def test_demo_marks_conn_and_wakes(env):
    core, port, _, clock = env
    run_demo(core, port, clock, P.Decision.ALLOW)
    assert [c["mode"] for c in port.of(P.T_CONN)][1] == P.Mode.DEMO
    assert P.Anim.WAKE in [a["anim"] for a in port.of(P.T_ANIM)]


def test_real_attach_ends_demo_and_its_approval(env):
    core, port, codex, clock = env
    d = Demo(core, speed=100.0)
    core.demo = d
    d.start()
    for _ in range(400):
        clock.t += 0.05
        core.tick()
        if d.approval is not None:
            break
    assert d.approval is not None and core.approvals
    core.attach_observe(SID, "/a", "/p", False, None)
    assert core.demo is None and d.finished and not core.approvals
    assert list(core.sessions) == [SID] and codex.responses == []
