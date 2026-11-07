"""Python mirror of screen/proto_screen.h (feat/second-screen, message types 0x40-0x6F).
screen/tests/test_proto_sync.py parses the C header and checks every constant below."""
from __future__ import annotations

import struct
from dataclasses import dataclass

SCR_W, SCR_H, SCR_TILE = 480, 272, 16
SCR_TILES_X, SCR_TILES_Y = SCR_W // SCR_TILE, SCR_H // SCR_TILE  # 30, 17
SCR_NTILES = SCR_TILES_X * SCR_TILES_Y  # 510
SCR_TILE_BYTES = SCR_TILE * SCR_TILE * 2  # 512

SCR_MAX_PAYLOAD = 65536
SCR_CHUNK_HDR = 16
SCR_MAX_BODY = SCR_MAX_PAYLOAD - SCR_CHUNK_HDR

SCR_T_CHUNK = 0x40
SCR_T_ACK = 0x41
SCR_T_CHUNK_ACK = 0x42
SCR_T_PROBE_DATA = 0x50
SCR_T_PROBE_END = 0x51
SCR_T_PROBE_RESULT = 0x52
SCR_T_PROBE_RESET = 0x53

SCR_CODEC_RAW = 0
SCR_CODEC_LZ4 = 1
SCR_CF_KEY = 0x01
SCR_CF_LAST = 0x02
SCR_TAG_SOLID = 0x8000
SCR_TAG_INDEX_MASK = 0x0FFF
SCR_ACKF_NEED_KEY = 0x0001
SCR_ACK_SIZE = 32
SCR_PROBE_RESULT_SIZE = 20
SCR_CHUNK_ACK_SIZE = 6

CHUNK_HDR = struct.Struct("<IHHBBHI")  # frame_id, chunk_idx, n_items, codec, cflags, reserved, body_len
ACK = struct.Struct("<IIIIIIHHI")
PROBE_RESULT = struct.Struct("<IIIII")
CHUNK_ACK = struct.Struct("<IH")  # frame_id, chunk_idx
assert CHUNK_ACK.size == SCR_CHUNK_ACK_SIZE and CHUNK_HDR.size == SCR_CHUNK_HDR and ACK.size == SCR_ACK_SIZE and PROBE_RESULT.size == SCR_PROBE_RESULT_SIZE


@dataclass
class Ack:
    frame_id: int
    decode_us: int
    present_us: int
    frames_shown: int
    rx_bytes: int
    buttons: int
    fps_x10: int
    flags: int
    decode_errors: int

    def pack(self) -> bytes:
        return ACK.pack(self.frame_id, self.decode_us, self.present_us, self.frames_shown, self.rx_bytes & 0xFFFFFFFF,
                        self.buttons, self.fps_x10, self.flags, self.decode_errors)

    @classmethod
    def unpack(cls, b: bytes) -> "Ack":
        return cls(*ACK.unpack_from(b))


@dataclass
class ProbeResult:
    tag: int
    bytes: int
    frames: int
    us: int
    crc_errors: int

    def pack(self) -> bytes:
        return PROBE_RESULT.pack(self.tag, self.bytes & 0xFFFFFFFF, self.frames, self.us, self.crc_errors)

    @classmethod
    def unpack(cls, b: bytes) -> "ProbeResult":
        return cls(*PROBE_RESULT.unpack_from(b))
