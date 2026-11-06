"""QuartzBackend builds real CGEvents with pyobjc, but CGEventPost is intercepted: nothing reaches
the window server, so this runs without Accessibility and without moving the user's cursor."""
import pytest

Q = pytest.importorskip("Quartz")

from deck.backend import DryRunBackend, QuartzBackend  # noqa: E402
from deck.mapper import Event  # noqa: E402


@pytest.fixture
def qb():
    b = QuartzBackend()
    b.captured = []

    def fake_post(ev):
        b.captured.append(ev)
        b.events += 1

    b._post = fake_post
    return b


def test_key_combo_event(qb):
    qb.post(Event("key", {"key": "cmd+shift+3", "keycode": 0x14, "mods": ["cmd", "shift"], "down": True,
                          "repeat": False}))
    e = qb.captured[0]
    assert Q.CGEventGetType(e) == Q.kCGEventKeyDown
    assert Q.CGEventGetIntegerValueField(e, Q.kCGKeyboardEventKeycode) == 0x14
    f = Q.CGEventGetFlags(e)
    assert f & Q.kCGEventFlagMaskCommand and f & Q.kCGEventFlagMaskShift


def test_key_repeat_flag(qb):
    qb.post(Event("key", {"key": "up", "keycode": 0x7E, "mods": [], "down": True, "repeat": True}))
    assert Q.CGEventGetIntegerValueField(qb.captured[0], Q.kCGKeyboardEventAutorepeat) == 1


def test_move_then_drag(qb):
    qb.post(Event("mouse_move", {"dx": 5, "dy": -3}))
    assert Q.CGEventGetType(qb.captured[-1]) == Q.kCGEventMouseMoved
    assert Q.CGEventGetIntegerValueField(qb.captured[-1], Q.kCGMouseEventDeltaX) == 5
    qb.post(Event("mouse_button", {"button": "left", "down": True}))
    assert Q.CGEventGetType(qb.captured[-1]) == Q.kCGEventLeftMouseDown
    qb.post(Event("mouse_move", {"dx": 1, "dy": 1}))
    assert Q.CGEventGetType(qb.captured[-1]) == Q.kCGEventLeftMouseDragged
    qb.post(Event("mouse_button", {"button": "left", "down": False}))
    assert Q.CGEventGetType(qb.captured[-1]) == Q.kCGEventLeftMouseUp


def test_double_click_state(qb):
    for d in (True, False, True, False):
        qb.post(Event("mouse_button", {"button": "left", "down": d}))
    assert Q.CGEventGetIntegerValueField(qb.captured[2], Q.kCGMouseEventClickState) == 2


def test_media_key_is_system_defined(qb):
    qb.post(Event("media", {"key": "playpause"}))
    assert len(qb.captured) == 2  # down + up
    assert all(Q.CGEventGetType(e) == 14 for e in qb.captured)  # NSSystemDefined


def test_scroll(qb):
    qb.post(Event("scroll", {"dy": -2}))
    assert Q.CGEventGetType(qb.captured[0]) == Q.kCGEventScrollWheel


def test_close_releases_held_button(qb):
    qb.post(Event("mouse_button", {"button": "right", "down": True}))
    qb.close()
    assert Q.CGEventGetType(qb.captured[-1]) == Q.kCGEventRightMouseUp


def test_dry_run_never_executes_shell(tmp_path):
    marker = tmp_path / "ran"
    b = DryRunBackend()
    txt = b.post(Event("shell", {"cmd": f"touch {marker}"}))
    assert "would run" in txt and not marker.exists() and b.log[0]["ev"] == "shell"
