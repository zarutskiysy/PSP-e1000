"""Python mirror (game/mac/bw_proto.py) vs the C header (game/proto_game.h): sizes, golden bytes, PRNG."""
import pathlib
import re
import subprocess

import bw_proto as G

ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_sizes_match_c_header():
    h = (ROOT / "game/proto_game.h").read_text()
    sizes = dict(re.findall(r"BW_SZ_(\w+) = (\d+)", h))
    py = {"GAME_START": G.S_GAME_START, "SUB_STATE": G.S_SUB_STATE, "ECHO_HDR": G.S_ECHO_HDR,
          "CONTACT": G.S_CONTACT, "HACK_REQ": G.S_HACK_REQ, "EVENT": G.S_EVENT, "PING_CMD": G.S_PING_CMD,
          "HACK_RESULT": G.S_HACK_RESULT, "MARK": G.S_MARK, "PILOT": G.S_PILOT, "READY": G.S_READY}
    for k, s in py.items():
        assert int(sizes[k]) == s.size, k


def test_type_ids_match_c_header_and_track_range():
    h = (ROOT / "game/proto_game.h").read_text()
    c_types = {k: int(v, 16) for k, v in re.findall(r"BW_T_(\w+) = (0x[0-9A-F]+)", h)}
    for name, val in c_types.items():
        assert getattr(G, "T_" + name) == val
        assert 0x70 <= val <= 0x9F  # track C range (psp_link.h)


def test_golden_bytes_shared_with_c_tests():
    # same vectors as game/psp/host/test_console.c::test_golden
    assert G.pack_sub_state(0x1234, -5, 700, 0x4000, 30, 100, 90, 7, 9, 1) == bytes(
        [0x34, 0x12, 0xFB, 0xFF, 0xBC, 0x02, 0x00, 0x40, 30, 100, 90, 7, 9, 1])
    assert G.pack_hack_req(2, 0, 1, 0xDEADBEEF, 200) == bytes([2, 0, 1, 0, 0xEF, 0xBE, 0xAD, 0xDE, 0xC8, 0x00])
    e = G.pack_echo(7, 1, [G.Contact(100, 300, G.K_MINE, 9), G.Contact(65535, 1, G.K_EXIT, 255)])
    assert len(e) == 16
    pid, mode, cs = G.unpack_echo(e)
    assert (pid, mode, cs[1].bearing, cs[0].range) == (7, 1, 65535, 300)
    assert len(G.pack_echo(1, 1, [G.Contact(0, 0, 1, 1)] * 40)) == 4 + 6 * G.ECHO_MAX


def test_rng_and_puzzle_mirror():
    v, s = G.rng_next(1)
    assert v == 270369
    v, s = G.rng_next(s)
    assert v == 67634689
    host = ROOT / "game/psp/host/psp_host"
    subprocess.run(["make", "-s", "-C", str(host.parent), "psp_host"], check=True)
    for seed, diff in ((3735928559, 1), (1, 0), (0xC0FFEE, 3), (0, 2)):
        out = subprocess.run([str(host), "--hackgen", str(seed), str(diff)], capture_output=True, text=True,
                             check=True).stdout.split("\n")
        t, st = G.hack_generate(seed, diff)
        assert out[0].split() == [str(x) for x in t]
        assert out[1].split() == [str(x) for x in st]


def test_bearing_roundtrip():
    for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0), (3, -4)):
        b = G.bearing_of(dx, dy)
        x, y = G.bearing_vec(b)
        n = (dx * dx + dy * dy) ** 0.5
        assert abs(x - dx / n) < 1e-3 and abs(y - dy / n) < 1e-3
    assert G.bearing_of(0, -1) == 0 and G.bearing_of(1, 0) == 16384
