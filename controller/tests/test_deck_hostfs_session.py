"""HOSTFS session quirks: usbhostfs_pc accepts TCP on 10004 before the PSP is attached, and the PSP
app can restart while the TCP connection stays up. The daemon must keep re-sending HELLO until the
PSP answers, and re-send WHEEL_CONFIG when the PSP asks again. Mac->PSP frames must stay small
(usbhostfs keeps a 4 KiB Mac->PSP ring per channel and drops overflow)."""
import pathlib
import subprocess
import sys
import time

from pspmac import protocol as P
from pspmac.link import Link
from pspmac.transport import TcpServerTransport

from deck import proto as C

ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_late_psp_and_psp_restart(tmp_path):
    srv = TcpServerTransport("127.0.0.1", 0)
    d = subprocess.Popen([sys.executable, str(ROOT / "controller/mac/psp_deck.py"), "-t", f"tcp:127.0.0.1:{srv.port}",
                          "--dry-run", "--duration", "12", "--once", "--summary", str(tmp_path / "s.json")],
                         stderr=subprocess.PIPE, text=True)
    try:
        srv.accept(timeout=10)
        # "PSP not attached yet": swallow everything for 2.5 s (usbhostfs_pc drops it too)
        psp = Link(srv, role=P.ROLE_PSP, app=C.APP_ID, name="psp_deck", auto_reply=False)
        t_end = time.monotonic() + 2.5
        hellos = 0
        biggest = 0
        while time.monotonic() < t_end:
            f = psp.recv(0.1)
            if f is not None:
                hellos += f.type == P.T_HELLO
                biggest = max(biggest, len(f.payload) + P.OVERHEAD)
        assert hellos >= 2, "daemon must retry HELLO while the PSP is absent"
        # PSP app boots: HELLO + CONFIG_REQ, expect WHEEL_CONFIG
        psp.auto_reply = True

        def boot_and_get_config():
            psp.send(P.T_HELLO, psp.hello_payload())
            psp.send(C.T_CONFIG_REQ)
            f = psp.wait_for(C.T_WHEEL_CONFIG, 5)
            assert f is not None
            assert len(f.payload) + P.OVERHEAD < 1024
            return C.WheelConfig.unpack(f.payload).labels

        labels = boot_and_get_config()
        assert labels[0] == "Mission Ctrl"
        for i in range(10):
            psp.send(C.T_INPUT_STATE, C.InputState(0, 128, 128, 0, 0xFF, i * 16667, i).pack())
        # PSP app restarts (same TCP connection, frame counter and clock start over)
        assert boot_and_get_config() == labels
        psp.send(P.T_BYE)
        assert biggest < 1024
    finally:
        d.wait(20)
        srv.close()
    assert "session ended: bye" in d.stderr.read()
