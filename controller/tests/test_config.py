import pytest

from deck import config as cfgmod
from deck.config import ConfigError, parse_action


def test_default_config_loads():
    cfg = cfgmod.load()
    assert cfg.buttons["L"].kind == "mouse" and cfg.buttons["L"].arg == "left"
    assert cfg.buttons["TRIANGLE"].kind == "mode"
    assert 1 <= len(cfg.wheel) <= 8
    kinds = {w.action.kind for w in cfg.wheel}
    assert {"mission_control", "media", "key", "shell"} <= kinds


@pytest.mark.parametrize("spec,kind,code,mods", [
    ("key:cmd+shift+3", "key", 0x14, ("cmd", "shift")),
    ("key:Return", "key", 0x24, ()),
    ("key:ctrl+up", "key", 0x7E, ("ctrl",)),
    ("key:option+command+escape", "key", 0x35, ("alt", "cmd")),
])
def test_parse_key(spec, kind, code, mods):
    a = parse_action(spec)
    assert (a.kind, a.keycode, a.mods) == (kind, code, mods)


@pytest.mark.parametrize("spec", [
    "key:cmd+nosuchkey", "key:hyper+a", "mouse:fourth", "media:eject", "shell:", "teleport:home", "",
    "mode:zoom",
])
def test_bad_actions(spec):
    with pytest.raises(ConfigError):
        parse_action(spec)


def test_select_is_reserved_and_unknown_buttons_rejected():
    with pytest.raises(ConfigError, match="SELECT"):
        cfgmod.from_dict({"buttons": {"SELECT": "key:a"}})
    with pytest.raises(ConfigError, match="unknown PSP button"):
        cfgmod.from_dict({"buttons": {"HOME": "key:a"}})


def test_wheel_limits():
    with pytest.raises(ConfigError, match="at most 8"):
        cfgmod.from_dict({"wheel": [{"label": str(i), "action": "none"} for i in range(9)]})
    with pytest.raises(ConfigError, match="label"):
        cfgmod.from_dict({"wheel": [{"label": "x" * 30, "action": "none"}]})
    with pytest.raises(ConfigError):
        cfgmod.from_dict({"wheel": [{"label": "no action"}]})


def test_numeric_validation_and_unknown_keys():
    with pytest.raises(ConfigError):
        cfgmod.from_dict({"mouse": {"deadzone": 2}})
    with pytest.raises(ConfigError):
        cfgmod.from_dict({"mouse": {"max_speed": "fast"}})
    with pytest.raises(ConfigError, match="unknown top-level"):
        cfgmod.from_dict({"mice": {}})


def test_toml_file(tmp_path):
    p = tmp_path / "d.toml"
    p.write_text('[mouse]\nmax_speed = 500\n[buttons]\nCROSS = "key:a"\n[[wheel]]\nlabel = "Hi"\naction = "shell:echo hi"\n')
    cfg = cfgmod.load(p)
    assert cfg.mouse.max_speed == 500 and cfg.buttons["CROSS"].keycode == 0x00 and cfg.labels == ["Hi"]
    p.write_text("[mouse\n")
    with pytest.raises(ConfigError):
        cfgmod.load(p)


def test_modifier_masks_match_quartz():
    Q = pytest.importorskip("Quartz")
    from deck.keys import MOD_FLAGS

    assert MOD_FLAGS["cmd"] == Q.kCGEventFlagMaskCommand
    assert MOD_FLAGS["shift"] == Q.kCGEventFlagMaskShift
    assert MOD_FLAGS["ctrl"] == Q.kCGEventFlagMaskControl
    assert MOD_FLAGS["alt"] == Q.kCGEventFlagMaskAlternate
    assert MOD_FLAGS["fn"] == Q.kCGEventFlagMaskSecondaryFn
