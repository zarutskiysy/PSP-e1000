"""proto_screen.h and proto_screen.py must agree on every constant."""
import pathlib
import re

import proto_screen as S

HDR = pathlib.Path(__file__).resolve().parents[1] / "proto_screen.h"


def c_constants():
    txt = HDR.read_text()
    out = {}
    for name, val in re.findall(r"#define\s+(SCR_\w+)\s+([0-9xA-Fa-fu]+)\b", txt):
        out[name] = int(val.rstrip("u"), 0)
    for name, val in re.findall(r"\b(SCR_\w+)\s*=\s*(0x[0-9A-Fa-f]+|\d+)", txt):
        out[name] = int(val, 0)
    return out


def test_constants_match():
    c = c_constants()
    assert len(c) >= 15
    for name, val in c.items():
        assert getattr(S, name) == val, name
    for name in ("SCR_TILES_X", "SCR_TILES_Y", "SCR_NTILES", "SCR_TILE_BYTES", "SCR_MAX_BODY"):
        assert hasattr(S, name)


def test_types_in_track_range():
    for name in dir(S):
        if name.startswith("SCR_T_"):
            assert 0x40 <= getattr(S, name) <= 0x6F, name
