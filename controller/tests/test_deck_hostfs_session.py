"""HOSTFS session quirks: usbhostfs_pc accepts TCP on 10004 before the PSP is attached, and the PSP
app can restart while the TCP connection stays up. The daemon must keep re-sending HELLO until the
PSP answers, and re-send WHEEL_CONFIG when the PSP asks again. Mac->PSP frames must stay small
(usbhostfs keeps a 4 KiB Mac->PSP ring per channel and drops overflow)."""
import pathlib
import subprocess
import sys
import time

import pytest

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


def test_malformed_frames_do_not_kill_the_daemon(tmp_path):
    """CRC-valid frames with wrong payload sizes for every PSP->Mac type: logged, counted, skipped."""
    import json

    srv = TcpServerTransport("127.0.0.1", 0)
    summary = tmp_path / "s.json"
    d = subprocess.Popen([sys.executable, str(ROOT / "controller/mac/psp_deck.py"), "-t", f"tcp:127.0.0.1:{srv.port}",
                          "--dry-run", "--duration", "10", "--once", "--summary", str(summary)],
                         stderr=subprocess.PIPE, text=True)
    try:
        srv.accept(timeout=10)
        psp = Link(srv, role=P.ROLE_PSP, app=C.APP_ID, name="psp_deck")
        psp.send(P.T_HELLO, psp.hello_payload())
        assert psp.wait_for(C.T_WHEEL_CONFIG, 5) is not None
        bad = [(C.T_INPUT_STATE, b"\x01\x02\x03"), (C.T_INPUT_STATE, b""), (C.T_WHEEL_FIRE, b""),
               (C.T_WHEEL_FIRE, b"\x02\x00\x00"), (P.T_HELLO, b"\x01"), (P.T_HELLO_ACK, b""),
               (P.T_PONG, b"\x00" * 3), (C.T_CONFIG_REQ, b"junk"), (P.T_LOG, b"\xff\xfe")]
        for t, payload in bad:
            psp.send(t, payload)
        # still alive: a good frame afterwards is processed and the session ends cleanly on BYE
        psp.send(C.T_WHEEL_FIRE, C.WheelFire(0).pack())
        res = psp.wait_for(C.T_ACTION_RESULT, 5)
        assert res is not None and C.ActionResult.unpack(res.payload).ok
        psp.send(P.T_BYE)
    finally:
        d.wait(20)
        srv.close()
    err = d.stderr.read()
    assert d.returncode == 0, err
    assert "dropped malformed INPUT_STATE" in err and "dropped malformed WHEEL_FIRE" in err
    s = json.loads(summary.read_text())
    assert s["bad_frames"] == 4 and s["wheel_fires"] == 1


@pytest.mark.parametrize("spec", ["foo", "tcp:abc", "tcp:host:notaport", "usb"])
def test_bad_transport_spec_exits_2(spec):
    r = subprocess.run([sys.executable, str(ROOT / "controller/mac/psp_deck.py"), "-t", spec, "--dry-run"],
                       capture_output=True, text=True, timeout=10)
    assert r.returncode == 2 and "bad --transport" in r.stderr and "Traceback" not in r.stderr
