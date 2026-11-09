"""Deterministic demo for filming. No Codex involved: it feeds App-Server-shaped events into the same
pipeline a real session uses, so the mapping, state machine, protocol and PSP renderer are all real.

Isolation from real work: the demo owns a session of mode DEMO, its approvals resolve into this object
only, and it never touches the Codex port. It refuses to start while a real session is attached, and
attaching one ends it.
"""
from __future__ import annotations

import logging

from . import protocol as P
from .core import Core, Session
from .events import Ev

log = logging.getLogger("psp_companion.demo")

DEMO_SID = "demo"
TURN = "demo-turn"
FILE = "src/auth/login.py"
TEST_CMD = "pytest tests/test_login.py"


class Demo:
    def __init__(self, core: Core, speed: float = 1.0, approval_timeout: float = 45.0):
        self.core = core
        self.speed = speed
        self.approval_timeout = approval_timeout
        self.hide_conn = True
        self.phase = "starting"
        self.finished = False
        self.outcome = ""
        self.decision: P.Decision | None = None
        self.answered = False
        self.approval = None
        self.wake_at = 0.0
        self.sess: Session | None = None
        self._gen = None

    # ---- lifecycle -----------------------------------------------------------
    def start(self) -> None:
        core = self.core
        s = Session(DEMO_SID, P.Mode.DEMO, "/demo-project", "demo-project", source="demo")
        core.sessions[DEMO_SID] = s
        core.order.append(DEMO_SID)
        core.active = DEMO_SID
        self.sess = s
        self._gen = self._script()
        self.wake_at = core.clock()

    def stop(self, why: str) -> None:
        if self.finished:
            return
        self._finish(f"stopped: {why}")

    def _finish(self, outcome: str) -> None:
        core = self.core
        self.finished = True
        self.outcome = outcome
        core.detach(DEMO_SID)
        core.demo = None
        core.last_demo = self.info()
        log.info("demo finished: %s", outcome)

    def info(self) -> dict:
        return {"phase": self.phase, "finished": self.finished, "outcome": self.outcome,
                "decision": self.decision.name if self.decision else None}

    def tick(self, now: float) -> None:
        if self.finished or now < self.wake_at:
            return
        try:
            delay = next(self._gen)
        except StopIteration:
            self._finish("completed")
            return
        self.wake_at = now + delay / self.speed

    # ---- steps ----------------------------------------------------------------
    def _note(self, phase: str) -> None:
        self.phase = phase
        log.info("demo: %s", phase)

    def _raw(self, method: str, params: dict) -> None:
        self.core.apply_raw_notification(self.sess, method, params)

    def _item(self, method: str, item: dict) -> None:
        self._raw(method, {"threadId": DEMO_SID, "turnId": TURN, "item": item})

    def _on_decision(self, d: P.Decision | None) -> None:
        self.answered = True
        self.decision = d

    def _script(self):
        s = self.sess
        core = self.core
        self._note("1 sleeping")
        core.emit(s, Ev("sleep", "Zzz..."))
        yield 3.0

        self._note("2 connection established")
        self.hide_conn = False
        s.machine.activity = "PSP connected"
        core._sync()
        yield 1.2

        self._note("3 waking up")
        core.emit(s, Ev("wake", "Hello!"))
        yield 2.4

        self._note("4 user submits a task")
        self._raw("turn/started", {"threadId": DEMO_SID, "turn": {"id": TURN, "status": "inProgress"}})
        self._item("item/started", {"type": "userMessage", "id": "m1", "content": [{"type": "text", "text": "Fix the failing login test"}]})
        yield 2.4

        self._note("5 thinking")
        self._item("item/started", {"type": "reasoning", "id": "r1"})
        yield 3.0

        self._note("6 editing a file")
        self._item("item/started", {"type": "fileChange", "id": "f1", "status": "inProgress", "changes": [{"path": FILE, "kind": "update", "diff": ""}]})
        yield 3.2
        self._item("item/completed", {"type": "fileChange", "id": "f1", "status": "completed", "changes": []})
        yield .5

        self._note("7 running tests")
        self._item("item/started", {"type": "commandExecution", "id": "c1", "command": TEST_CMD, "commandActions": [], "status": "inProgress"})
        yield 2.0

        self._note("8 permission request (press X or O on the PSP)")
        self.approval = core.add_approval(s, kind=P.Kind.COMMAND, title="Run command?", detail=TEST_CMD,
                                          responder=self._on_decision, turn_id=None, timeout=self.approval_timeout, demo=True)
        while not self.answered:
            yield .05

        self._note(f"9-10 pet reacts: {self.decision.name if self.decision else 'no answer (treated as deny)'}")
        yield 1.8
        if self.decision == P.Decision.ALLOW:
            self._note("11 tests fail")
            self._item("item/completed", {"type": "commandExecution", "id": "c1", "command": TEST_CMD, "exitCode": 1, "status": "failed"})
        else:
            self._note("11 command denied, agent works around it")
            self._item("item/completed", {"type": "commandExecution", "id": "c1", "command": TEST_CMD, "status": "declined"})
        yield 2.8

        self._note("12 fixing the issue")
        self._item("item/started", {"type": "fileChange", "id": "f2", "status": "inProgress", "changes": [{"path": FILE, "kind": "update", "diff": ""}]})
        yield 3.0
        self._item("item/completed", {"type": "fileChange", "id": "f2", "status": "completed", "changes": []})
        yield .4

        self._note("13 tests pass")
        self._item("item/started", {"type": "commandExecution", "id": "c2", "command": TEST_CMD, "commandActions": [], "status": "inProgress"})
        yield 2.6
        self._item("item/completed", {"type": "commandExecution", "id": "c2", "command": TEST_CMD, "exitCode": 0, "status": "completed"})
        yield 2.2

        self._note("14 celebrating")
        self._raw("turn/completed", {"threadId": DEMO_SID, "turn": {"id": TURN, "status": "completed"}})
        yield 5.0

        self._note("15 back to idle")
        yield 3.0
