"""Second-screen codec, Mac side: RGB -> PSP 565, 16x16 dirty tiles vs the previous frame,
solid-tile shortcut, optional LZ4 block per chunk, chunking into <= 64 KiB SCR_CHUNK payloads.
Also a pure-Python reference decoder (the PSP uses screen/codec/scr_codec.c)."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import lz4.block
import numpy as np

from proto_screen import (CHUNK_HDR, SCR_CF_KEY, SCR_CF_LAST, SCR_CHUNK_HDR, SCR_CODEC_LZ4, SCR_CODEC_RAW, SCR_H,
                          SCR_MAX_BODY, SCR_MAX_PAYLOAD, SCR_NTILES, SCR_TAG_INDEX_MASK, SCR_TAG_SOLID, SCR_TILE,
                          SCR_TILE_BYTES, SCR_TILES_X, SCR_TILES_Y, SCR_W)


def rgb_to_psp565(rgb: np.ndarray) -> np.ndarray:
    """HxWx3 (or x4, extra channel ignored) uint8 RGB -> HxW uint16 in PSP order: B<<11 | G<<5 | R."""
    r = rgb[..., 0].astype(np.uint16) >> 3
    g = rgb[..., 1].astype(np.uint16) >> 2
    b = rgb[..., 2].astype(np.uint16) >> 3
    return (b << 11) | (g << 5) | r


def bgra_to_psp565(bgra: np.ndarray) -> np.ndarray:
    """HxWx4 uint8 BGRA (ScreenCaptureKit / mss order) -> PSP 565."""
    b = bgra[..., 0].astype(np.uint16) >> 3
    g = bgra[..., 1].astype(np.uint16) >> 2
    r = bgra[..., 2].astype(np.uint16) >> 3
    return (b << 11) | (g << 5) | r


def psp565_to_rgb(v: np.ndarray) -> np.ndarray:
    """PSP 565 -> HxWx3 uint8 RGB (bit replication, like the PSP display controller)."""
    v = v.astype(np.uint16)
    r = (v & 0x1F).astype(np.uint8)
    g = ((v >> 5) & 0x3F).astype(np.uint8)
    b = ((v >> 11) & 0x1F).astype(np.uint8)
    return np.stack([(r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)], axis=-1)


def to_tiles(frame: np.ndarray) -> np.ndarray:
    """(272, 480) -> (510, 256) contiguous, tile-major (index = ty*30+tx), rows inside a tile."""
    t = frame.reshape(SCR_TILES_Y, SCR_TILE, SCR_TILES_X, SCR_TILE).transpose(0, 2, 1, 3)
    return np.ascontiguousarray(t).reshape(SCR_NTILES, SCR_TILE * SCR_TILE)


@dataclass
class FrameStats:
    frame_id: int = 0
    key: bool = False
    dirty: int = 0
    solid: int = 0
    raw_bytes: int = 0      # body bytes before LZ4
    wire_bytes: int = 0     # SCR_CHUNK payload bytes actually sent (headers included)
    chunks: int = 0
    lz4_chunks: int = 0
    encode_ms: float = 0.0


@dataclass
class Encoder:
    lz4: str = "auto"            # "off" | "on" | "auto" (use LZ4 when it saves >= 10%)
    max_payload: int = SCR_MAX_PAYLOAD
    prev: np.ndarray | None = None
    frame_id: int = 0
    last: FrameStats = field(default_factory=FrameStats)

    def encode(self, frame: np.ndarray, key: bool = False) -> list[bytes]:
        """frame: (272, 480) uint16 PSP 565. Returns SCR_CHUNK payloads (empty list if nothing changed)."""
        t0 = time.perf_counter()
        assert frame.shape == (SCR_H, SCR_W) and frame.dtype == np.uint16
        tiles = to_tiles(frame)
        if self.prev is None or key:
            key = True
            dirty = np.arange(SCR_NTILES)
        else:
            dirty = np.nonzero((tiles != self.prev).any(axis=1))[0]
        st = FrameStats(frame_id=self.frame_id, key=key, dirty=len(dirty))
        self.prev = tiles
        if len(dirty) == 0:
            st.encode_ms = (time.perf_counter() - t0) * 1e3
            self.last = st
            return []
        sub = tiles[dirty]
        solid = (sub == sub[:, :1]).all(axis=1)
        st.solid = int(solid.sum())
        tags = dirty.astype("<u2") | np.where(solid, SCR_TAG_SOLID, 0).astype("<u2")
        tile_le = sub.astype("<u2")
        # record sizes: 4 (solid) or 514
        sizes = np.where(solid, 4, 2 + SCR_TILE_BYTES)
        max_body = min(SCR_MAX_BODY, self.max_payload - SCR_CHUNK_HDR)
        bodies: list[tuple[int, bytes]] = []
        recs: list[bytes] = []
        cur = 0
        for i in range(len(dirty)):
            sz = int(sizes[i])
            if cur + sz > max_body and recs:
                bodies.append((len(recs), b"".join(recs)))
                recs, cur = [], 0
            if solid[i]:
                recs.append(tags[i].tobytes() + tile_le[i, 0].tobytes())
            else:
                recs.append(tags[i].tobytes() + tile_le[i].tobytes())
            cur += sz
        bodies.append((len(recs), b"".join(recs)))
        out = []
        cflags_base = SCR_CF_KEY if key else 0
        for ci, (n, body) in enumerate(bodies):
            codec, data = SCR_CODEC_RAW, body
            if self.lz4 != "off":
                c = lz4.block.compress(body, store_size=False)
                if self.lz4 == "on" or len(c) <= 0.9 * len(body):
                    codec, data = SCR_CODEC_LZ4, c
                    st.lz4_chunks += 1
            cf = cflags_base | (SCR_CF_LAST if ci == len(bodies) - 1 else 0)
            out.append(CHUNK_HDR.pack(self.frame_id & 0xFFFFFFFF, ci, n, codec, cf, 0, len(body)) + data)
            st.raw_bytes += len(body)
        st.chunks = len(out)
        st.wire_bytes = sum(len(p) for p in out)
        self.frame_id = (self.frame_id + 1) & 0xFFFFFFFF
        st.encode_ms = (time.perf_counter() - t0) * 1e3
        self.last = st
        return out


class PyDecoder:
    """Reference decoder (independent of scr_codec.c): applies SCR_CHUNK payloads to a canvas."""

    def __init__(self):
        self.canvas = np.zeros((SCR_H, SCR_W), np.uint16)
        self.frames_done = 0

    def chunk(self, p: bytes) -> bool:
        fid, idx, n, codec, cf, _, blen = CHUNK_HDR.unpack_from(p)
        body = p[SCR_CHUNK_HDR:]
        if codec == SCR_CODEC_LZ4:
            body = lz4.block.decompress(body, uncompressed_size=blen)
        assert len(body) == blen
        off = 0
        for _ in range(n):
            tag = int.from_bytes(body[off:off + 2], "little")
            off += 2
            i = tag & SCR_TAG_INDEX_MASK
            ty, tx = divmod(i, SCR_TILES_X)
            view = self.canvas[ty * SCR_TILE:(ty + 1) * SCR_TILE, tx * SCR_TILE:(tx + 1) * SCR_TILE]
            if tag & SCR_TAG_SOLID:
                view[:] = int.from_bytes(body[off:off + 2], "little")
                off += 2
            else:
                view[:] = np.frombuffer(body, "<u2", 256, off).reshape(SCR_TILE, SCR_TILE)
                off += SCR_TILE_BYTES
        assert off == blen
        if cf & SCR_CF_LAST:
            self.frames_done += 1
            return True
        return False
