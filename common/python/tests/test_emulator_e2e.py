"""Real PSP code in PPSSPP <-> Mac Link, through tools/ppsspp_bridge.py (mailbox over the debugger).

Skipped when PPSSPP or the PSP toolchain is missing. Uses debugger port 45690 (override: PSP_E2E_PPSSPP_PORT)."""
import os
import pathlib
import shutil
import subprocess
import sys
import time

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "common" / "python"))
sys.path.insert(0, str(ROOT / "tools"))

from pspmac.link import Link  # noqa: E402
from pspmac.transport import TcpTransport  # noqa: E402

PPSSPP = os.environ.get("PPSSPP_BIN", "/Applications/PPSSPPSDL.app/Contents/MacOS/PPSSPPSDL")
PSPDEV = pathlib.Path(os.environ.get("PSPDEV", pathlib.Path.home() / "pspdev"))
PORT = int(os.environ.get("PSP_E2E_PPSSPP_PORT", "45690"))

pytestmark = pytest.mark.skipif(not (os.path.exists(PPSSPP) and (PSPDEV / "bin/psp-gcc").exists()),
                                reason="PPSSPP or pspdev toolchain not installed")


@pytest.fixture(scope="module")
def echo_in_emulator():
    from ppsspp import Ppsspp

    env = dict(os.environ, PATH=f"{PSPDEV}/bin:{os.environ['PATH']}", PSPDEV=str(PSPDEV))
    subprocess.run(["make", "-s", "-C", str(ROOT / "examples/echo")], check=True, env=env, capture_output=True)
    Ppsspp.kill(PORT)
    emu = Ppsspp.launch(ROOT / "examples/echo/EBOOT.PBP", PORT)
    emu.ws.close()
    br = subprocess.Popen([sys.executable, str(ROOT / "tools/ppsspp_bridge.py"), "--port", str(PORT), "--listen", "0",
                           "--quiet"], stdout=subprocess.PIPE, text=True)
    line = br.stdout.readline()
    assert line.startswith("LISTEN "), line
    yield int(line.split()[1])
    br.terminate()
    Ppsspp.kill(PORT)


def test_handshake_ping_echo(echo_in_emulator):
    link = Link(TcpTransport("127.0.0.1", echo_in_emulator, connect_timeout=20))
    peer = link.handshake(timeout=10)
    assert peer.name == "echo" and peer.role == 1
    rtt = min(link.ping(timeout=5) for _ in range(3))
    assert rtt < 1.0
    payload = bytes(range(256)) * 100
    link.send(0xF1, payload)
    f = link.wait_for(0xF1, 20)
    assert f is not None and f.payload == payload
    link.close()
