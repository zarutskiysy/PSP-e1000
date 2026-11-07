"""fake_psp_screen.py — fake_psp plugin that plays the second-screen PSP app on the Mac.

It decodes SCR_CHUNKs with the *same C code the PSP runs* (screen/codec/scr_codec.c compiled to
libscrcodec.dylib, loaded with ctypes; `make -C screen/codec lib` is run automatically if needed),
presents into a 512-stride "framebuffer" exactly like screen/psp/main.c, sends SCR_ACKs, and answers
the throughput probe.

    python tools/fake_psp.py --app 2 --plugin tools/fake_psp_screen.py -- --dump-final /tmp/psp.png
Plugin args (after `--`):
    --dump-final PNG      rewrite PNG after every presented frame (last one wins)
    --dump-dir DIR        write DIR/frame_NNNNN.png for every presented frame
    --decoder c|py        C decoder via ctypes (default) or the Python reference decoder
    --ack-delay-ms N      pretend decoding takes N ms (tests flow control)
    --drop-chunk N        drop the N-th received chunk once (tests NEED_KEY recovery)
    --max-unread N        count link frames > N bytes (what a 4 KiB HOSTFS ring would drop)
    --stats-file F        write "chunk_acks overflows frames_shown" after every frame
Chunks with PSP_LINK_F_ACK_REQ get an SCR_CHUNK_ACK, like the PSP app (HOSTFS stop-and-wait).
"""
from __future__ import annotations

import argparse
import ctypes
import pathlib
import struct
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "screen" / "mac"))
sys.path.insert(0, str(ROOT / "common" / "python"))

import numpy as np  # noqa: E402

import proto_screen as S  # noqa: E402
from pspmac import protocol as P  # noqa: E402

CODEC_DIR = ROOT / "screen" / "codec"
FB_STRIDE = 512


class CDecoder(ctypes.Structure):
    """Mirror of scr_decoder_t (screen/codec/scr_codec.h); size checked against scr_dec_struct_size()."""
    _fields_ = [
        ("canvas", ctypes.c_void_p), ("stride", ctypes.c_uint32), ("dirty", ctypes.c_uint8 * S.SCR_NTILES),
        ("frame_id", ctypes.c_uint32), ("next_chunk", ctypes.c_uint16), ("in_frame", ctypes.c_int),
        ("synced", ctypes.c_int), ("need_key", ctypes.c_int),
        ("frames_done", ctypes.c_uint32), ("chunks", ctypes.c_uint32), ("tiles", ctypes.c_uint32),
        ("solid_tiles", ctypes.c_uint32), ("errors", ctypes.c_uint32), ("gaps", ctypes.c_uint32),
        ("last_frame_id", ctypes.c_uint32),
    ]


def load_codec() -> ctypes.CDLL:
    ext = "dylib" if sys.platform == "darwin" else "so"
    lib_path = CODEC_DIR / f"libscrcodec.{ext}"
    srcs = [CODEC_DIR / "scr_codec.c", CODEC_DIR / "scr_codec.h", ROOT / "screen" / "proto_screen.h"]
    if not lib_path.exists() or any(s.stat().st_mtime > lib_path.stat().st_mtime for s in srcs):
        subprocess.run(["make", "-s", "-C", str(CODEC_DIR), "lib"], check=True)
    lib = ctypes.CDLL(str(lib_path))
    lib.scr_dec_struct_size.restype = ctypes.c_uint32
    lib.scr_dec_init.argtypes = [ctypes.POINTER(CDecoder), ctypes.c_void_p, ctypes.c_uint32]
    lib.scr_dec_chunk.argtypes = [ctypes.POINTER(CDecoder), ctypes.c_char_p, ctypes.c_uint32, ctypes.c_void_p,
                                  ctypes.c_uint32]
    lib.scr_dec_chunk.restype = ctypes.c_int
    lib.scr_present.argtypes = [ctypes.POINTER(CDecoder), ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int]
    lib.scr_present.restype = ctypes.c_int
    lib.scr_lz4_decompress.argtypes = [ctypes.c_char_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32]
    lib.scr_lz4_decompress.restype = ctypes.c_int
    assert lib.scr_dec_struct_size() == ctypes.sizeof(CDecoder), "scr_decoder_t layout changed: update CDecoder"
    return lib


class CScreen:
    """PSP-equivalent screen state: canvas (480 stride) + framebuffer (512 stride), C decoder."""

    def __init__(self):
        self.lib = load_codec()
        self.canvas = np.zeros((S.SCR_H, S.SCR_W), np.uint16)
        self.fb = np.zeros((S.SCR_H, FB_STRIDE), np.uint16)
        self.scratch = ctypes.create_string_buffer(S.SCR_MAX_BODY)
        self.d = CDecoder()
        self.lib.scr_dec_init(ctypes.byref(self.d), self.canvas.ctypes.data, S.SCR_W)

    def chunk(self, payload: bytes) -> int:
        return self.lib.scr_dec_chunk(ctypes.byref(self.d), payload, len(payload), self.scratch, S.SCR_MAX_BODY)

    def present(self) -> int:
        return self.lib.scr_present(ctypes.byref(self.d), self.fb.ctypes.data, FB_STRIDE, 0)

    @property
    def visible(self) -> np.ndarray:
        return self.fb[:, : S.SCR_W]


