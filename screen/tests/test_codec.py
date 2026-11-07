"""Codec tests: Python encoder -> C decoder (the PSP code via ctypes) and -> Python decoder, pixel-exact."""
import ctypes
import os
import pathlib
import subprocess

import lz4.block
import numpy as np
import pytest

import proto_screen as S
from fake_psp_screen import CScreen, load_codec
from screencodec import Encoder, PyDecoder, bgra_to_psp565, psp565_to_rgb, rgb_to_psp565
from sources import make_source

ROOT = pathlib.Path(__file__).resolve().parents[2]
DESKTOP = "image:" + str(ROOT / "screen/tests/data/desktop.png")


def test_c_unit_tests():
    subprocess.run(["make", "-s", "-C", str(ROOT / "screen/codec"), "test"], check=True)


def test_pixel_order():
    rgb = np.array([[[255, 0, 0], [0, 255, 0], [0, 0, 255], [255, 255, 255]]], np.uint8)
    v = rgb_to_psp565(rgb)
    assert v.tolist() == [[0x001F, 0x07E0, 0xF800, 0xFFFF]]  # PSP 565: red in the LOW bits
    bgra = np.array([[[0, 0, 255, 255], [255, 0, 0, 255]]], np.uint8)
    assert bgra_to_psp565(bgra).tolist() == [[0x001F, 0xF800]]
    assert np.array_equal(rgb_to_psp565(psp565_to_rgb(v)), v)


@pytest.mark.parametrize("spec", ["test-pattern", "video-ish", DESKTOP])
@pytest.mark.parametrize("lz4mode", ["off", "on", "auto"])
def test_roundtrip_c_and_py(spec, lz4mode):
    src = make_source(spec)
    enc = Encoder(lz4=lz4mode)
    c, py = CScreen(), PyDecoder()
    for n in range(12):
        fr = src.frame(n * 3)
        chunks = enc.encode(fr, key=(n == 5))
        for p in chunks:
            assert len(p) <= S.SCR_MAX_PAYLOAD
            r = c.chunk(p)
            assert r >= 0
            py.chunk(p)
        if chunks:
            c.present()
        assert np.array_equal(c.visible, fr), (spec, n)
        assert np.array_equal(py.canvas, fr)
    assert c.d.errors == 0 and c.d.gaps == 0 and not c.d.need_key


def test_unchanged_frame_sends_nothing_and_key_resends_all():
    src = make_source(DESKTOP)
    enc = Encoder(lz4="off")
    assert len(enc.encode(src.frame(0))) > 0
    assert enc.last.dirty == S.SCR_NTILES and enc.last.key
    assert enc.encode(src.frame(1)) == []
    enc.encode(src.frame(2), key=True)
    assert enc.last.dirty == S.SCR_NTILES


def test_small_payload_chunking():
    src = make_source("video-ish")
    enc = Encoder(lz4="off", max_payload=4096)
    c = CScreen()
    chunks = enc.encode(src.frame(0))
    assert len(chunks) > 60 and all(len(p) <= 4096 for p in chunks)
    for p in chunks:
        c.chunk(p)
    c.present()
    assert np.array_equal(c.visible, src.frame(0))


def test_lost_chunk_requests_key_and_recovers():
    src = make_source("video-ish")
    enc = Encoder(lz4="off")
    c = CScreen()
    for p in enc.encode(src.frame(0)):
        c.chunk(p)
    assert not c.d.need_key
    chunks = enc.encode(src.frame(1))
    assert len(chunks) >= 2
    for p in chunks[1:]:  # drop chunk 0
        c.chunk(p)
    assert c.d.need_key
    for p in enc.encode(src.frame(2), key=True):
        c.chunk(p)
    c.present()
    assert not c.d.need_key and np.array_equal(c.visible, src.frame(2))


def test_c_lz4_matches_reference():
    lib = load_codec()
    rng = np.random.default_rng(1)
    for size in (1, 15, 16, 300, 4096, 65520):
        for kind in ("random", "runs", "text"):
            if kind == "random":
                data = rng.integers(0, 256, size, np.uint8).tobytes()
            elif kind == "runs":
                data = np.repeat(rng.integers(0, 4, size // 7 + 1, np.uint8), 7)[:size].tobytes()
            else:
                data = (b"hello psp second screen " * (size // 24 + 1))[:size]
            comp = lz4.block.compress(data, store_size=False)
            out = ctypes.create_string_buffer(size)
            n = lib.scr_lz4_decompress(comp, len(comp), out, size)
            assert n == size and out.raw == data, (size, kind)
            assert lib.scr_lz4_decompress(comp, len(comp), out, max(0, size - 1)) == -1 or size == 0


def test_corrupt_chunks_never_crash():
    enc = Encoder(lz4="on")
    src = make_source("test-pattern")
    c = CScreen()
    good = enc.encode(src.frame(0))
    rng = np.random.default_rng(7)
    for _ in range(300):
        p = bytearray(good[int(rng.integers(len(good)))])
        for _ in range(int(rng.integers(1, 20))):
            p[int(rng.integers(len(p)))] = int(rng.integers(256))
        c.chunk(bytes(p[: int(rng.integers(1, len(p) + 1))]))
    assert c.d.errors > 0


@pytest.mark.skipif(not os.path.exists(os.path.expanduser("~/pspdev/bin/psp-gcc")), reason="no PSP toolchain")
def test_eboot_builds():
    env = dict(os.environ, PATH=os.path.expanduser("~/pspdev/bin") + ":" + os.environ["PATH"])
    subprocess.run(["make", "-s", "-C", str(ROOT / "screen/psp")], check=True, env=env)
    assert (ROOT / "screen/psp/EBOOT.PBP").stat().st_size > 10000


def test_lz4_on_never_exceeds_max_payload():
    """Incompressible content with --lz4 on must fall back to raw so payloads stay <= 64 KiB."""
    rng = np.random.default_rng(3)
    noise = rng.integers(0, 65536, (S.SCR_H, S.SCR_W), dtype=np.uint16)
    enc = Encoder(lz4="on")
    chunks = enc.encode(noise)
    assert max(len(p) for p in chunks) <= S.SCR_MAX_PAYLOAD
    c = CScreen()
    for p in chunks:
        assert c.chunk(p) >= 0
    c.present()
    assert np.array_equal(c.visible, noise)


def test_hostfs_chunk_size():
    enc = Encoder(lz4="auto", max_payload=3000)
    chunks = enc.encode(make_source("video-ish").frame(0))
    assert chunks and max(len(p) for p in chunks) <= 3000
