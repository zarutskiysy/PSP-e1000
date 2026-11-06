"""Python mirror of controller/proto_controller.h (track range 0x10-0x3F). Keep in sync;
controller/tests/test_proto.py parses the C header and compares."""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

APP_ID = 1

T_INPUT_STATE = 0x10
T_WHEEL_CONFIG = 0x11
T_WHEEL_FIRE = 0x12
T_ACTION_RESULT = 0x13
T_CONFIG_REQ = 0x14
T_MAC_STATUS = 0x15

TYPE_NAMES = {
    T_INPUT_STATE: "INPUT_STATE", T_WHEEL_CONFIG: "WHEEL_CONFIG", T_WHEEL_FIRE: "WHEEL_FIRE",
    T_ACTION_RESULT: "ACTION_RESULT", T_CONFIG_REQ: "CONFIG_REQ", T_MAC_STATUS: "MAC_STATUS",
}

INPUT_SIZE = 16
IN_F_WHEEL_OPEN = 0x01
NO_SLICE = 0xFF
WHEEL_MAX = 8
LABEL_LEN = 24
WHEEL_CONFIG_SIZE = 4 + WHEEL_MAX * LABEL_LEN
WHEEL_FIRE_SIZE = 8
RESULT_TEXT_LEN = 48
ACTION_RESULT_SIZE = 4 + RESULT_TEXT_LEN
MAC_STATUS_SIZE = 16

# PSP_CTRL_* bits (pspsdk pspctrl.h). Only the ones a user-mode app can read are mappable.
BUTTONS = {
    "SELECT": 0x000001, "START": 0x000008, "UP": 0x000010, "RIGHT": 0x000020, "DOWN": 0x000040,
    "LEFT": 0x000080, "L": 0x000100, "R": 0x000200, "TRIANGLE": 0x001000, "CIRCLE": 0x002000,
    "CROSS": 0x004000, "SQUARE": 0x008000,
}

_INPUT = struct.Struct("<IBBBBII")
_FIRE = struct.Struct("<B3xI")
_RESULT_HEAD = struct.Struct("<BBH")
_STATUS = struct.Struct("<IIHBBI")


@dataclass
class InputState:
    buttons: int = 0
    lx: int = 128
    ly: int = 128
    flags: int = 0
    hover: int = NO_SLICE
    t_us: int = 0
    frame: int = 0

    def pack(self) -> bytes:
        return _INPUT.pack(self.buttons & 0xFFFFFFFF, self.lx, self.ly, self.flags, self.hover,
                           self.t_us & 0xFFFFFFFF, self.frame & 0xFFFFFFFF)

    @classmethod
    def unpack(cls, b: bytes) -> "InputState":
        if len(b) < INPUT_SIZE:
            raise ValueError(f"INPUT_STATE too short: {len(b)}")
        return cls(*_INPUT.unpack_from(b))

    @property
    def wheel_open(self) -> bool:
        return bool(self.flags & IN_F_WHEEL_OPEN)


@dataclass
class WheelConfig:
    labels: list[str] = field(default_factory=list)

    def pack(self) -> bytes:
        labels = self.labels[:WHEEL_MAX]
        out = bytearray(struct.pack("<BBH", len(labels), 1, 0))
        for i in range(WHEEL_MAX):
            raw = labels[i].encode("ascii", "replace")[: LABEL_LEN - 1] if i < len(labels) else b""
            out += raw.ljust(LABEL_LEN, b"\0")
        return bytes(out)

    @classmethod
    def unpack(cls, b: bytes) -> "WheelConfig":
        n = min(b[0], WHEEL_MAX)
        labels = [b[4 + i * LABEL_LEN: 4 + (i + 1) * LABEL_LEN].split(b"\0", 1)[0].decode(errors="replace")
                  for i in range(n)]
        return cls(labels)


@dataclass
class WheelFire:
    slice: int
    t_us: int = 0

    def pack(self) -> bytes:
        return _FIRE.pack(self.slice, self.t_us & 0xFFFFFFFF)

    @classmethod
    def unpack(cls, b: bytes) -> "WheelFire":
        return cls(*_FIRE.unpack_from(b))


@dataclass
class ActionResult:
    slice: int
    ok: bool
    text: str = ""

    def pack(self) -> bytes:
        raw = self.text.encode("ascii", "replace")[: RESULT_TEXT_LEN - 1]
        return _RESULT_HEAD.pack(self.slice & 0xFF, 1 if self.ok else 0, 0) + raw.ljust(RESULT_TEXT_LEN, b"\0")

    @classmethod
    def unpack(cls, b: bytes) -> "ActionResult":
        s, ok, _ = _RESULT_HEAD.unpack_from(b)
        return cls(s, bool(ok), b[4:4 + RESULT_TEXT_LEN].split(b"\0", 1)[0].decode(errors="replace"))


@dataclass
class MacStatus:
    rtt_us: int = 0
    events: int = 0
    input_hz: int = 0
    dry_run: bool = False
    ax_trusted: bool = False

    def pack(self) -> bytes:
        return _STATUS.pack(self.rtt_us & 0xFFFFFFFF, self.events & 0xFFFFFFFF, min(self.input_hz, 0xFFFF),
                            int(self.dry_run), int(self.ax_trusted), 0)

    @classmethod
    def unpack(cls, b: bytes) -> "MacStatus":
        r, e, hz, d, a, _ = _STATUS.unpack_from(b)
        return cls(r, e, hz, bool(d), bool(a))


assert _INPUT.size == INPUT_SIZE and _FIRE.size == WHEEL_FIRE_SIZE and _STATUS.size == MAC_STATUS_SIZE
