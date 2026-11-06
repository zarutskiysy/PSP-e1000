"""PSP input -> abstract Mac events. Pure logic (no pyobjc), unit-tested.

Mouse: radial deadzone, power-curve acceleration, sub-pixel accumulation, time-based (uses the
PSP timestamp in INPUT_STATE, so a delayed/bunched USB packet does not change the distance).
Buttons: edge-triggered; keys repeat on hold (synthetic key-downs are not auto-repeated by macOS
in our experience; UNVERIFIED either way, so we repeat ourselves with the autorepeat flag set).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .config import Action, Config
from .proto import BUTTONS, InputState

DT_FIRST = 1 / 60
DT_MAX = 0.05  # a gap longer than this (pause, reconnect) must not teleport the cursor


@dataclass
class Event:
    kind: str  # mouse_move | mouse_button | scroll | key | media | shell | app | mission_control
    args: dict = field(default_factory=dict)

    def __getitem__(self, k):
        return self.args[k]

    def to_json(self) -> dict:
        return {"ev": self.kind, **self.args}


def nub_vector(lx: int, ly: int, deadzone: float, exponent: float, invert_y: bool = False) -> tuple[float, float]:
    """Raw 0..255 nub -> (vx, vy) with |v| in [0,1]. +x right, +y down (CG screen coordinates)."""
    x = max(-1.0, min(1.0, (lx - 128) / 127.0))
    y = max(-1.0, min(1.0, (ly - 128) / 127.0))
    if invert_y:
        y = -y
    m = math.hypot(x, y)
    if m <= deadzone or m == 0.0:
        return 0.0, 0.0
    mm = min(1.0, (m - deadzone) / (1.0 - deadzone))
    s = mm ** exponent
    return x / m * s, y / m * s


def action_events(a: Action, down: bool | None = None, repeat: bool = False) -> list[Event]:
    """Events for an action. down=None means a full press (down+up / one-shot)."""
    if a.kind == "mouse":
        if down is None:
            return [Event("mouse_button", {"button": a.arg, "down": True}),
                    Event("mouse_button", {"button": a.arg, "down": False})]
        return [Event("mouse_button", {"button": a.arg, "down": down})]
    if a.kind == "key":
        mk = lambda d, r=False: Event("key", {"key": a.arg, "keycode": a.keycode, "mods": list(a.mods),
                                              "down": d, "repeat": r})
        if down is None:
            return [mk(True), mk(False)]
        return [mk(down, repeat)]
    if down is False:
        return []  # one-shot actions fire on press only
    if a.kind == "media":
        return [Event("media", {"key": a.arg})]
    if a.kind in ("shell", "app"):
        return [Event(a.kind, {"cmd" if a.kind == "shell" else "name": a.arg})]
    if a.kind == "mission_control":
        return [Event("mission_control")]
    return []


class Mapper:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.prev_buttons = 0
        self.acc_x = self.acc_y = 0.0
        self.sacc = 0.0
        self.last_t: int | None = None
        self.now = 0.0
        self.scroll_mode = False
        self.repeat_at: dict[str, float] = {}

    def _dt(self, t_us: int) -> float:
        if self.last_t is None:
            dt = DT_FIRST
        else:
            dt = ((t_us - self.last_t) & 0xFFFFFFFF) / 1e6
            dt = min(max(dt, 0.0), DT_MAX)
        self.last_t = t_us
        return dt

    def on_input(self, st: InputState) -> list[Event]:
        dt = self._dt(st.t_us)
        self.now += dt
        out: list[Event] = []
        pressed = st.buttons & ~self.prev_buttons
        released = self.prev_buttons & ~st.buttons
        self.prev_buttons = st.buttons
        kc = self.cfg.keys
        for name, bit in BUTTONS.items():
            a = self.cfg.buttons.get(name)
            if a is None or a.kind == "none":
                continue
            if a.kind == "mode":
                if pressed & bit:
                    self.scroll_mode = True
                    self.sacc = 0.0
                elif released & bit:
                    self.scroll_mode = False
                continue
            if pressed & bit:
                out += action_events(a, True)
                if a.kind == "key":
                    self.repeat_at[name] = self.now + kc.repeat_delay_ms / 1000
            elif released & bit:
                out += action_events(a, False)
                self.repeat_at.pop(name, None)
            elif (st.buttons & bit) and name in self.repeat_at and self.now >= self.repeat_at[name]:
                out += action_events(a, True, repeat=True)
                self.repeat_at[name] += kc.repeat_interval_ms / 1000
        if st.wheel_open:
            self.acc_x = self.acc_y = self.sacc = 0.0
            return out
        m = self.cfg.mouse
        vx, vy = nub_vector(st.lx, st.ly, m.deadzone, m.exponent, m.invert_y)
        if self.scroll_mode:
            self.sacc += -vy * m.scroll_speed * dt  # nub up -> wheel up (positive)
            n = int(self.sacc)
            if n:
                self.sacc -= n
                out.append(Event("scroll", {"dy": n}))
        else:
            self.acc_x += vx * m.max_speed * dt
            self.acc_y += vy * m.max_speed * dt
            dx, dy = int(self.acc_x), int(self.acc_y)
            if dx or dy:
                self.acc_x -= dx
                self.acc_y -= dy
                out.append(Event("mouse_move", {"dx": dx, "dy": dy}))
        return out

    def release_all(self) -> list[Event]:
        """On disconnect: release everything still held so no key/button gets stuck."""
        out: list[Event] = []
        for name, bit in BUTTONS.items():
            a = self.cfg.buttons.get(name)
            if a is not None and (self.prev_buttons & bit) and a.kind in ("mouse", "key"):
                out += action_events(a, False)
        self.prev_buttons = 0
        self.repeat_at.clear()
        self.scroll_mode = False
        self.last_t = None
        return out

    def wheel_events(self, idx: int) -> tuple[str, list[Event]]:
        if not 0 <= idx < len(self.cfg.wheel):
            raise IndexError(f"wheel slice {idx} not configured ({len(self.cfg.wheel)} slices)")
        slot = self.cfg.wheel[idx]
        return slot.label, action_events(slot.action, None)
