"""End-to-end: tools/fake_psp.py + tools/fake_psp_controller.py (mock PSP over TCP) <-> psp_deck --dry-run."""
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]


def start_fake(tmp_path, *plugin_args):
    p = subprocess.Popen(
        [sys.executable, str(ROOT / "tools" / "fake_psp.py"), "--port", "0", "--print-port", "--quiet", "--once",
         "--plugin", str(ROOT / "tools" / "fake_psp_controller.py"), "--", *plugin_args],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    line = p.stdout.readline()
    assert line.startswith("PORT "), line
    return p, int(line.split()[1])


def run_deck(port, *args, timeout=30):
    return subprocess.run(
        [sys.executable, str(ROOT / "controller" / "mac" / "psp_deck.py"), "-t", f"tcp:127.0.0.1:{port}",
         "--dry-run", "--once", *args], capture_output=True, text=True, timeout=timeout)


def test_demo_scenario_end_to_end(tmp_path):
    report, events, summary = tmp_path / "report.json", tmp_path / "ev.jsonl", tmp_path / "sum.json"
    fake, port = start_fake(tmp_path, "--scenario", "demo", "--report", str(report))
    try:
        r = run_deck(port, "--events-log", str(events), "--summary", str(summary), "--stats-every", "1")
    finally:
        fake.wait(timeout=10)
    assert r.returncode == 0, r.stderr
    assert "session ended: bye" in r.stderr
    rep = json.loads(report.read_text())
    s = json.loads(summary.read_text())
    evs = [json.loads(l) for l in events.read_text().splitlines()]

    # the PSP got the wheel labels from deck.toml and a result for the slice it fired
    assert rep["labels"] == ["Mission Ctrl", "Play/Pause", "Screenshot", "Next track", "Cmd+Tab", "Downloads"]
    assert len(rep["results"]) == 1 and rep["results"][0]["slice"] == 2 and rep["results"][0]["ok"]
    assert rep["results"][0]["text"].startswith("Screenshot: dry-run: would run screencap")
    assert rep["status"]["dry_run"] is True

    # mouse moved right, then dragged up while L was held
    mv = [e for e in evs if e["ev"] == "mouse_move"]
    assert sum(e["dx"] for e in mv) > 300
    kinds = [(e["ev"], e.get("button") or e.get("key"), e.get("down")) for e in evs if e["ev"] != "mouse_move"]
    assert ("mouse_button", "left", True) in kinds and ("mouse_button", "right", True) in kinds
    assert ("key", "return", True) in kinds and ("key", "return", False) in kinds
    assert any(e["ev"] == "key" and e["key"] == "up" and e["repeat"] for e in evs)
    assert any(e["ev"] == "scroll" and e["dy"] < 0 for e in evs)
    shot = [e for e in evs if e["ev"] == "shell"]
    assert len(shot) == 1 and shot[0]["cmd"].startswith("screencapture -x ~/Desktop/psp-")
    # every press was released
    assert kinds.count(("mouse_button", "left", True)) == kinds.count(("mouse_button", "left", False))

    assert s["wheel_fires"] == 1 and s["errors"] == 0 and s["inputs"] > 100
    assert s["rtt_samples"] >= 1 and s["rtt_ms_median"] < 50


def test_bad_config_fails(tmp_path):
    bad = tmp_path / "bad.toml"
    bad.write_text('[buttons]\nSELECT = "key:a"\n')
    r = subprocess.run([sys.executable, str(ROOT / "controller" / "mac" / "psp_deck.py"), "-c", str(bad),
                        "--check-config"], capture_output=True, text=True)
    assert r.returncode == 2 and "SELECT" in r.stderr


def test_idle_scenario_duration(tmp_path):
    fake, port = start_fake(tmp_path, "--scenario", "idle")
    try:
        r = run_deck(port, "--duration", "2.5", "--summary", str(tmp_path / "s.json"), "--stats-every", "1")
    finally:
        fake.wait(timeout=10)
    assert r.returncode == 0, r.stderr
    s = json.loads((tmp_path / "s.json").read_text())
    assert s["events"] == 0  # centred nub, no buttons -> nothing posted
    assert s["inputs"] > 60 and s["input_hz_median"] > 30
