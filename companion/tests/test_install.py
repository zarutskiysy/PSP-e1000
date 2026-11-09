"""Installer behaviour, entirely inside temporary directories."""
import json
import stat

import pytest

from psp_companion import install as inst


@pytest.fixture
def homes(tmp_path, monkeypatch):
    monkeypatch.setenv("PSP_COMPANION_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("PSP_COMPANION_SKILLS", str(tmp_path / "skills"))
    monkeypatch.setenv("PSP_COMPANION_BIN", str(tmp_path / "bin"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    (tmp_path / "codex").mkdir()
    return tmp_path


def test_install_is_idempotent(homes):
    a = inst.install()
    b = inst.install()
    assert a == b
    assert (homes / "skills/psp-connect/SKILL.md").exists() and (homes / "skills/psp-disconnect/SKILL.md").exists()
    assert (homes / "bin/psp-companion").is_symlink()
    cfg = json.loads((homes / "state/config.json").read_text())
    assert cfg["transport"] == "usb" and cfg["root"]
    assert stat.S_IMODE((homes / "state").stat().st_mode) == 0o700


def test_install_will_not_replace_a_foreign_skill(homes):
    (homes / "skills/psp-connect").mkdir(parents=True)
    (homes / "skills/psp-connect/SKILL.md").write_text("mine")
    with pytest.raises(RuntimeError):
        inst.install()
    assert (homes / "skills/psp-connect/SKILL.md").read_text() == "mine"


def test_uninstall_removes_only_what_it_installed(homes):
    inst.install()
    (homes / "skills/other").mkdir()
    assert len(inst.uninstall()) == 3
    assert (homes / "skills/other").exists() and not (homes / "skills/psp-connect").exists()


def test_hooks_are_merged_and_removed_cleanly(homes):
    original = {"description": "mine", "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "/my/policy.sh"}]}]}}
    path = homes / "codex/hooks.json"
    path.write_text(json.dumps(original))
    assert not inst.hooks_installed()
    inst.hooks_install()
    inst.hooks_install()  # twice must not duplicate
    data = json.loads(path.read_text())
    assert inst.hooks_installed() and data["description"] == "mine"
    pre = data["hooks"]["PreToolUse"]
    assert len(pre) == 2 and pre[0]["hooks"][0]["command"] == "/my/policy.sh"
    assert set(inst.HOOK_EVENTS) <= set(data["hooks"])
    assert data["hooks"]["PermissionRequest"][0]["hooks"][0]["timeout"] == 125
    assert (homes / "codex/hooks.json.psp-backup").exists()
    assert inst.hooks_uninstall() is True
    assert json.loads(path.read_text()) == original
    assert inst.hooks_uninstall() is False


def test_install_does_not_write_hooks(homes):
    inst.install()
    assert not (homes / "codex/hooks.json").exists()
