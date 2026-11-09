"""Installs the global skills and launcher, and (separately, on request) the optional Codex hooks."""
from __future__ import annotations

import json
import os
import shlex
import shutil
import sys
from pathlib import Path

from . import __version__
from .config import Paths, load_config, save_config

MARKER = ".psp-companion-managed"
SKILLS = ("psp-connect", "psp-disconnect")
HOOK_MARK = "psp_hook.py"

# event -> (timeout seconds, matcher or None)
HOOK_EVENTS = {
    "UserPromptSubmit": (3, None),
    "PreToolUse": (3, ".*"),
    "PostToolUse": (3, ".*"),
    "PermissionRequest": (125, ".*"),
    "PreCompact": (3, None),
    "Stop": (3, None),
    "Interrupt": (2, None),
    "SessionEnd": (2, None),
}


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def skills_dir() -> Path:
    return Path(os.environ.get("PSP_COMPANION_SKILLS") or "~/.agents/skills").expanduser()


def install_skills(force: bool = False) -> list[str]:
    root, dest_root, done = project_root(), skills_dir(), []
    dest_root.mkdir(parents=True, exist_ok=True)
    for name in SKILLS:
        src, dst = root / "companion" / "skills" / name, dest_root / name
        if dst.exists():
            if not (dst / MARKER).exists() and not force:
                raise RuntimeError(f"{dst} exists and was not installed by psp-companion; use --force to replace it")
            shutil.rmtree(dst)
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))
        (dst / MARKER).write_text(__version__ + "\n")
        done.append(str(dst))
    return done


def install(force: bool = False, transport: str | None = None) -> dict:
    paths = Paths.default()
    cfg = load_config(paths)
    cfg.update({"root": str(project_root()), "python": sys.executable})
    if transport:
        cfg["transport"] = transport
    cfg.setdefault("transport", "usb")
    save_config(paths, cfg)
    skills = install_skills(force)
    link = Path(os.environ.get("PSP_COMPANION_BIN") or "~/.local/bin").expanduser() / "psp-companion"
    link.parent.mkdir(parents=True, exist_ok=True)
    target = project_root() / "tools" / "psp-companion"
    if link.is_symlink() or not link.exists():
        if link.is_symlink():
            link.unlink()
        link.symlink_to(target)
    else:
        raise RuntimeError(f"{link} exists and is not a symlink; remove it first")
    return {"config": str(paths.config), "skills": skills, "launcher": str(link), "root": cfg["root"]}


def uninstall() -> list[str]:
    removed = []
    for name in SKILLS:
        d = skills_dir() / name
        if (d / MARKER).exists():
            shutil.rmtree(d)
            removed.append(str(d))
    link = Path(os.environ.get("PSP_COMPANION_BIN") or "~/.local/bin").expanduser() / "psp-companion"
    if link.is_symlink():
        link.unlink()
        removed.append(str(link))
    return removed


# ---- hooks (optional, never installed implicitly) ----------------------------------
def hooks_path() -> Path:
    return Path(os.environ.get("CODEX_HOME") or "~/.codex").expanduser() / "hooks.json"


def _hook_command() -> str:
    python = Path(sys.base_prefix) / "bin" / "python3"
    script = skills_dir() / "psp-connect" / "scripts" / HOOK_MARK
    return f"{shlex.quote(str(python))} -I -S {shlex.quote(str(script))}"


def _load_hooks(path: Path) -> dict:
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise RuntimeError(f"{path} is not a JSON object")
    return data


def _strip_ours(data: dict) -> dict:
    """Removes only our handlers; every other hook and setting stays exactly as it was."""
    table = data.get("hooks")
    if not isinstance(table, dict):
        return data
    for event in list(table):
        groups = []
        for g in table[event]:
            kept = [h for h in g.get("hooks", []) if HOOK_MARK not in str(h.get("command", ""))]
            if kept:
                groups.append({**g, "hooks": kept})
        if groups:
            table[event] = groups
        else:
            del table[event]
    return data


def hooks_install() -> Path:
    path = hooks_path()
    data = _strip_ours(_load_hooks(path))
    if path.exists():
        backup = path.with_name(path.name + ".psp-backup")
        if not backup.exists():
            shutil.copy2(path, backup)
    table = data.setdefault("hooks", {})
    cmd = _hook_command()
    for event, (timeout, matcher) in HOOK_EVENTS.items():
        group: dict = {"hooks": [{"type": "command", "command": cmd, "timeout": timeout}]}
        if matcher:
            group = {"matcher": matcher, **group}
        table.setdefault(event, []).append(group)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".psp-tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(tmp, path)
    return path


def hooks_uninstall() -> bool:
    path = hooks_path()
    if not path.exists():
        return False
    data = _load_hooks(path)
    before = json.dumps(data, sort_keys=True)
    data = _strip_ours(data)
    if json.dumps(data, sort_keys=True) == before:
        return False
    tmp = path.with_suffix(".psp-tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(tmp, path)
    return True


def hooks_installed() -> bool:
    path = hooks_path()
    try:
        return HOOK_MARK in path.read_text()
    except OSError:
        return False
