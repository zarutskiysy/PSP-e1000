"""Event mapping and the state machine, using payloads shaped like the real sources."""
from psp_companion import protocol as P
from psp_companion.events import AgentMachine, Ev, from_appserver, from_hook, from_rollout
from psp_companion.text import ellipsize, is_test_command, shorten_path, summarize_command, to_ascii


def one(evs):
    assert len(evs) == 1, evs
    return evs[0]


# ---- text ------------------------------------------------------------------------
def test_ascii_and_cyrillic():
    assert to_ascii("Редактирую файл") == "Redaktiruyu fayl"
    assert to_ascii("a\nb\t c") == "a b c"
    assert all(" " <= c <= "~" for c in to_ascii("emoji 🎉 — ok"))


def test_truncation():
    assert ellipsize("x" * 100, 10) == "x" * 7 + "..."
    p = shorten_path("/very/long/" + "dir/" * 30 + "main.py", 30)
    assert p.endswith("main.py") and len(p) <= 34 and p.startswith(".../")
    assert len(shorten_path("/a/" + "b" * 200, 40)) <= 40


def test_command_summaries():
    assert summarize_command("/bin/zsh -lc 'git status --short'") == "git status --short"
    assert summarize_command(["bash", "-lc", "cd sub/dir && npm test"]) == "npm test"
    assert len(summarize_command("x" * 300, 60)) == 60


def test_test_command_detection():
    for c in ("pytest -q", "/bin/zsh -lc 'cd a && npm test'", "cargo test --all", "make check", "python -m unittest", "npm run test"):
        assert is_test_command(c), c
    for c in ("git status", "cat pytest.ini", "npm install", "echo testing", "ls tests"):
        assert not is_test_command(c), c


# ---- App Server ------------------------------------------------------------------
def test_appserver_items():
    start = lambda item: one(from_appserver("item/started", {"item": item}))
    assert start({"type": "reasoning"}).kind == "thinking"
    e = start({"type": "commandExecution", "command": "/bin/zsh -lc 'pytest -q'", "commandActions": []})
    assert (e.kind, e.text, e.is_test) == ("running", "Running tests", True)
    e = start({"type": "commandExecution", "command": "git log", "commandActions": [{"type": "unknown", "command": "git log"}]})
    assert e.text == "Running: git log"
    e = start({"type": "commandExecution", "command": "cat a.py", "commandActions": [{"type": "read", "name": "a.py", "path": "/x/a.py", "command": "cat a.py"}]})
    assert e.text == "Reading a.py"
    e = start({"type": "fileChange", "changes": [{"path": "src/main.py", "kind": "update", "diff": ""}, {"path": "b", "kind": "add", "diff": ""}]})
    assert (e.kind, e.text) == ("editing", "Editing src/main.py (+1)")
    assert start({"type": "mcpToolCall", "server": "gh", "tool": "list"}).text == "Using gh: list"
    assert start({"type": "agentMessage"}).kind == "reply"


def test_appserver_command_results():
    done = lambda **kw: one(from_appserver("item/completed", {"item": {"type": "commandExecution", "command": kw.pop("command", "ls"), **kw}}))
    assert done(exitCode=0).ok is True
    e = done(exitCode=2)
    assert (e.ok, e.text) == (False, "Command failed")
    e = done(command="pytest", exitCode=1)
    assert (e.ok, e.text, e.is_test) == (False, "Tests failed", True)
    e = done(command="pytest", exitCode=0)
    assert (e.ok, e.text) == (True, "Tests passed")
    assert done(status="declined").text == "Command declined"


def test_appserver_turns():
    e = one(from_appserver("turn/started", {"turn": {"id": "t1"}}))
    assert (e.kind, e.turn_id) == ("turn_start", "t1")
    assert one(from_appserver("turn/completed", {"turn": {"id": "t1", "status": "completed"}})).kind == "turn_done"
    assert one(from_appserver("turn/completed", {"turn": {"id": "t1", "status": "interrupted"}})).kind == "turn_interrupted"
    e = one(from_appserver("turn/completed", {"turn": {"id": "t1", "status": "failed", "error": {"message": "out of quota"}}}))
    assert (e.kind, e.text) == ("turn_failed", "out of quota")
    assert one(from_appserver("error", {"error": {"message": "x"}, "willRetry": True})).kind == "retrying"
    assert one(from_appserver("error", {"error": {"message": "boom"}, "willRetry": False})).text == "boom"
    assert from_appserver("thread/tokenUsage/updated", {}) == []


# ---- hooks -----------------------------------------------------------------------
def hook(name, **kw):
    return from_hook({"hook_event_name": name, "session_id": "s", "turn_id": "t", **kw})


