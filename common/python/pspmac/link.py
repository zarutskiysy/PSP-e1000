"""Framed link over a Transport: send/recv frames, HELLO handshake, PING/PONG, thread-safe send."""
from __future__ import annotations

import collections
import struct
import threading
import time

from . import protocol as P
from .transport import Transport


class Link:
    def __init__(self, transport: Transport, role: int = P.ROLE_MAC, app: int = P.APP_GENERIC,
                 name: str = "mac", max_payload: int = 1 << 20, auto_reply: bool = True):
        self.t = transport
        self.role, self.app, self.name = role, app, name
        self.parser = P.Parser(max_payload)
        self.seq = 0
        self.auto_reply = auto_reply
        self.peer: P.Hello | None = None
        self._q: collections.deque[P.Frame] = collections.deque()
        self._send_lock = threading.Lock()
        self.tx_frames = self.rx_frames = 0
        self.tx_bytes = self.rx_bytes = 0

    # -- sending -------------------------------------------------------------
    def send(self, type_: int, payload: bytes = b"", flags: int = 0) -> None:
        with self._send_lock:
            data = P.encode(type_, payload, self.seq, flags)
            self.seq = (self.seq + 1) & 0xFFFF
            self.t.write(data)
            self.tx_frames += 1
            self.tx_bytes += len(data)

    def hello_payload(self) -> bytes:
        return P.Hello(P.VERSION, self.role, self.app, self.parser.max_payload, self.name).pack()

    def log(self, text: str) -> None:
        self.send(P.T_LOG, text.encode())

    # -- receiving -----------------------------------------------------------
    def _pump(self, timeout: float | None) -> None:
        data = self.t.read(65536, timeout)
        if data:
            self.rx_bytes += len(data)
            for f in self.parser.feed(data):
                self.rx_frames += 1
                self._auto(f)
                self._q.append(f)

    def _auto(self, f: P.Frame) -> None:
        if f.type in (P.T_HELLO, P.T_HELLO_ACK) and len(f.payload) >= 8:
            self.peer = P.Hello.unpack(f.payload)
        if not self.auto_reply:
            return
        if f.type == P.T_HELLO:
            self.send(P.T_HELLO_ACK, self.hello_payload())
        elif f.type == P.T_PING:
            self.send(P.T_PONG, f.payload)

    def recv(self, timeout: float | None = 0.1) -> P.Frame | None:
        """Next frame or None on timeout. PING/HELLO are auto-answered but still returned."""
        deadline = None if timeout is None else time.monotonic() + timeout
        while not self._q:
            remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
            self._pump(remaining if remaining is None or remaining > 0 else 0.001)
            if not self._q and deadline is not None and time.monotonic() >= deadline:
                return None
        return self._q.popleft()

    def wait_for(self, type_: int, timeout: float = 2.0) -> P.Frame | None:
        """Wait for a frame of a given type, dropping others (they are lost)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            f = self.recv(deadline - time.monotonic())
            if f is not None and f.type == type_:
                return f
        return None

    # -- helpers -------------------------------------------------------------
    def handshake(self, timeout: float = 3.0) -> P.Hello:
        self.send(P.T_HELLO, self.hello_payload())
        f = self.wait_for(P.T_HELLO_ACK, timeout)
        if f is None:
            raise TimeoutError("no HELLO_ACK from peer")
        return self.peer  # type: ignore[return-value]

    def ping(self, timeout: float = 1.0) -> float:
        """Round-trip time in seconds."""
        t0 = time.perf_counter()
        token = struct.pack("<d", t0)
        self.send(P.T_PING, token)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            f = self.recv(deadline - time.monotonic())
            if f is not None and f.type == P.T_PONG and f.payload == token:
                return time.perf_counter() - t0
        raise TimeoutError("no PONG")

    def close(self, bye: bool = True) -> None:
        if bye:
            try:
                self.send(P.T_BYE)
            except Exception:
                pass
        self.t.close()
