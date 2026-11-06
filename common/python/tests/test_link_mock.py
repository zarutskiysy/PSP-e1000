"""End-to-end over the mock transport: Mac Link <-> tools/fake_psp.py (subprocess)."""
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "common" / "python"))

from pspmac import protocol as P  # noqa: E402
from pspmac.link import Link  # noqa: E402
from pspmac.transport import TcpTransport  # noqa: E402


@pytest.fixture
def fake_psp():
    proc = subprocess.Popen([sys.executable, str(ROOT / "tools/fake_psp.py"), "--port", "0", "--print-port",
                             "--once", "--quiet", "--app", "2"], stdout=subprocess.PIPE, text=True)
    line = proc.stdout.readline()
    assert line.startswith("PORT ")
    yield int(line.split()[1])
    proc.wait(timeout=5)


def test_handshake_ping_bulk(fake_psp):
    link = Link(TcpTransport("127.0.0.1", fake_psp), app=P.APP_GENERIC)
    peer = link.handshake()
    assert peer.role == P.ROLE_PSP and peer.app == 2 and peer.name == "fake_psp"
    rtts = [link.ping() for _ in range(20)]
    assert max(rtts) < 0.5
    # a big frame (raw 480x272 RGB565) must pass through intact framing
    link.send(P.T_TEST, bytes(480 * 272 * 2))
    assert link.ping() < 1.0
    link.close()


def test_c_host_build_talks_to_python():
    """The PSP-side C link logic over POSIX TCP <-> Python Link (proves C/Python interop live)."""
    exe = ROOT / "common/psp/test/echo_psp.bin"
    subprocess.run(["make", "-s", "-C", str(ROOT / "common/psp/test"), "echo_psp.bin"], check=True)
    proc = subprocess.Popen([str(exe), "0"], stdout=subprocess.PIPE, text=True)
    port = int(proc.stdout.readline().split()[1])
    link = Link(TcpTransport("127.0.0.1", port))
    peer = link.handshake()
    assert peer.role == P.ROLE_PSP and peer.name == "echo_psp"
    assert link.ping() < 0.5
    link.send(0xF1, b"x" * 70000)
    f = link.wait_for(0xF1, 2.0)
    assert f is not None and f.payload == b"x" * 70000
    link.close()
    assert proc.wait(timeout=5) == 0
