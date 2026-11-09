"""The companion daemon: a single core loop, fed by the PSP link, Codex and the local socket."""
from __future__ import annotations

import fcntl
import json
import logging
import logging.handlers
import os
import queue
import signal
import time
from pathlib import Path

from .appserver import AppServer
from .config import Paths
from .core import Core
from .demo import Demo
from .ipc import IpcServer
from .psplink import PspConnection
from .rollout import Tailer, find_rollout, is_thread_id, read_meta, scan_tail

log = logging.getLogger("psp_companion.daemon")


class _JsonFormatter(logging.Formatter):
    def format(self, r: logging.LogRecord) -> str:
        return json.dumps({"t": round(r.created, 3), "lvl": r.levelname, "src": r.name.rsplit(".", 1)[-1], "msg": r.getMessage()})


def setup_logging(paths: Paths, foreground: bool) -> None:
    root = logging.getLogger("psp_companion")
    root.setLevel(logging.DEBUG if os.environ.get("PSP_COMPANION_DEBUG") else logging.INFO)
    h = logging.handlers.RotatingFileHandler(paths.log, maxBytes=1 << 20, backupCount=3)
    h.setFormatter(_JsonFormatter())
    root.addHandler(h)
    if foreground and os.environ.get("PSP_COMPANION_ECHO"):
        root.addHandler(logging.StreamHandler())


class Daemon:
    def __init__(self, paths: Paths, transport: str, codex_bin: str | None = None):
        self.paths = paths
        self.q: queue.Queue = queue.Queue()
        self.running = True
        self.psp = PspConnection(transport, self.q.put)
        self.codex = AppServer(self.q.put, codex_bin, str(paths.home / "appserver.log"))
        self.core = Core(self.psp, self.codex, self._start_tail)
        self.ipc = IpcServer(paths.sock, self.q.put)
        self.lock_file = None

    def _start_tail(self, sid: str, path: str):
        t = Tailer(sid, path, self.q.put)
        t.start()
        return t

    def _acquire(self) -> bool:
        self.lock_file = open(self.paths.lock, "w")
        try:
            fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        self.lock_file.write(str(os.getpid()))
        self.lock_file.flush()
        return True

    # ---- IPC operations (run on the core loop) ------------------------------
    def _op_attach(self, req: dict, reply) -> None:
        tid = str(req.get("thread_id") or "")
        if not is_thread_id(tid):
            reply({"ok": False, "error": f"not a Codex thread id: {tid!r}"})
            return
        path = find_rollout(tid)
        meta = read_meta(path) if path else None
        if path is None or meta is None:
            reply({"ok": False, "error": f"no rollout found for thread {tid}"})
            return
        if str(meta.get("id")) != tid:
            reply({"ok": False, "error": "rollout does not belong to this thread"})
            return
        running, turn = scan_tail(path)
        reply(self.core.attach_observe(tid, str(meta.get("cwd") or ""), str(path), running, turn))

    def _handle_ipc(self, req: dict, reply) -> None:
        op = req["op"]
        core = self.core
        if op == "ping":
            reply({"ok": True, "pid": os.getpid()})
        elif op == "status":
            reply({"ok": True, **core.status()})
        elif op == "attach":
            self._op_attach(req, reply)
        elif op == "detach":
            reply({"ok": True, "detached": core.detach(req.get("thread_id"))})
        elif op == "select":
            reply({"ok": core.select(str(req.get("thread_id")))})
        elif op == "start_managed":
            cwd = os.path.realpath(str(req.get("cwd") or ""))
            if not os.path.isdir(cwd):
                reply({"ok": False, "error": f"no such directory: {cwd}"})
                return
            core.start_managed(cwd, str(req.get("approval_policy") or "on-request"), str(req.get("sandbox") or "workspace-write"),
                               reply, bool(req.get("ephemeral")), req.get("model"))
        elif op == "prompt":
            core.send_prompt(req.get("thread_id"), str(req.get("text") or ""), reply)
        elif op == "hook":
            payload = req.get("payload")
            if not isinstance(payload, dict):
                reply({})
            else:
                core.on_hook(payload, reply)
        elif op == "demo_start":
            if core.demo is not None:
                reply({"ok": False, "error": "demo is already running"})
            elif core.sessions:
                reply({"ok": False, "error": "a real session is attached; run `psp-companion disconnect` first"})
            elif not core.psp_up:
                reply({"ok": False, "error": "PSP is not linked yet", "retry": True})
            else:
                core.last_demo = None
                core.demo = Demo(core, float(req.get("speed") or 1.0), float(req.get("approval_timeout") or 45.0))
                core.demo.start()
                reply({"ok": True})
        elif op == "demo_status":
            d = core.demo.info() if core.demo is not None else getattr(core, "last_demo", None)
            reply({"ok": True, "demo": d})
        elif op == "demo_stop":
            if core.demo is not None:
                core.demo.stop("requested")
            reply({"ok": True})
        elif op == "shutdown":
            reply({"ok": True})
            self.running = False
        else:
            reply({"ok": False, "error": f"unknown op {op!r}"})

    # ---- main loop -----------------------------------------------------------
    def _dispatch(self, item: tuple) -> None:
        kind = item[0]
        core = self.core
        if kind == "psp_link":
            core.on_psp_link(item[1])
        elif kind == "psp_frame":
            core.on_psp_frame(item[1], item[2])
        elif kind == "appserver":
            core.on_appserver(item[1])
        elif kind == "appserver_exit":
            core.on_appserver_exit()
        elif kind == "rollout":
            core.on_rollout(item[1], item[2])
        elif kind == "call":
            item[1](item[2], item[3])
        elif kind == "ipc":
            try:
                self._handle_ipc(item[1], item[2])
            except Exception as e:
                log.exception("ipc op failed")
                item[2]({"ok": False, "error": str(e)})

    def run(self) -> int:
        if not self._acquire():
            return 3  # another daemon owns the lock: exiting is the correct, quiet result
        self.ipc.bind()
        signal.signal(signal.SIGTERM, lambda *_: setattr(self, "running", False))
        signal.signal(signal.SIGINT, lambda *_: setattr(self, "running", False))
        self.ipc.start()
        self.psp.start()
        log.info("daemon started pid=%d transport=%s", os.getpid(), self.psp.spec)
        last_expire = time.monotonic()
        while self.running:
            try:
                item = self.q.get(timeout=0.05)
            except queue.Empty:
                item = None
            try:
                if item is not None:
                    self._dispatch(item)
                self.core.tick()
                if time.monotonic() - last_expire > 1.0:
                    self.codex.expire()
                    last_expire = time.monotonic()
            except Exception:
                log.exception("core loop error")
        log.info("daemon stopping")
        self.core.shutdown()
        # let the PSP see the end of the session before the writer goes away
        time.sleep(0.1)
        self.psp.stop()
        self.psp.join(timeout=4)
        self.codex.stop()
        self.ipc.stop()
        return 0


def run_daemon(paths: Paths, transport: str, codex_bin: str | None, foreground: bool) -> int:
    paths.ensure()
    setup_logging(paths, foreground)
    return Daemon(paths, transport, codex_bin).run()
