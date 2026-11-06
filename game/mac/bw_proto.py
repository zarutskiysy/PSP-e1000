"""Python mirror of game/proto_game.h (Blackwater Ping messages, track range 0x70-0x9F).

Fixed-size little-endian payloads on top of the shared framed protocol (pspmac.protocol).
Keep in sync with the C header; game/tests/test_proto.py checks golden bytes shared with
game/psp/host/test_console.c.
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field

APP_ID = 3
PROTO_VERSION = 1

# Mac -> PSP
T_GAME_START = 0x70
T_SUB_STATE = 0x71
T_ECHO = 0x72
T_HACK_REQ = 0x73
T_EVENT = 0x74
# PSP -> Mac
T_PING_CMD = 0x80
T_HACK_RESULT = 0x81
T_MARK = 0x82
T_PILOT = 0x83
T_READY = 0x84

NAMES = {
    T_GAME_START: "GAME_START", T_SUB_STATE: "SUB_STATE", T_ECHO: "ECHO", T_HACK_REQ: "HACK_REQ",
    T_EVENT: "EVENT", T_PING_CMD: "PING_CMD", T_HACK_RESULT: "HACK_RESULT", T_MARK: "MARK",
    T_PILOT: "PILOT", T_READY: "READY",
}

ECHO_MAX = 24
MODE_COOP, MODE_SOLO = 0, 1
PING_PASSIVE, PING_ACTIVE = 0, 1
K_ROCK, K_MINE, K_CREATURE, K_GATE, K_EXIT, K_UNKNOWN = range(6)
EV_DAMAGE, EV_CREATURE_NEAR, EV_GATE_OPEN, EV_WIN, EV_LOSE, EV_BATTERY_LOW, EV_HACK_FAIL, EV_MARKED = range(1, 9)
SF_AT_GATE, SF_HACKING, SF_HUNTED, SF_RUNNING = 1, 2, 4, 8
B_UP, B_DOWN, B_LEFT, B_RIGHT = 1, 2, 4, 8
B_CROSS, B_CIRCLE, B_SQUARE, B_TRIANGLE = 16, 32, 64, 128
B_START, B_SELECT, B_L, B_R = 256, 512, 1024, 2048

S_GAME_START = struct.Struct("<BBIH")             # 8
S_SUB_STATE = struct.Struct("<HhhHBBBBBB")        # 14
S_ECHO_HDR = struct.Struct("<BBBx")               # 4
S_CONTACT = struct.Struct("<HHBB")                # 6
S_HACK_REQ = struct.Struct("<BBBxIH")             # 10
S_EVENT = struct.Struct("<BxH")                   # 4
S_PING_CMD = struct.Struct("<BBHH")               # 6
S_HACK_RESULT = struct.Struct("<BBH")             # 4
S_MARK = struct.Struct("<BBBx")                   # 4
S_PILOT = struct.Struct("<bbH")                   # 4
S_READY = struct.Struct("<BxH")                   # 4


def pack_game_start(level: int, mode: int, seed: int, max_range: int) -> bytes:
    return S_GAME_START.pack(level, mode, seed & 0xFFFFFFFF, max_range)


def pack_sub_state(tick, x, y, heading, speed, hull, battery, noise, flags, gates_open) -> bytes:
    return S_SUB_STATE.pack(tick & 0xFFFF, clamp_i16(x), clamp_i16(y), heading & 0xFFFF, clamp_u8(speed),
                            clamp_u8(hull), clamp_u8(battery), clamp_u8(noise), flags & 0xFF, gates_open & 0xFF)


@dataclass
class Contact:
    bearing: int
    range: int
    kind: int
    strength: int


def pack_echo(ping_id: int, mode: int, contacts: list[Contact]) -> bytes:
    cs = contacts[:ECHO_MAX]
    return S_ECHO_HDR.pack(ping_id & 0xFF, mode, len(cs)) + b"".join(
        S_CONTACT.pack(c.bearing & 0xFFFF, min(c.range, 0xFFFF), c.kind, clamp_u8(c.strength)) for c in cs)


def unpack_echo(b: bytes) -> tuple[int, int, list[Contact]]:
    pid, mode, n = S_ECHO_HDR.unpack_from(b)
    n = min(n, ECHO_MAX)
    return pid, mode, [Contact(*S_CONTACT.unpack_from(b, 4 + 6 * i)) for i in range(n)]


def pack_hack_req(gate_id: int, puzzle: int, difficulty: int, seed: int, time_limit_ds: int) -> bytes:
    return S_HACK_REQ.pack(gate_id, puzzle, difficulty, seed & 0xFFFFFFFF, time_limit_ds)


def pack_event(code: int, arg: int = 0) -> bytes:
    return S_EVENT.pack(code, arg & 0xFFFF)


def pack_ping_cmd(ping_id: int, mode: int, bearing: int = 0, width: int = 0xFFFF) -> bytes:
    return S_PING_CMD.pack(ping_id & 0xFF, mode, bearing, width)


def pack_hack_result(gate_id: int, ok: int, elapsed_ds: int) -> bytes:
    return S_HACK_RESULT.pack(gate_id, 1 if ok else 0, min(elapsed_ds, 0xFFFF))


def pack_mark(ping_id: int, index: int, tag: int) -> bytes:
    return S_MARK.pack(ping_id, index, tag)


def pack_pilot(ax: int, ay: int, buttons: int) -> bytes:
    return S_PILOT.pack(max(-127, min(127, ax)), max(-127, min(127, ay)), buttons & 0xFFFF)


def pack_ready(want: int = 1) -> bytes:
    return S_READY.pack(want, PROTO_VERSION)


def clamp_u8(v) -> int:
    return max(0, min(255, int(v)))


def clamp_i16(v) -> int:
    return max(-32768, min(32767, int(v)))


def bearing_of(dx: float, dy: float) -> int:
    """World vector (x right, y down) -> u16 bearing, clockwise from north (-y)."""
    a = math.atan2(dx, -dy)
    if a < 0:
        a += 2 * math.pi
    return int(a * 65536 / (2 * math.pi)) & 0xFFFF


def bearing_vec(b: int) -> tuple[float, float]:
    a = b * 2 * math.pi / 65536
    return math.sin(a), -math.cos(a)


def rng_next(s: int) -> tuple[int, int]:
    """xorshift32, mirror of bw_rng_next(): returns (value, new_state)."""
    x = s or 0x9E3779B9
    x ^= (x << 13) & 0xFFFFFFFF
    x ^= x >> 17
    x ^= (x << 5) & 0xFFFFFFFF
    return x, x


def hack_generate(seed: int, difficulty: int) -> tuple[list[int], list[int]]:
    """Mirror of bw_hack_generate(): (target, start) values 0..7."""
    n = min(3 + difficulty, 6)
    s = seed & 0xFFFFFFFF
    target, start = [], []
    for _ in range(n):
        v, s = rng_next(s)
        t = v % 8
        v, s = rng_next(s)
        target.append(t)
        start.append((t + 1 + v % 7) % 8)
    return target, start
