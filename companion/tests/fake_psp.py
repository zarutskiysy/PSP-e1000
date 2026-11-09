"""A stand-in PSP for tests: listens on TCP like the emulator bridge and speaks the companion protocol."""
from __future__ import annotations

import pathlib
import sys
import threading
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "companion/mac"), str(ROOT / "common/python")]

from pspmac import protocol as L  # noqa: E402
from pspmac.link import Link  # noqa: E402
from pspmac.transport import TcpServerTransport  # noqa: E402

from psp_companion import protocol as P  # noqa: E402


class FakePsp:
    """Accepts one daemon at a time. `reconnect=True` keeps accepting after a drop."""

    def __init__(self, port: int = 0, app: int = P.APP_ID, reconnect: bool = True, heartbeat: bool = True):
        self.server = TcpServerTransport("127.0.0.1", port)
        self.port = self.server.port
        self.app = app
        self.reconnect = reconnect
        self.heartbeat = heartbeat
        self.boot_id = 0x1234
        self.link: Link | None = None
        self.received: list[P.Decoded] = []
        self.hellos = 0
        self.cv = threading.Condition()
        self.running = True
        self.req = 0
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    # ---- what the PSP has been told -------------------------------------------
    def latest(self, type_: int) -> dict | None:
        with self.cv:
            for m in reversed(self.received):
                if m.type == type_:
                    return m.fields
        return None

    def all(self, type_: int) -> list[dict]:
        with self.cv:
            return [m.fields for m in self.received if m.type == type_]

    def wait(self, pred, timeout: float = 5.0):
        deadline = time.monotonic() + timeout
        with self.cv:
            while True:
                v = pred()
                if v:
                    return v
                left = deadline - time.monotonic()
                if left <= 0:
                    raise TimeoutError("condition not reached; received: " + repr(self.received[-12:]))
                self.cv.wait(min(left, 0.05))

    def wait_state(self, state: int, timeout: float = 5.0) -> None:
        self.wait(lambda: (self.latest(P.T_AGENT) or {}).get("state") == state, timeout)

    def wait_activity(self, text: str, timeout: float = 5.0) -> None:
        self.wait(lambda: (self.latest(P.T_ACTIVITY) or {}).get("text") == text, timeout)

    def wait_approval(self, timeout: float = 5.0) -> dict:
        return self.wait(lambda: self.latest(P.T_APPROVAL_REQ), timeout)

    def wait_close(self, req_id: int, timeout: float = 5.0) -> dict:
        return self.wait(lambda: next((c for c in self.all(P.T_APPROVAL_CLOSE) if c["id"] == req_id), None), timeout)

    def wait_linked(self, timeout: float = 8.0) -> None:
        self.wait(lambda: self.link is not None and self.latest(P.T_CONN) is not None, timeout)

    # ---- what the PSP does -------------------------------------------------------
    def send(self, type_: int, payload: bytes) -> None:
        self.link.send(type_, payload)

    def respond(self, req_id: int, decision: int) -> None:
        self.send(P.T_APPROVAL_RESP, bytes([P.VERSION]) + req_id.to_bytes(4, "little") + bytes([decision]))

    def action(self, action: int) -> int:
        self.req += 1
        self.send(P.T_ACTION, bytes([P.VERSION]) + self.req.to_bytes(2, "little") + bytes([action]))
        return self.req

    def button(self, button: int, down: bool = True) -> None:
        self.send(P.T_BUTTON, bytes([P.VERSION, button, 1 if down else 0]))

    def drop(self) -> None:
        """Simulates pulling the cable: the connection goes away without a BYE."""
        if self.link is not None:
            self.link.t.close_client() if hasattr(self.link.t, "close_client") else self.link.t.sock.close()

    def close(self) -> None:
        self.running = False
        try:
            self.drop()
        except Exception:
            pass
        self.server.close()

    # ---- internals -----------------------------------------------------------------
    def _run(self) -> None:
        while self.running:
            try:
                self.server.accept(timeout=0.2)
            except OSError:
                continue
            link = Link(self.server, role=L.ROLE_PSP, app=self.app, name="fake-psp", max_payload=P.MAX_PAYLOAD, auto_reply=True)
            with self.cv:
                self.link = link
            last_hb = 0.0
            try:
                while self.running:
                    f = link.recv(0.02)
                    if f is not None:
                        self._on_frame(f)
                    now = time.monotonic()
                    if self.heartbeat and now - last_hb >= 0.5 and link.peer is not None:
                        link.send(P.T_HEARTBEAT, P.heartbeat(self.boot_id, int(now * 1000)))
                        last_hb = now
            except (ConnectionError, OSError):
                pass
            with self.cv:
                self.link = None
                self.cv.notify_all()
            if not self.reconnect:
                return

    def _on_frame(self, f) -> None:
        with self.cv:
            if f.type == L.T_HELLO:
                self.hellos += 1
            elif P.T_CONN <= f.type <= P.T_HEARTBEAT:
                self.received.append(P.decode_outbound(f.type, f.payload))
            self.cv.notify_all()
