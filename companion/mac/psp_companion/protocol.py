"""Python mirror of companion/proto_companion.h. Keep them in sync; tests/test_golden.py checks the wire
format against the real C code in both directions."""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from enum import IntEnum

VERSION = 1
APP_ID = 4
MAX_PAYLOAD = 384

T_CONN = 0xA0
T_AGENT = 0xA1
T_ACTIVITY = 0xA2
T_ACTIONS = 0xA3
T_APPROVAL_REQ = 0xA4
T_APPROVAL_CLOSE = 0xA5
T_ACTION_ACK = 0xA6
T_ANIM = 0xA7
T_HEARTBEAT = 0xA8
T_BUTTON = 0xB0
T_ACTION = 0xB1
T_APPROVAL_RESP = 0xB2

LABEL_MAX = 24
ACTIVITY_MAX = 72
REASON_MAX = 40
TITLE_MAX = 28
DETAIL_MAX = 120
TEXT_MAX = 48


class Conn(IntEnum):
    NONE = 0
    ATTACHED = 1
    RECONNECTING = 2
    ENDED = 3


class Mode(IntEnum):
    NONE = 0
    OBSERVE = 1
    HOOKS = 2
    MANAGED = 3
    DEMO = 4


CAP_APPROVALS = 1
CAP_ACTIONS = 2
CAP_LIVE_TOOLS = 4


class Agent(IntEnum):
    OFFLINE = 0
    SLEEPING = 1
    IDLE = 2
    THINKING = 3
    EDITING = 4
    RUNNING = 5
    TESTING = 6
    APPROVAL = 7
    SUCCESS = 8
    FAILED = 9
    TALKING = 10
    WORKING = 11


class Anim(IntEnum):
    NONE = 0
    WAKE = 1
    CELEBRATE = 2
    FAIL = 3
    ALLOWED = 4
    DENIED = 5
    BOUNCE = 6


class Kind(IntEnum):
    COMMAND = 0
    FILE = 1
    PERMISSION = 2
    OTHER = 3


AF_ACTIONABLE = 1
AF_DEMO = 2


class Decision(IntEnum):
    ALLOW = 1
    DENY = 2


class Close(IntEnum):
    ALLOWED = 1
    DENIED = 2
    TIMEOUT = 3
    ELSEWHERE = 4
    DISCONNECT = 5
    FAILED = 6
    STALE = 7
    HIDDEN = 8


class Action(IntEnum):
    CONTINUE = 0
    SUMMARIZE = 1
    TESTS = 2
    ERRORS = 3
    INTERRUPT = 4
    SESSION_PREV = 0x10
    SESSION_NEXT = 0x11


ACTION_COUNT = 5


class Ack(IntEnum):
    ACCEPTED = 1
    DONE = 2
    FAILED = 3
    UNAVAILABLE = 4


BUTTON_NAMES = ["UP", "DOWN", "LEFT", "RIGHT", "CROSS", "CIRCLE", "SQUARE", "TRIANGLE", "START", "SELECT", "L", "R"]


class ProtoError(ValueError):
    pass


def _str(text: str, cap: int) -> bytes:
    raw = text.encode("ascii", "replace")[:cap]
    return bytes([len(raw)]) + raw


class _Rd:
    def __init__(self, data: bytes):
        self.d, self.o = bytes(data), 0

    def take(self, fmt: str):
        s = struct.Struct("<" + fmt)
        if self.o + s.size > len(self.d):
            raise ProtoError("truncated payload")
        v = s.unpack_from(self.d, self.o)
        self.o += s.size
        return v[0] if len(v) == 1 else v

    def str(self) -> str:
        n = self.take("B")
        if self.o + n > len(self.d):
            raise ProtoError("truncated string")
        s = self.d[self.o : self.o + n].decode("ascii", "replace")
        self.o += n
        return s


def _rd(payload: bytes) -> _Rd:
    r = _Rd(payload)
    v = r.take("B")
    if v != VERSION:
        raise ProtoError(f"unsupported companion version {v}")
    return r


# ---- Mac -> PSP encoders ----------------------------------------------------
def conn(state: int, mode: int, caps: int, index: int, count: int, label: str) -> bytes:
    return struct.pack("<BBBBBB", VERSION, state, mode, caps, index & 0xFF, count & 0xFF) + _str(label, LABEL_MAX)


def agent(state: int) -> bytes:
    return struct.pack("<BB", VERSION, state)


