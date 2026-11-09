"""Client for `codex app-server` over stdio (newline-delimited JSON-RPC, the documented default transport).

Never blocks the caller: request() returns at once and the callback is delivered on the daemon's core
loop through `post`. The child process starts on first use, so sessions that only observe never spawn it.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
import time

from . import __version__

log = logging.getLogger("psp_companion.appserver")

DESKTOP_CLI = "/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex"
REQUEST_TIMEOUT_S = 60.0


def find_codex(explicit: str | None = None) -> str | None:
    for candidate in (explicit, os.environ.get("PSP_COMPANION_CODEX"), shutil.which("codex"), DESKTOP_CLI):
        if candidate and os.path.exists(candidate):
            return candidate
    return None


class AppServer:
    def __init__(self, post, codex_bin: str | None = None, stderr_path: str | None = None):
        self.post = post
        self.codex_bin = codex_bin
        self.stderr_path = stderr_path
        self.proc: subprocess.Popen | None = None
        self._wlock = threading.Lock()
        self._state = threading.Lock()
        self._next = 1
        self._pending: dict[int, tuple] = {}
        self._ready = False
        self._starting = False
        self._queue: list[tuple] = []

    # ---- public --------------------------------------------------------------
    def request(self, method: str, params: dict, cb) -> None:
        with self._state:
            if self._ready:
                send_now = True
            else:
                send_now = False
                self._queue.append((method, params, cb))
                if not self._starting:
                    self._starting = True
                    threading.Thread(target=self._start, name="appserver-start", daemon=True).start()
        if send_now:
            self._send_request(method, params, cb)

    def respond(self, rpc_id, result: dict) -> None:
        self._write({"id": rpc_id, "result": result})

    def respond_error(self, rpc_id, code: int, message: str) -> None:
        self._write({"id": rpc_id, "error": {"code": code, "message": message}})

    def expire(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        with self._state:
            dead = [k for k, v in self._pending.items() if now > v[2]]
            items = [self._pending.pop(k) for k in dead]
        for method, cb, _ in items:
            self.post(("call", cb, None, {"message": f"{method} timed out"}))

    def stop(self) -> None:
        p = self.proc
        if p is None:
            return
        try:
            p.stdin.close()
            p.terminate()
            p.wait(timeout=3)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass

    # ---- internals -----------------------------------------------------------
    def _start(self) -> None:
        err = None
        try:
            codex = find_codex(self.codex_bin)
            if codex is None:
                raise RuntimeError("codex CLI not found")
            stderr = open(self.stderr_path, "ab") if self.stderr_path else subprocess.DEVNULL
            self.proc = subprocess.Popen([codex, "app-server", "--listen", "stdio://"], stdin=subprocess.PIPE,
                                         stdout=subprocess.PIPE, stderr=stderr, bufsize=0)
            threading.Thread(target=self._reader, name="appserver-read", daemon=True).start()
            done = threading.Event()
            box: dict = {}

            def init_cb(result, error):
                box["error"] = error
                done.set()

            self._register_and_send(
                "initialize",
                {
                    "clientInfo": {"name": "psp_companion", "title": "PSP AI Companion", "version": __version__},
                    "capabilities": {"experimentalApi": False, "requestAttestation": False},
                },
                init_cb,
                direct=True,
            )
            if not done.wait(20) or box.get("error"):
                raise RuntimeError(f"initialize failed: {box.get('error', 'timeout')}")
            self._write({"method": "initialized"})
        except Exception as e:
            err = e
        with self._state:
            self._starting = False
            queued, self._queue = self._queue, []
            self._ready = err is None
        if err is not None:
            log.warning("app-server start failed: %s", err)
            for method, _params, cb in queued:
                self.post(("call", cb, None, {"message": f"cannot start codex app-server: {err}"}))
            return
        log.info("app-server ready (pid %s)", self.proc.pid)
        for method, params, cb in queued:
            self._send_request(method, params, cb)

    def _send_request(self, method: str, params: dict, cb) -> None:
        self._register_and_send(method, params, cb, direct=False)

    def _register_and_send(self, method: str, params: dict, cb, direct: bool) -> None:
        with self._state:
            rid = self._next
            self._next += 1
            self._pending[rid] = (method, cb, time.monotonic() + REQUEST_TIMEOUT_S, direct)
        try:
            self._write({"id": rid, "method": method, "params": params})
        except OSError as e:
            with self._state:
                self._pending.pop(rid, None)
            if direct:
                cb(None, {"message": str(e)})
            else:
                self.post(("call", cb, None, {"message": str(e)}))

    def _write(self, msg: dict) -> None:
        p = self.proc
        if p is None or p.stdin is None:
            raise OSError("app-server is not running")
        data = (json.dumps(msg, separators=(",", ":")) + "\n").encode()
        with self._wlock:
            p.stdin.write(data)
            p.stdin.flush()

    def _reader(self) -> None:
        assert self.proc is not None and self.proc.stdout is not None
        buf = b""
        while True:
            try:
                chunk = self.proc.stdout.read(65536)
            except (OSError, ValueError):
                chunk = b""
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if line.strip():
                    self._handle(line)
        self._on_exit()

    def _handle(self, line: bytes) -> None:
        try:
            msg = json.loads(line)
        except ValueError:
            log.warning("app-server sent invalid JSON")
            return
        if "id" in msg and ("result" in msg or "error" in msg):
            with self._state:
                entry = self._pending.pop(msg["id"], None)
            if entry is None:
                return
            _method, cb, _deadline, direct = entry
            if direct:
                cb(msg.get("result"), msg.get("error"))
            else:
                self.post(("call", cb, msg.get("result"), msg.get("error")))
        else:
            self.post(("appserver", msg))

    def _on_exit(self) -> None:
        with self._state:
            self._ready = False
            pending, self._pending = self._pending, {}
        log.warning("app-server exited")
        for method, cb, _deadline, direct in pending.values():
            if direct:
                cb(None, {"message": "app-server exited"})
            else:
                self.post(("call", cb, None, {"message": "app-server exited"}))
        self.post(("appserver_exit",))
