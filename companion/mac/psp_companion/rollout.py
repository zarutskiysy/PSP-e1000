"""Read-only access to Codex session rollouts (~/.codex/sessions/YYYY/MM/DD/rollout-*-<id>.jsonl).

The rollout path is exposed by Codex (hooks receive it as transcript_path), but its record format is not a
documented API, so this is best effort: unknown records are ignored and nothing here ever writes.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from pathlib import Path

log = logging.getLogger("psp_companion.rollout")

_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def is_thread_id(value: str) -> bool:
    return bool(_UUID_RE.match(value or ""))


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or "~/.codex").expanduser()


def find_rollout(thread_id: str, home: Path | None = None) -> Path | None:
    if not is_thread_id(thread_id):  # the id goes into a glob: never let it be anything else
        return None
    root = (home or codex_home()) / "sessions"
    if not root.is_dir():
        return None
    for year in sorted((p for p in root.iterdir() if p.is_dir()), reverse=True):
        for month in sorted((p for p in year.iterdir() if p.is_dir()), reverse=True):
            for day in sorted((p for p in month.iterdir() if p.is_dir()), reverse=True):
                hits = list(day.glob(f"rollout-*-{thread_id}.jsonl"))
                if hits:
                    return hits[0]
    return None


def read_meta(path: Path) -> dict | None:
    """The session_meta payload from the first line (it can be very long: base instructions)."""
    try:
        with open(path, "rb") as f:
            first = f.readline(8 * 1024 * 1024)
        rec = json.loads(first)
    except (OSError, ValueError):
        return None
    if rec.get("type") != "session_meta" or not isinstance(rec.get("payload"), dict):
        return None
    return rec["payload"]


def scan_tail(path: Path, max_bytes: int = 1 << 20) -> tuple[bool, str | None]:
    """Is a turn running right now, judged from the most recent start/end records?"""
    running, turn = False, None
    try:
        size = path.stat().st_size
        with open(path, "rb") as f:
            f.seek(max(0, size - max_bytes))
            data = f.read()
    except OSError:
        return False, None
    for raw in data.split(b"\n"):
        if b'"event_msg"' not in raw:
            continue
        try:
            rec = json.loads(raw)
        except ValueError:
            continue
        p = rec.get("payload") or {}
        if rec.get("type") != "event_msg" or not isinstance(p, dict):
            continue
        if p.get("type") == "task_started":
            running, turn = True, p.get("turn_id")
        elif p.get("type") in ("task_complete", "turn_aborted"):
            running, turn = False, None
    return running, turn


def recent_sessions(cwd: str | None = None, limit: int = 6, max_age_s: float = 3600.0, home: Path | None = None) -> list[dict]:
    """Recently written rollouts, newest first, optionally only those started in cwd."""
    root = (home or codex_home()) / "sessions"
    if not root.is_dir():
        return []
    now = time.time()
    candidates = []
    for p in root.glob("*/*/*/rollout-*.jsonl"):
        try:
            mtime = p.stat().st_mtime
        except OSError:
            continue
        if now - mtime <= max_age_s:
            candidates.append((mtime, p))
    out: list[dict] = []
    want = os.path.realpath(cwd) if cwd else None
    for mtime, p in sorted(candidates, reverse=True):
        meta = read_meta(p)
        if not meta or not meta.get("id"):
            continue
        if want and os.path.realpath(str(meta.get("cwd") or "")) != want:
            continue
        out.append({"id": meta["id"], "cwd": meta.get("cwd"), "age_s": int(now - mtime), "path": str(p)})
        if len(out) >= limit:
            break
    return out


class Tailer(threading.Thread):
    """Follows one rollout from its current end and posts each new record."""

    def __init__(self, sid: str, path: str, post, interval: float = 0.2):
        super().__init__(name=f"tail-{sid[:8]}", daemon=True)
        self.sid, self.path, self.post, self.interval = sid, path, post, interval
        self._stop_event = threading.Event()
        self.offset = os.path.getsize(path)

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        buf = b""
        while not self._stop_event.wait(self.interval):
            try:
                size = os.path.getsize(self.path)
                if size < self.offset:  # rewritten: start over rather than read garbage
                    self.offset, buf = 0, b""
                if size == self.offset:
                    continue
                with open(self.path, "rb") as f:
                    f.seek(self.offset)
                    data = f.read(1 << 20)
                self.offset += len(data)
            except OSError as e:
                log.warning("rollout read failed: %s", e)
                continue
            buf += data
            *lines, buf = buf.split(b"\n")
            for raw in lines:
                if not raw.strip():
                    continue
                try:
                    rec = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(rec, dict):
                    self.post(("rollout", self.sid, rec))
