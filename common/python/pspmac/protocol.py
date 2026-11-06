"""Python mirror of common/protocol/psp_link.h. Keep in sync with the C header.

Frame (little-endian): 'P' 'L' type:u8 flags:u8 seq:u16 len:u32 payload[len] crc16:u16
CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF) over header+payload.
"""
from __future__ import annotations

import binascii
import struct
from dataclasses import dataclass

MAGIC = b"PL"
HEADER = struct.Struct("<2sBBHI")
HEADER_SIZE = HEADER.size  # 10
CRC_SIZE = 2
OVERHEAD = HEADER_SIZE + CRC_SIZE
VERSION = 1

USB_VID = 0x054C
USB_PID = 0x01CB
USB_EP_IN = 0x81  # PSP -> Mac
USB_EP_OUT = 0x02  # Mac -> PSP

# common message types (0x00-0x0F); track ranges: 0x10-0x3F controller, 0x40-0x6F screen,
# 0x70-0x9F game, 0xA0-0xEF future, 0xF0-0xFF testing
T_HELLO = 0x01
T_HELLO_ACK = 0x02
T_PING = 0x03
T_PONG = 0x04
T_LOG = 0x05
T_BYE = 0x06
T_ERROR = 0x07
T_TEST = 0xF0

F_NONE = 0x00
F_ACK_REQ = 0x01
F_LAST = 0x02

ROLE_MAC = 0
ROLE_PSP = 1

APP_GENERIC, APP_CONTROLLER, APP_SCREEN, APP_GAME = 0, 1, 2, 3

TYPE_NAMES = {
    T_HELLO: "HELLO", T_HELLO_ACK: "HELLO_ACK", T_PING: "PING", T_PONG: "PONG",
    T_LOG: "LOG", T_BYE: "BYE", T_ERROR: "ERROR", T_TEST: "TEST",
}


def crc16(data: bytes | bytearray | memoryview, crc: int = 0xFFFF) -> int:
    """CRC-16/CCITT-FALSE; binascii.crc_hqx is poly 0x1021, non-reflected, caller-supplied init."""
    return binascii.crc_hqx(data, crc)


@dataclass
class Frame:
    type: int
    flags: int
    seq: int
    payload: bytes

    @property
    def name(self) -> str:
        return TYPE_NAMES.get(self.type, f"0x{self.type:02X}")


def encode(type_: int, payload: bytes = b"", seq: int = 0, flags: int = 0) -> bytes:
    head = HEADER.pack(MAGIC, type_ & 0xFF, flags & 0xFF, seq & 0xFFFF, len(payload))
    body = head + bytes(payload)
    return body + struct.pack("<H", crc16(body))


@dataclass
class Hello:
    version: int = VERSION
    role: int = ROLE_MAC
    app: int = APP_GENERIC
    max_payload: int = 1 << 20
    name: str = ""

    _S = struct.Struct("<HBBI")

    def pack(self) -> bytes:
        return self._S.pack(self.version, self.role, self.app, self.max_payload) + self.name.encode()[:32]

    @classmethod
    def unpack(cls, b: bytes) -> "Hello":
        v, r, a, m = cls._S.unpack_from(b)
        return cls(v, r, a, m, bytes(b[8:]).decode(errors="replace"))


class Parser:
    """Streaming parser; mirrors psp_link_parser_t. feed() returns complete, CRC-valid frames."""

    def __init__(self, max_payload: int = 1 << 20):
        self.max_payload = max_payload
        self.buf = bytearray()
        self.frames_ok = 0
        self.crc_errors = 0
        self.oversize_frames = 0
        self.junk_bytes = 0

    def feed(self, data: bytes) -> list[Frame]:
        self.buf += data
        out: list[Frame] = []
        while True:
            i = self.buf.find(MAGIC)
            if i < 0:
                # keep a trailing 'P' that may start a magic
                keep = 1 if self.buf.endswith(MAGIC[:1]) else 0
                self.junk_bytes += len(self.buf) - keep
                del self.buf[: len(self.buf) - keep]
                return out
            if i:
                self.junk_bytes += i
                del self.buf[:i]
            if len(self.buf) < HEADER_SIZE:
                return out
            _, t, fl, seq, ln = HEADER.unpack_from(self.buf)
            total = HEADER_SIZE + ln + CRC_SIZE
            if len(self.buf) < total:
                if ln > self.max_payload and len(self.buf) >= HEADER_SIZE:
                    # wait for the whole oversize frame to skip it, like the C parser does
                    pass
                return out
            body = bytes(self.buf[: HEADER_SIZE + ln])
            (got,) = struct.unpack_from("<H", self.buf, HEADER_SIZE + ln)
            del self.buf[:total]
            if ln > self.max_payload:
                self.oversize_frames += 1
                continue
            if crc16(body) != got:
                self.crc_errors += 1
                continue
            self.frames_ok += 1
            out.append(Frame(t, fl, seq, body[HEADER_SIZE:]))
