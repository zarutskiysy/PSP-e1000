import math

import pytest

from deck import config as cfgmod
from deck.mapper import DT_MAX, Mapper, nub_vector
from deck.proto import BUTTONS, IN_F_WHEEL_OPEN, InputState

US = 1_000_000


def cfg(**mouse):
    return cfgmod.from_dict({
        "mouse": {"deadzone": 0.15, "max_speed": 1000, "exponent": 2.0, **mouse},
        "keys": {"repeat_delay_ms": 400, "repeat_interval_ms": 100},
        "buttons": {"L": "mouse:left", "R": "mouse:right", "CROSS": "key:return", "UP": "key:up",
                    "START": "media:playpause", "TRIANGLE": "mode:scroll", "SQUARE": "shell:echo hi"},
        "wheel": [{"label": "Shot", "action": "key:cmd+shift+3"}, {"label": "MC", "action": "mission_control"},
                  {"label": "Run", "action": "shell:true"}, {"label": "Click", "action": "mouse:left"}],
    })


def feed(m, frames, dt_us=16_667, t0=0):
    out = []
    for i, (b, lx, ly, *rest) in enumerate(frames):
        flags = rest[0] if rest else 0
        out += m.on_input(InputState(b, lx, ly, flags, 0xFF, t0 + i * dt_us, i))
    return out


def moves(evs):
    return sum(e["dx"] for e in evs if e.kind == "mouse_move"), sum(e["dy"] for e in evs if e.kind == "mouse_move")


# -- nub curve ---------------------------------------------------------------
def test_deadzone_center_and_small_drift():
    assert nub_vector(128, 128, 0.15, 2) == (0.0, 0.0)
    assert nub_vector(140, 120, 0.15, 2) == (0.0, 0.0)  # |v| ~ 0.11 < deadzone
    vx, vy = nub_vector(150, 128, 0.15, 2)
    assert vx > 0 and vy == 0


def test_full_deflection_is_unit_and_direction():
    for lx, ly, sx, sy in [(255, 128, 1, 0), (0, 128, -1, 0), (128, 0, 0, -1), (128, 255, 0, 1)]:
        vx, vy = nub_vector(lx, ly, 0.15, 2)
        assert math.isclose(math.hypot(vx, vy), 1.0, rel_tol=1e-6)
        assert (round(vx), round(vy)) == (sx, sy)


def test_curve_is_monotonic_and_accelerating():
    speeds = [math.hypot(*nub_vector(128 + d, 128, 0.15, 2.2)) for d in range(0, 128)]
    assert all(b >= a for a, b in zip(speeds, speeds[1:]))
    # power curve: half deflection past the deadzone gives (0.5)^2.2 ~ 0.22 of full speed
    mid = 0.15 + 0.5 * 0.85
    v = math.hypot(*nub_vector(128 + round(mid * 127), 128, 0.15, 2.2))
    assert 0.17 < v < 0.27


def test_invert_y():
    assert nub_vector(128, 0, 0.1, 1, invert_y=True)[1] > 0


# -- mouse ---------------------------------------------------------------------
def test_mouse_distance_is_time_based():
    m = Mapper(cfg())
    evs = feed(m, [(0, 255, 128)] * 61)  # first frame counts DT_FIRST, so 61 frames = 61/60 s at full speed -> ~1017 px
    dx, dy = moves(evs)
    assert 1000 <= dx <= 1017 and dy == 0


def test_rate_independence():
    a, b = Mapper(cfg()), Mapper(cfg())
    da = moves(feed(a, [(0, 255, 128)] * 61, dt_us=16_667))[0]
    db = moves(feed(b, [(0, 255, 128)] * 126, dt_us=8_000))[0]  # 125 Hz for the same second
    assert abs(da - db) <= 20


def test_subpixel_accumulation_slow_nub():
    m = Mapper(cfg())
    evs = feed(m, [(0, 128 + 30, 128)] * 300)
    per_frame_px = nub_vector(158, 128, 0.15, 2)[0] * 1000 / 60
    assert per_frame_px < 1  # each frame alone would round to 0
    assert moves(evs)[0] > 0.8 * per_frame_px * 299


