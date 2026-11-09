"""Locations and persistent settings. The state directory is short on purpose: AF_UNIX paths are limited
to 104 bytes on macOS."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Paths:
    home: Path

    @classmethod
    def default(cls) -> "Paths":
        return cls(Path(os.environ.get("PSP_COMPANION_HOME") or "~/.psp-companion").expanduser())

    @property
    def sock(self) -> Path:
        return self.home / "daemon.sock"

    @property
    def lock(self) -> Path:
        return self.home / "daemon.lock"

    @property
    def log(self) -> Path:
        return self.home / "daemon.log"

    @property
    def config(self) -> Path:
        return self.home / "config.json"

    def ensure(self) -> None:
        self.home.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.home, 0o700)


def load_config(paths: Paths) -> dict:
    try:
        return json.loads(paths.config.read_text())
    except (OSError, ValueError):
        return {}


def save_config(paths: Paths, cfg: dict) -> None:
    paths.ensure()
    tmp = paths.config.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2) + "\n")
    os.replace(tmp, paths.config)


def default_transport(paths: Paths) -> str:
    return os.environ.get("PSP_COMPANION_TRANSPORT") or load_config(paths).get("transport") or "usb"