class PyScreen:
    def __init__(self):
        from screencodec import PyDecoder
        self.dec = PyDecoder()
        self.errors = 0

    def chunk(self, payload: bytes) -> int:
        try:
            return 1 if self.dec.chunk(payload) else 0
        except Exception:  # noqa: BLE001
            self.errors += 1
            return -4

    def present(self) -> int:
        return S.SCR_NTILES

    @property
    def visible(self) -> np.ndarray:
        return self.dec.canvas


class Plugin:
    def __init__(self, args):
        ap = argparse.ArgumentParser(prog="fake_psp_screen")
        ap.add_argument("--dump-final")
        ap.add_argument("--dump-dir")
        ap.add_argument("--decoder", default="c", choices=["c", "py"])
        ap.add_argument("--ack-delay-ms", type=float, default=0.0)
        ap.add_argument("--drop-chunk", type=int, default=-1)
        ap.add_argument("--max-unread", type=int, default=0,
                        help="flag link frames bigger than this (HOSTFS 4 KiB ring check); count is in --stats-file")
        ap.add_argument("--stats-file", help="write 'chunk_acks overflows frames' here on every frame")
        self.a = ap.parse_args(args)
        self.scr = CScreen() if self.a.decoder == "c" else PyScreen()
        self.frames_shown = 0
        self.rx_bytes = 0
        self.dec_us = 0
        self.chunks_seen = 0
        self.fps_t0, self.fps_n, self.fps_x10 = time.monotonic(), 0, 0
        self.probe = dict(bytes=0, frames=0, t0=None, t1=None)
        self.chunk_acks = self.overflows = 0

    def on_connect(self, link):
        link.name = "fake_psp_screen"
        link.app = P.APP_SCREEN
        # The PSP accepts SCR_MAX_PAYLOAD-sized payloads; advertise the same.
        link.parser.max_payload = S.SCR_MAX_PAYLOAD + 64

    def _dump(self):
        from screencodec import psp565_to_rgb
        from PIL import Image
        img = Image.fromarray(psp565_to_rgb(self.scr.visible))
        if self.a.dump_final:
            img.save(self.a.dump_final)
        if self.a.dump_dir:
            pathlib.Path(self.a.dump_dir).mkdir(parents=True, exist_ok=True)
            img.save(pathlib.Path(self.a.dump_dir) / f"frame_{self.frames_shown:05d}.png")

    def on_frame(self, link, f):
        self.rx_bytes += len(f.payload) + P.OVERHEAD
        if f.type == S.SCR_T_CHUNK:
            self.chunks_seen += 1
            if self.chunks_seen == self.a.drop_chunk:
                return
            if (f.flags & P.F_ACK_REQ) and not (f.payload[9] & S.SCR_CF_LAST):
                link.send(S.SCR_T_CHUNK_ACK, S.CHUNK_ACK.pack(*struct.unpack_from("<IH", f.payload)))
                self.chunk_acks += 1
            if self.a.max_unread and len(f.payload) + P.OVERHEAD > self.a.max_unread:
                self.overflows += 1  # a real HOSTFS ring would have dropped bytes here
            t0 = time.perf_counter()
            r = self.scr.chunk(f.payload)
            self.dec_us += int((time.perf_counter() - t0) * 1e6)
            if r == 1 or (r < 0 and f.payload[9] & S.SCR_CF_LAST):
                t1 = time.perf_counter()
                self.scr.present()
                present_us = int((time.perf_counter() - t1) * 1e6)
                self.frames_shown += 1
                self._dump()
                if self.a.stats_file:
                    pathlib.Path(self.a.stats_file).write_text(f"{self.chunk_acks} {self.overflows} {self.frames_shown}")
                self.fps_n += 1
                now = time.monotonic()
                if now - self.fps_t0 >= 1.0:
                    self.fps_x10 = int(self.fps_n * 10 / (now - self.fps_t0))
                    self.fps_t0, self.fps_n = now, 0
                if self.a.ack_delay_ms:
                    time.sleep(self.a.ack_delay_ms / 1000)
                d = getattr(self.scr, "d", None)
                need_key = bool(d.need_key) if d is not None else False
                errors = d.errors if d is not None else self.scr.errors
                frame_id = struct.unpack_from("<I", f.payload)[0]
                ack = S.Ack(frame_id, self.dec_us, present_us, self.frames_shown, self.rx_bytes, 0, self.fps_x10,
                            S.SCR_ACKF_NEED_KEY if need_key else 0, errors)
                link.send(S.SCR_T_ACK, ack.pack())
                self.dec_us = 0
        elif f.type == S.SCR_T_PROBE_RESET:
            self.probe = dict(bytes=0, frames=0, t0=None, t1=None)
        elif f.type == S.SCR_T_PROBE_DATA:
            now = time.perf_counter()
            if self.probe["t0"] is None:
                self.probe["t0"] = now
            self.probe["t1"] = now
            self.probe["bytes"] += len(f.payload) + P.OVERHEAD
            self.probe["frames"] += 1
        elif f.type == S.SCR_T_PROBE_END:
            (tag,) = struct.unpack_from("<I", f.payload)
            p = self.probe
            us = int(((p["t1"] or 0) - (p["t0"] or 0)) * 1e6)
            link.send(S.SCR_T_PROBE_RESULT,
                      S.ProbeResult(tag, p["bytes"], p["frames"], us, link.parser.crc_errors).pack())