def test_dt_clamped_after_gap_and_wraparound():
    m = Mapper(cfg())
    m.on_input(InputState(0, 255, 128, 0, 0xFF, 0, 0))
    evs = m.on_input(InputState(0, 255, 128, 0, 0xFF, 5 * US, 1))  # 5 s gap
    assert moves(evs)[0] <= 1000 * DT_MAX + 1
    m2 = Mapper(cfg())
    m2.on_input(InputState(0, 255, 128, 0, 0xFF, 0xFFFFFFFF - 8000, 0))
    evs = m2.on_input(InputState(0, 255, 128, 0, 0xFF, 8667, 1))  # wrapped, dt = 16.667 ms
    assert 15 <= moves(evs)[0] <= 18


def test_wheel_open_freezes_cursor():
    m = Mapper(cfg())
    evs = feed(m, [(BUTTONS["SELECT"], 255, 128, IN_F_WHEEL_OPEN)] * 30)
    assert moves(evs) == (0, 0)


# -- buttons -------------------------------------------------------------------
def test_click_and_drag():
    m = Mapper(cfg())
    L = BUTTONS["L"]
    evs = feed(m, [(0, 128, 128), (L, 128, 128), (L, 128, 0), (L, 128, 0), (0, 128, 128)])
    kinds = [(e.kind, e.args.get("button"), e.args.get("down")) for e in evs if e.kind != "mouse_move"]
    assert kinds == [("mouse_button", "left", True), ("mouse_button", "left", False)]
    i_down = next(i for i, e in enumerate(evs) if e.kind == "mouse_button")
    assert any(e.kind == "mouse_move" and e["dy"] < 0 for e in evs[i_down:])


def test_key_press_release_and_repeat():
    m = Mapper(cfg())
    U = BUTTONS["UP"]
    evs = feed(m, [(U, 128, 128)] * 61 + [(0, 128, 128)])  # held 1 s
    keys = [e for e in evs if e.kind == "key"]
    assert keys[0]["down"] and not keys[0]["repeat"] and keys[0]["keycode"] == 0x7E
    assert not keys[-1]["down"]
    reps = [k for k in keys if k["repeat"]]
    # delay 400 ms then every 100 ms until 1.0 s -> 6 or 7 repeats
    assert 5 <= len(reps) <= 7


def test_one_shot_actions_fire_once_on_press():
    m = Mapper(cfg())
    S = BUTTONS["START"]
    evs = feed(m, [(S, 128, 128)] * 40 + [(0, 128, 128)])
    assert [e.kind for e in evs] == ["media"] and evs[0]["key"] == "playpause"
    evs = feed(Mapper(cfg()), [(BUTTONS["SQUARE"], 128, 128)])
    assert evs[0].kind == "shell" and evs[0]["cmd"] == "echo hi"


def test_scroll_mode():
    m = Mapper(cfg(scroll_speed=60))
    T = BUTTONS["TRIANGLE"]
    evs = feed(m, [(T, 128, 0)] * 61)  # nub up for 1 s -> ~+60 lines, no cursor motion
    assert moves(evs) == (0, 0)
    total = sum(e["dy"] for e in evs if e.kind == "scroll")
    assert 58 <= total <= 61
    evs = feed(m, [(0, 128, 0)] * 5, t0=2 * US)
    assert moves(evs)[1] < 0  # back to cursor mode


def test_release_all_unsticks_buttons():
    m = Mapper(cfg())
    feed(m, [(BUTTONS["L"] | BUTTONS["CROSS"], 128, 128)])
    evs = m.release_all()
    assert {(e.kind, e.args.get("down")) for e in evs} == {("mouse_button", False), ("key", False)}
    assert m.release_all() == []


# -- wheel ---------------------------------------------------------------------
def test_wheel_events():
    m = Mapper(cfg())
    label, evs = m.wheel_events(0)
    assert label == "Shot"
    assert [(e.kind, e["down"], e["mods"]) for e in evs] == [("key", True, ["cmd", "shift"]),
                                                            ("key", False, ["cmd", "shift"])]
    assert [e.kind for e in m.wheel_events(1)[1]] == ["mission_control"]
    assert m.wheel_events(2)[1][0]["cmd"] == "true"
    assert [e["down"] for e in m.wheel_events(3)[1]] == [True, False]
    with pytest.raises(IndexError):
        m.wheel_events(4)
