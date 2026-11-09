"""Keeps a connection to the PSP over the existing pspmac transports, reconnecting forever.

Sends never block the caller: they go through a queue to a writer thread, because a USB write can stall
for up to 2 s and the core loop must not.
"""
from __future__ import annotations

import logging
import queue
import random
import threading
import time

from pspmac import protocol as L
from pspmac.link import Link
from pspmac.transport import open_transport

from . import protocol as P

log = logging.getLogger("psp_companion.psplink")

HEARTBEAT_S = 1.0
LINK_TIMEOUT_S = 3.5
RETRY_S = 1.0


class PspConnection(threading.Thread):
    def __init__(self, spec: str, post):
        super().__init__(name="psp-link", daemon=True)
        self.spec = spec
        self.post = post
        self.status_text = "starting"
        self._stop_event = threading.Event()
        self._out: queue.Queue = queue.Queue(maxsize=512)
        self._link: Link | None = None
        self.boot_id = random.getrandbits(32) | 1

    # called from the core thread
    def send(self, type_: int, payload: bytes) -> None:
        try:
            self._out.put_nowait((type_, payload))
        except queue.Full:
            log.warning("psp send queue full, dropping 0x%02X", type_)

    def stop(self) -> None:
        self._stop_event.set()

    def _set_status(self, text: str) -> None:
        if text != self.status_text:
            self.status_text = text
            log.info("psp: %s", text)

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._session()
            except Exception as e:  # whatever goes wrong here, keep trying: this thread must never die
                if not isinstance(e, (ConnectionError, TimeoutError, OSError, RuntimeError, ImportError, ValueError)):
                    log.exception("unexpected link error")
                self._set_status(self._describe(e))
            self._stop_event.wait(RETRY_S)

    def _describe(self, e: Exception) -> str:
        msg = str(e)
        if isinstance(e, ImportError):
            return "pyusb is not installed"
        if "PSP not found" in msg:
            return "waiting for PSP on USB"
        if "no HELLO_ACK" in msg:
            return "PSP found, app is not answering"
        return f"waiting for PSP ({msg[:60]})"

    def _session(self) -> None:
        kw = {"connect_timeout": 1.0} if self.spec != "usb" and not self.spec.startswith("usb:") else {}
        transport = open_transport(self.spec, **kw)
        link = Link(transport, app=P.APP_ID, name="psp-companion", max_payload=4096)
        try:
            peer = link.handshake(timeout=0.5, attempts=4)
            if peer.app != P.APP_ID:
                raise RuntimeError(f"PSP is running another app (id {peer.app})")
            self._link = link
            self._drain()
            self.post(("psp_link", True))
            self._set_status("connected")
            self._run_link(link)
        finally:
            was_up = self._link is not None
            self._link = None
            if was_up:
                self.post(("psp_link", False))
            try:
                link.close(bye=was_up)
            except Exception:
                pass

    def _drain(self) -> None:
        try:
            while True:
                self._out.get_nowait()
        except queue.Empty:
            pass

    def _run_link(self, link: Link) -> None:
        broken: list[Exception] = []
        stop_writer = threading.Event()

        def writer() -> None:
            while not stop_writer.is_set():
                try:
                    t, p = self._out.get(timeout=0.1)
                except queue.Empty:
                    continue
                try:
                    link.send(t, p)
                except Exception as e:
                    broken.append(e)
                    return

        w = threading.Thread(target=writer, name="psp-write", daemon=True)
        w.start()
        last_rx = last_hb = time.monotonic()
        start = last_rx
        try:
            while not self._stop_event.is_set():
                if broken:
                    raise ConnectionError(str(broken[0]))
                f = link.recv(0.05)
                now = time.monotonic()
                if f is not None:
                    last_rx = now
                    if f.type == L.T_BYE:
                        raise ConnectionError("PSP app closed")
                    if f.type not in (L.T_HELLO, L.T_HELLO_ACK, L.T_PING, L.T_PONG):
                        self.post(("psp_frame", f.type, f.payload))
                if now - last_hb >= HEARTBEAT_S:
                    self.send(P.T_HEARTBEAT, P.heartbeat(self.boot_id, int((now - start) * 1000)))
                    last_hb = now
                if now - last_rx > LINK_TIMEOUT_S:
                    raise TimeoutError("PSP stopped responding")
        finally:
            stop_writer.set()
            w.join(timeout=3)
