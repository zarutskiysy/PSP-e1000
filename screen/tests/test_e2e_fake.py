"""End to end on the Mac: psp_screen.py (real sender) -> TCP -> tools/fake_psp.py + fake_psp_screen.py
(the PSP's C decoder). The PNG the fake PSP shows must equal the last source frame, pixel for pixel."""
import pathlib
import subprocess
import sys

import numpy as np
import pytest
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parents[2]
PY = sys.executable
DESKTOP = "image:" + str(ROOT / "screen/tests/data/desktop.png")


def start_fake(tmp_path, *plugin_args):
    p = subprocess.Popen([PY, str(ROOT / "tools/fake_psp.py"), "--port", "0", "--print-port", "--once", "--quiet",
                          "--app", "2", "--plugin", str(ROOT / "tools/fake_psp_screen.py"), "--", *plugin_args],
                         stdout=subprocess.PIPE, text=True, cwd=ROOT)
    line = p.stdout.readline()
    assert line.startswith("PORT "), line
    return p, int(line.split()[1])


def send(port, *args, timeout=120):
    r = subprocess.run([PY, str(ROOT / "screen/mac/psp_screen.py"), "--transport", f"tcp:127.0.0.1:{port}", *args],
                       capture_output=True, text=True, cwd=ROOT, timeout=timeout)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


@pytest.mark.parametrize("spec", ["test-pattern", "video-ish", DESKTOP])
@pytest.mark.parametrize("decoder", ["c", "py"])
def test_pixel_exact(tmp_path, spec, decoder):
    got, want = tmp_path / "psp.png", tmp_path / "src.png"
    fake, port = start_fake(tmp_path, "--dump-final", str(got), "--decoder", decoder)
    send(port, "--source", spec, "--fps", "0", "--frames", "45", "--save-last", str(want))
    fake.wait(timeout=30)
    assert np.array_equal(np.asarray(Image.open(got)), np.asarray(Image.open(want)))


def test_lost_chunk_recovers_via_keyframe(tmp_path):
    got, want = tmp_path / "psp.png", tmp_path / "src.png"
    fake, port = start_fake(tmp_path, "--dump-final", str(got), "--drop-chunk", "8")
    send(port, "--source", "video-ish", "--fps", "0", "--frames", "40", "--lz4", "off", "--key-interval", "0",
         "--save-last", str(want))
    fake.wait(timeout=30)
    assert np.array_equal(np.asarray(Image.open(got)), np.asarray(Image.open(want)))


def test_flow_control_window(tmp_path):
    """A slow PSP (50 ms per frame) must throttle the sender to ~window/latency, not lose frames."""
    got = tmp_path / "psp.png"
    fake, port = start_fake(tmp_path, "--dump-final", str(got), "--ack-delay-ms", "50")
    out = send(port, "--source", "test-pattern", "--fps", "0", "--frames", "40", "--window", "1",
               "--stats-interval", "0.5")
    fake.wait(timeout=30)
    fps = [float(line.split()[2]) for line in out.splitlines() if line.startswith("[stats]")]
    assert fps and max(fps) < 25, out  # 1 frame in flight, 50 ms each -> <= 20 fps
    assert "no ACK" not in out


def test_probe(tmp_path):
    fake, port = start_fake(tmp_path)
    r = subprocess.run([PY, str(ROOT / "screen/mac/psp_screen.py"), "probe", "--transport", f"tcp:127.0.0.1:{port}",
                        "--sizes", "16,64,256", "--mb", "2"], capture_output=True, text=True, cwd=ROOT, timeout=120)
    subprocess.run([PY, "-c", "import socket;s=socket.create_connection(('127.0.0.1',%d))" % port],
                   capture_output=True)
    fake.kill()
    assert r.returncode == 0, r.stdout + r.stderr
    rows = [line for line in r.stdout.splitlines() if line.startswith("| ") and "KiB |" in line]
    assert len(rows) == 3, r.stdout


def test_record_stream(tmp_path):
    """record:FILE writes exactly the bytes the PSP replay io plays back; decode the file offline."""
    sys.path.insert(0, str(ROOT / "common/python"))
    sys.path.insert(0, str(ROOT / "screen/mac"))
    from pspmac import protocol as P
    import proto_screen as S
    from fake_psp_screen import CScreen
    from sources import make_source
    f = tmp_path / "stream.bin"
    r = subprocess.run([PY, str(ROOT / "screen/mac/psp_screen.py"), "--transport", f"record:{f}", "--source", DESKTOP,
                        "--fps", "0", "--frames", "5"], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stderr
    c = CScreen()
    frames = P.Parser(1 << 20).feed(f.read_bytes())
    assert all(fr.type == S.SCR_T_CHUNK for fr in frames)
    for fr in frames:
        c.chunk(fr.payload)
    c.present()
    assert np.array_equal(c.visible, make_source(DESKTOP).frame(0))
