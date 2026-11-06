import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "common" / "python"))

from pspmac import protocol as P  # noqa: E402


def test_crc_check_value():
    assert P.crc16(b"123456789") == 0x29B1


def test_roundtrip_bytewise():
    fr = P.encode(0x42, b"hello", seq=0x1234, flags=1)
    p = P.Parser()
    got = []
    for b in fr:
        got += p.feed(bytes([b]))
    assert got == [P.Frame(0x42, 1, 0x1234, b"hello")]


def test_junk_crc_oversize():
    bad = bytearray(P.encode(2, b"bad", 2))
    bad[-1] ^= 0xFF
    stream = b"\x00PP" + P.encode(1, b"a", 1) + bytes(bad) + P.encode(3, b"x" * 19, 3) + P.encode(4, b"", 4)
    p = P.Parser(max_payload=16)
    frames = p.feed(stream)
    assert [f.type for f in frames] == [1, 4]
    assert p.crc_errors == 1 and p.oversize_frames == 1


def test_hello_pack():
    h = P.Hello(1, P.ROLE_PSP, 3, 4096, "psp")
    assert P.Hello.unpack(h.pack()) == h


def test_golden_matches_c():
    """C (common/psp/test) and Python must produce byte-identical frames."""
    subprocess.run(["make", "-s", "-C", str(ROOT / "common/psp/test"), "test_link.bin"], check=True)
    out = subprocess.run([str(ROOT / "common/psp/test/test_link.bin"), "--golden"], check=True,
                         capture_output=True, text=True).stdout.split()
    py = [
        P.encode(P.T_HELLO, b"\x01\x00\x01\x00\x00\x10\x00\x00psp", 0).hex(),
        P.encode(P.T_PING, b"\x01\x02\x03\x04", 0xBEEF).hex(),
        P.encode(P.T_BYE, b"", 65535, P.F_LAST).hex(),
    ]
    assert out == py
