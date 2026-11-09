"""Local control channel: a Unix socket in a 0700 directory, one JSON request/response per connection.

Access control: the directory and socket are owner-only, and every peer's UID is checked with
LOCAL_PEERCRED. Other local users cannot connect. Processes of the same user can, but there is
deliberately no operation that decides an approval: only a physical PSP button can do that.
"""
from __future__ import annotations

import json
import logging
import os
import socket
import struct
import threading
from pathlib import Path

log = logging.getLogger("psp_companion.ipc")

MAX_REQUEST = 1 << 20
SOL_LOCAL = 0
LOCAL_PEERCRED = 1
HOOK_WAIT_S = 125.0
OP_WAIT_S = 70.0


def peer_uid(conn: socket.socket) -> int | None:
    try:
        raw = conn.getsockopt(SOL_LOCAL, LOCAL_PEERCRED, 76)  # struct xucred
        return struct.unpack_from("=II", raw)[1]
    except OSError:
        return None


class IpcServer(threading.Thread):
    def __init__(self, path: Path, post):
        super().__init__(name="ipc", daemon=True)
        self.path, self.post = path, post
        self.sock: socket.socket | None = None
        self._stopping = False

    def bind(self) -> None:
        try:
            self.path.unlink()  # only reached while holding the daemon lock: a leftover from a crash
        except FileNotFoundError:
            pass
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        old = os.umask(0o177)
        try:
            s.bind(str(self.path))
        finally:
            os.umask(old)
        os.chmod(self.path, 0o600)
        s.listen(16)
        self.sock = s

    def stop(self) -> None:
        self._stopping = True
        try:
            if self.sock is not None:
                self.sock.close()
        except OSError:
            pass
        try:
            self.path.unlink()
        except OSError:
            pass

    def run(self) -> None:
        while not self._stopping:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._client, args=(conn,), name="ipc-client", daemon=True).start()

    def _client(self, conn: socket.socket) -> None:
        with conn:
            if peer_uid(conn) != os.getuid():
                log.warning("rejected a connection from another user")
                return
            conn.settimeout(5.0)
            try:
                data = b""
                while b"\n" not in data and len(data) < MAX_REQUEST:
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    data += chunk
                req = json.loads(data.split(b"\n", 1)[0])
                if not isinstance(req, dict) or not isinstance(req.get("op"), str):
                    raise ValueError("bad request")
            except (OSError, ValueError):
                return
            done = threading.Event()
            box: dict = {}

            def reply(resp: dict) -> None:
                box["resp"] = resp
                done.set()

            self.post(("ipc", req, reply))
            wait = HOOK_WAIT_S if req["op"] == "hook" else OP_WAIT_S
            done.wait(wait)
            resp = box.get("resp", {"ok": False, "error": "daemon did not answer"})
            try:
                conn.settimeout(5.0)
                conn.sendall(json.dumps(resp).encode() + b"\n")
            except OSError:
                pass


class DaemonNotRunning(Exception):
    pass


def call(path: Path, op: str, timeout: float = OP_WAIT_S + 5, **args) -> dict:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        try:
            s.connect(str(path))
        except OSError as e:
            raise DaemonNotRunning(str(e)) from e
        s.sendall(json.dumps({"op": op, **args}).encode() + b"\n")
        data = b""
        while b"\n" not in data:
            chunk = s.recv(65536)
            if not chunk:
                break
            data += chunk
    finally:
        s.close()
    if not data:
        raise DaemonNotRunning("daemon closed the connection")
    return json.loads(data.split(b"\n", 1)[0])