def test_hooks():
    assert one(hook("UserPromptSubmit", prompt="hi")).kind == "turn_start"
    e = one(hook("PreToolUse", tool_name="Bash", tool_input={"command": "pytest"}))
    assert e.text == "Running tests"
    e = one(hook("PreToolUse", tool_name="apply_patch", tool_input={"command": "*** Begin Patch\n*** Update File: a/b.py\n@@\n*** End Patch"}))
    assert e.text == "Editing a/b.py"
    assert one(hook("PreToolUse", tool_name="mcp__fs__read", tool_input={})).text == "Using fs: read"
    e = one(hook("PostToolUse", tool_name="Bash", tool_input={"command": "ls"}, tool_response="Exit code: 1\nnope"))
    assert (e.kind, e.ok) == ("command_done", False)
    e = one(hook("PostToolUse", tool_name="Bash", tool_input={"command": "ls"}, tool_response="fine"))
    assert e.ok is None  # no exit status in the output: do not claim success or failure
    assert one(hook("Stop", last_assistant_message="ok")).kind == "turn_done"
    assert one(hook("Interrupt")).kind == "turn_interrupted"
    assert hook("SessionStart", source="startup") == []


# ---- rollout (shapes taken from real session files) --------------------------------
def rollout(payload, t="event_msg"):
    return from_rollout({"type": t, "payload": payload})


def test_rollout():
    assert one(rollout({"type": "task_started", "turn_id": "t"})).kind == "turn_start"
    assert one(rollout({"type": "task_complete", "turn_id": "t"})).kind == "turn_done"
    assert one(rollout({"type": "turn_aborted", "turn_id": "t"})).kind == "turn_interrupted"
    assert one(rollout({"type": "item_completed", "item": {"type": "Reasoning"}})).kind == "thinking"
    evs = rollout({"type": "item_completed", "item": {"type": "CommandExecution", "command": "git status", "exit_code": 0}})
    assert one(evs).text == "Ran: git status"
    evs = rollout({"type": "item_completed", "item": {"type": "CommandExecution", "command": "false", "exit_code": 1}})
    assert [e.kind for e in evs] == ["tool", "command_done"] and evs[1].ok is False
    assert one(rollout({"type": "item_completed", "item": {"type": "FileChange", "changes": {"a.py": {}}}})).text == "Edited a.py"
    assert rollout({"type": "item_completed", "item": {"type": "AgentMessage", "phase": "final_answer"}}) == []
    assert one(rollout({"type": "custom_tool_call", "name": "exec"}, "response_item")).text == "Working..."
    assert rollout({"type": "token_count"}) == []
    assert from_rollout({"type": "event_msg", "payload": "junk"}) == []


# ---- state machine ------------------------------------------------------------------
def test_machine_normal_turn():
    m = AgentMachine()
    assert m.apply(Ev("turn_start", turn_id="t"), 0) == P.Anim.BOUNCE
    assert m.state == P.Agent.THINKING and m.turn_id == "t"
    m.apply(Ev("editing", "Editing a.py"), 1)
    assert (m.state, m.activity) == (P.Agent.EDITING, "Editing a.py")
    m.apply(Ev("running", "Running tests", is_test=True), 2)
    assert m.state == P.Agent.TESTING
    assert m.apply(Ev("turn_done", turn_id="t"), 3) == P.Anim.CELEBRATE
    assert (m.state, m.activity, m.turn_id) == (P.Agent.SUCCESS, "Task complete", None)
    m.tick(3 + 3.9)
    assert m.state == P.Agent.SUCCESS
    m.tick(3 + 4.1)
    assert (m.state, m.activity) == (P.Agent.IDLE, "Idle")


def test_machine_failure_flash_is_not_overwritten():
    m = AgentMachine()
    m.apply(Ev("turn_start", turn_id="t"), 0)
    assert m.apply(Ev("command_done", "Tests failed", ok=False, is_test=True), 1) == P.Anim.FAIL
    assert (m.state, m.activity) == (P.Agent.FAILED, "Tests failed")
    m.apply(Ev("editing", "Editing a.py"), 1.1)  # arrives during the dwell
    assert m.state == P.Agent.FAILED
    m.tick(1 + 1.5)
    assert (m.state, m.activity) == (P.Agent.EDITING, "Editing a.py")


def test_machine_terminal_events_cut_the_dwell():
    m = AgentMachine()
    m.apply(Ev("turn_start", turn_id="t"), 0)
    m.apply(Ev("command_done", "Command failed", ok=False), 1)
    m.apply(Ev("turn_done", turn_id="t"), 1.1)
    assert m.state == P.Agent.SUCCESS


def test_machine_approval_holds_state():
    m = AgentMachine()
    m.apply(Ev("turn_start", turn_id="t"), 0)
    m.set_approval(True)
    assert (m.state, m.activity) == (P.Agent.APPROVAL, "Waiting for approval")
    m.apply(Ev("thinking"), 1)
    assert m.state == P.Agent.APPROVAL
    m.set_approval(False)
    assert m.state == P.Agent.THINKING


def test_machine_returns_to_the_command_after_approval():
    m = AgentMachine()
    m.apply(Ev("turn_start", turn_id="t"), 0)
    m.apply(Ev("running", "Running tests", is_test=True), 1)
    m.set_approval(True)
    m.set_approval(False)
    assert (m.state, m.activity) == (P.Agent.TESTING, "Running tests")


def test_machine_failed_turn_returns_to_idle():
    m = AgentMachine()
    m.apply(Ev("turn_start", turn_id="t"), 0)
    assert m.apply(Ev("turn_failed", "quota"), 1) == P.Anim.FAIL
    assert (m.state, m.activity) == (P.Agent.FAILED, "quota")
    m.tick(7)
    assert m.state == P.Agent.IDLE
