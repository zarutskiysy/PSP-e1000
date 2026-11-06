"""Python mirror vs C header (controller/proto_controller.h) + pack/unpack round trips."""
import pathlib
import re

import pytest

from deck import proto as C

HDR = (pathlib.Path(__file__).resolve().parents[1] / "proto_controller.h").read_text()


def c_value(name: str) -> int:
    m = re.search(rf"\b{name}\s*=\s*(0x[0-9A-Fa-f]+|\d+)", HDR) or \
        re.search(rf"#define\s+{name}\s+\(?([^\n/]+?)\)?\s*(?:/\*|$)", HDR, re.M)
    assert m, name
    expr = m.group(1).replace("u", "")
    for k in ("CTRL_WHEEL_MAX", "CTRL_LABEL_LEN", "CTRL_RESULT_TEXT_LEN"):
        if k in expr:
            expr = expr.replace(k, str(c_value(k)))
    return int(eval(expr, {}, {}))  # header-controlled arithmetic only


@pytest.mark.parametrize("c,py", [
    ("CTRL_T_INPUT_STATE", C.T_INPUT_STATE), ("CTRL_T_WHEEL_CONFIG", C.T_WHEEL_CONFIG),
    ("CTRL_T_WHEEL_FIRE", C.T_WHEEL_FIRE), ("CTRL_T_ACTION_RESULT", C.T_ACTION_RESULT),
    ("CTRL_T_CONFIG_REQ", C.T_CONFIG_REQ), ("CTRL_T_MAC_STATUS", C.T_MAC_STATUS),
    ("CTRL_INPUT_SIZE", C.INPUT_SIZE), ("CTRL_IN_F_WHEEL_OPEN", C.IN_F_WHEEL_OPEN),
    ("CTRL_NO_SLICE", C.NO_SLICE), ("CTRL_WHEEL_MAX", C.WHEEL_MAX), ("CTRL_LABEL_LEN", C.LABEL_LEN),
    ("CTRL_WHEEL_CONFIG_SIZE", C.WHEEL_CONFIG_SIZE), ("CTRL_WHEEL_FIRE_SIZE", C.WHEEL_FIRE_SIZE),
    ("CTRL_RESULT_TEXT_LEN", C.RESULT_TEXT_LEN), ("CTRL_ACTION_RESULT_SIZE", C.ACTION_RESULT_SIZE),
    ("CTRL_MAC_STATUS_SIZE", C.MAC_STATUS_SIZE), ("CTRL_APP_ID", C.APP_ID),
])
def test_constants_match_c_header(c, py):
    assert c_value(c) == py


def test_types_in_track_range():
    for t in C.TYPE_NAMES:
        assert 0x10 <= t <= 0x3F


def test_input_roundtrip_and_layout():
    s = C.InputState(0x4101, 255, 0, C.IN_F_WHEEL_OPEN, 3, 0xFFFFFFFF, 7)
    b = s.pack()
    assert len(b) == C.INPUT_SIZE
    assert b[:4] == bytes([0x01, 0x41, 0, 0]) and b[4] == 255 and b[5] == 0 and b[6] == 1 and b[7] == 3
    assert C.InputState.unpack(b) == s and C.InputState.unpack(b).wheel_open


def test_wheel_config_roundtrip_and_truncation():
    labels = ["A", "Play/Pause", "x" * 40] + [f"s{i}" for i in range(10)]
    b = C.WheelConfig(labels).pack()
    assert len(b) == C.WHEEL_CONFIG_SIZE and b[0] == 8
    out = C.WheelConfig.unpack(b).labels
    assert out[:2] == ["A", "Play/Pause"] and out[2] == "x" * 23 and len(out) == 8


def test_result_status_fire_roundtrip():
    r = C.ActionResult(5, False, "error: " + "y" * 100)
    b = r.pack()
    assert len(b) == C.ACTION_RESULT_SIZE
    u = C.ActionResult.unpack(b)
    assert u.slice == 5 and not u.ok and len(u.text) == 47
    s = C.MacStatus(1234, 99, 60, True, False)
    assert len(s.pack()) == C.MAC_STATUS_SIZE and C.MacStatus.unpack(s.pack()) == s
    f = C.WheelFire(2, 42)
    assert len(f.pack()) == C.WHEEL_FIRE_SIZE and C.WheelFire.unpack(f.pack()) == f


def test_buttons_match_pspsdk_values():
    # pspsdk pspctrl.h
    assert C.BUTTONS["SELECT"] == 0x1 and C.BUTTONS["START"] == 0x8 and C.BUTTONS["L"] == 0x100
    assert C.BUTTONS["CROSS"] == 0x4000 and C.BUTTONS["SQUARE"] == 0x8000 and C.BUTTONS["TRIANGLE"] == 0x1000
