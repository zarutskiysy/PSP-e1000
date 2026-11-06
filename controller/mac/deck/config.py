"""deck.toml parsing and validation (stdlib tomllib)."""
from __future__ import annotations

import pathlib
import tomllib
from dataclasses import dataclass, field

from . import keys
from .proto import BUTTONS, LABEL_LEN, WHEEL_MAX

MOUSE_BUTTONS = ("left", "right", "middle")
MEDIA_KEYS = ("playpause", "next", "previous", "volup", "voldown", "mute")
MODES = ("scroll",)
WHEEL_BUTTON = "SELECT"  # hard-wired on the PSP: hold SELECT = action wheel

DEFAULT_PATH = pathlib.Path(__file__).resolve().parents[1] / "deck.toml"


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Action:
    """kind: mouse | key | media | shell | app | mission_control | mode | none"""
    kind: str
    arg: str = ""
    keycode: int = -1        # for kind == "key"
    mods: tuple[str, ...] = ()

    def describe(self) -> str:
        return f"{self.kind}:{self.arg}" if self.arg else self.kind


def parse_action(spec: str) -> Action:
    if not isinstance(spec, str) or not spec.strip():
        raise ConfigError(f"action must be a non-empty string, got {spec!r}")
    spec = spec.strip()
    kind, _, arg = spec.partition(":")
    kind = kind.lower()
    if kind == "none":
        return Action("none")
    if kind == "mission_control":
        return Action("mission_control")
    if kind == "mouse":
        if arg not in MOUSE_BUTTONS:
            raise ConfigError(f"{spec!r}: mouse button must be one of {MOUSE_BUTTONS}")
        return Action("mouse", arg)
    if kind == "key":
        try:
            code, mods = keys.parse_combo(arg)
        except ValueError as e:
            raise ConfigError(f"{spec!r}: {e}") from None
        return Action("key", arg.lower(), code, mods)
    if kind == "media":
        if arg not in MEDIA_KEYS:
            raise ConfigError(f"{spec!r}: media key must be one of {MEDIA_KEYS}")
        return Action("media", arg)
    if kind in ("shell", "app"):
        if not arg.strip():
            raise ConfigError(f"{spec!r}: needs an argument")
        return Action(kind, arg)
    if kind == "mode":
        if arg not in MODES:
            raise ConfigError(f"{spec!r}: mode must be one of {MODES}")
        return Action("mode", arg)
    raise ConfigError(f"unknown action kind {kind!r} in {spec!r} "
                      "(mouse|key|media|shell|app|mission_control|mode|none)")


@dataclass
class MouseCfg:
    deadzone: float = 0.15
    max_speed: float = 1400.0
    exponent: float = 2.2
    invert_y: bool = False
    scroll_speed: float = 30.0


@dataclass
class KeyCfg:
    repeat_delay_ms: int = 400
    repeat_interval_ms: int = 60


@dataclass
class WheelSlot:
    label: str
    action: Action


@dataclass
class Config:
    mouse: MouseCfg = field(default_factory=MouseCfg)
    keys: KeyCfg = field(default_factory=KeyCfg)
    buttons: dict[str, Action] = field(default_factory=dict)
    wheel: list[WheelSlot] = field(default_factory=list)

    @property
    def labels(self) -> list[str]:
        return [w.label for w in self.wheel]


def _num(d: dict, k: str, default, lo, hi, typ=float):
    v = d.get(k, default)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ConfigError(f"{k} must be a number, got {v!r}")
    if not lo <= v <= hi:
        raise ConfigError(f"{k}={v} out of range [{lo}, {hi}]")
    return typ(v)


def from_dict(d: dict) -> Config:
    unknown = set(d) - {"mouse", "keys", "buttons", "wheel"}
    if unknown:
        raise ConfigError(f"unknown top-level keys: {sorted(unknown)}")
    m = d.get("mouse", {})
    mouse = MouseCfg(
        deadzone=_num(m, "deadzone", 0.15, 0.0, 0.9),
        max_speed=_num(m, "max_speed", 1400.0, 1.0, 20000.0),
        exponent=_num(m, "exponent", 2.2, 0.5, 5.0),
        invert_y=bool(m.get("invert_y", False)),
        scroll_speed=_num(m, "scroll_speed", 30.0, 0.0, 1000.0),
    )
    k = d.get("keys", {})
    kc = KeyCfg(
        repeat_delay_ms=_num(k, "repeat_delay_ms", 400, 0, 5000, int),
        repeat_interval_ms=_num(k, "repeat_interval_ms", 60, 10, 5000, int),
    )
    buttons: dict[str, Action] = {}
    for name, spec in d.get("buttons", {}).items():
        up = name.upper()
        if up == WHEEL_BUTTON:
            raise ConfigError("SELECT is reserved for the action wheel on the PSP")
        if up not in BUTTONS:
            raise ConfigError(f"unknown PSP button {name!r}; one of {sorted(set(BUTTONS) - {WHEEL_BUTTON})}")
        buttons[up] = parse_action(spec)
    wheel = []
    raw_wheel = d.get("wheel", [])
    if len(raw_wheel) > WHEEL_MAX:
        raise ConfigError(f"at most {WHEEL_MAX} wheel slices, got {len(raw_wheel)}")
    for i, w in enumerate(raw_wheel):
        if not isinstance(w, dict) or "label" not in w or "action" not in w:
            raise ConfigError(f"wheel[{i}] needs label and action")
        label = str(w["label"])
        if not label.isascii() or len(label) > LABEL_LEN - 1:
            raise ConfigError(f"wheel[{i}] label {label!r}: ASCII, at most {LABEL_LEN - 1} chars")
        wheel.append(WheelSlot(label, parse_action(w["action"])))
    return Config(mouse, kc, buttons, wheel)


def load(path: str | pathlib.Path = DEFAULT_PATH) -> Config:
    p = pathlib.Path(path)
    try:
        with p.open("rb") as f:
            d = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{p}: {e}") from None
    return from_dict(d)