def activity(text: str) -> bytes:
    return bytes([VERSION]) + _str(text, ACTIVITY_MAX)


def actions(items: list[tuple[int, bool, str]]) -> bytes:
    out = bytes([VERSION, len(items)])
    for action_id, enabled, reason in items:
        out += bytes([action_id, 1 if enabled else 0]) + _str(reason, REASON_MAX)
    return out


def approval_req(req_id: int, kind: int, flags: int, timeout_s: int, pending: int, title: str, detail: str) -> bytes:
    head = struct.pack("<BIBBHB", VERSION, req_id, kind, flags, min(timeout_s, 0xFFFF), min(pending, 255))
    return head + _str(title, TITLE_MAX) + _str(detail, DETAIL_MAX)


def approval_close(req_id: int, reason: int, text: str = "") -> bytes:
    return struct.pack("<BIB", VERSION, req_id, reason) + _str(text, TEXT_MAX)


def action_ack(req: int, status: int, text: str = "") -> bytes:
    return struct.pack("<BHB", VERSION, req, status) + _str(text, TEXT_MAX)


def anim(which: int) -> bytes:
    return struct.pack("<BB", VERSION, which)


def heartbeat(boot_id: int, uptime_ms: int) -> bytes:
    return struct.pack("<BII", VERSION, boot_id & 0xFFFFFFFF, uptime_ms & 0xFFFFFFFF)


# ---- PSP -> Mac decoders ----------------------------------------------------
@dataclass
class Button:
    button: int
    down: bool

    @property
    def name(self) -> str:
        return BUTTON_NAMES[self.button] if self.button < len(BUTTON_NAMES) else f"#{self.button}"


@dataclass
class ActionMsg:
    req: int
    action: int


@dataclass
class ApprovalResp:
    req_id: int
    decision: int


@dataclass
class Heartbeat:
    boot_id: int
    uptime_ms: int


def decode_inbound(type_: int, payload: bytes):
    """Decodes a PSP->Mac companion message. Raises ProtoError on anything malformed."""
    if len(payload) > MAX_PAYLOAD:
        raise ProtoError("payload too large")
    r = _rd(payload)
    if type_ == T_BUTTON:
        b, d = r.take("BB")
        return Button(b, bool(d))
    if type_ == T_ACTION:
        req, a = r.take("HB")
        return ActionMsg(req, a)
    if type_ == T_APPROVAL_RESP:
        rid, d = r.take("IB")
        if d not in (Decision.ALLOW, Decision.DENY):
            raise ProtoError(f"bad decision {d}")
        return ApprovalResp(rid, d)
    if type_ == T_HEARTBEAT:
        boot, up = r.take("II")
        return Heartbeat(boot, up)
    raise ProtoError(f"unexpected inbound type 0x{type_:02X}")


# ---- Mac -> PSP decoders (fake PSP and tests) ---------------------------------
@dataclass
class Decoded:
    type: int
    fields: dict = field(default_factory=dict)


def decode_outbound(type_: int, payload: bytes) -> Decoded:
    r = _rd(payload)
    f: dict = {}
    if type_ == T_CONN:
        f["conn"], f["mode"], f["caps"], f["index"], f["count"] = r.take("BBBBB")
        f["label"] = r.str()
    elif type_ == T_AGENT:
        f["state"] = r.take("B")
    elif type_ == T_ACTIVITY:
        f["text"] = r.str()
    elif type_ == T_ACTIONS:
        n = r.take("B")
        f["items"] = []
        for _ in range(n):
            i, e = r.take("BB")
            f["items"].append((i, bool(e), r.str()))
    elif type_ == T_APPROVAL_REQ:
        f["id"], f["kind"], f["flags"], f["timeout_s"], f["pending"] = r.take("IBBHB")
        f["title"] = r.str()
        f["detail"] = r.str()
    elif type_ == T_APPROVAL_CLOSE:
        f["id"], f["reason"] = r.take("IB")
        f["text"] = r.str()
    elif type_ == T_ACTION_ACK:
        f["req"], f["status"] = r.take("HB")
        f["text"] = r.str()
    elif type_ == T_ANIM:
        f["anim"] = r.take("B")
    elif type_ == T_HEARTBEAT:
        f["boot_id"], f["uptime_ms"] = r.take("II")
    else:
        raise ProtoError(f"unexpected outbound type 0x{type_:02X}")
    return Decoded(type_, f)
