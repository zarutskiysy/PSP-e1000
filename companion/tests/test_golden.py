"""Cross-checks the Python protocol against the real PSP C code (companion/psp/host/vectors)."""
import pathlib
import subprocess

import pytest

from psp_companion import protocol as P

HOST = pathlib.Path(__file__).resolve().parents[1] / "psp" / "host"


@pytest.fixture(scope="module")
def vectors_bin():
    subprocess.run(["make", "-C", str(HOST), "vectors"], check=True, capture_output=True)
    return HOST / "vectors"


class Vectors:
    def __init__(self, path):
        self.p = subprocess.Popen([str(path)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env={"ASAN_OPTIONS": "detect_leaks=0"})

    def line(self, s):
        self.p.stdin.write(s + "\n")
        self.p.stdin.flush()

    def read(self):
        return self.p.stdout.readline().strip()

    def feed(self, t, payload, now=1000):
        self.line(f"F {t} {payload.hex() or '-'} {now}")
        while True:
            r = self.read()
            if r.startswith("F "):
                return int(r[2:])

    def state(self):
        self.line("S")
        out = {}
        while True:
            r = self.read()
            if r == "END":
                return out
            k, _, v = r.partition("=")
            out[k] = v

    def close(self):
        self.p.stdin.close()
        self.p.wait(timeout=5)


@pytest.fixture
def v(vectors_bin):
    x = Vectors(vectors_bin)
    x.line("L 1 500")
    yield x
    x.close()


def test_mac_to_psp_messages_parse_in_c(v):
    assert v.feed(P.T_CONN, P.conn(P.Conn.ATTACHED, P.Mode.MANAGED, 3, 1, 2, "my-repo"))
    assert v.feed(P.T_AGENT, P.agent(P.Agent.TESTING))
    assert v.feed(P.T_ACTIVITY, P.activity("Running tests"))
    assert v.feed(P.T_ACTIONS, P.actions([(0, True, ""), (4, False, "No turn is running")]))
    assert v.feed(P.T_ANIM, P.anim(P.Anim.CELEBRATE))
    assert v.feed(P.T_HEARTBEAT, P.heartbeat(0xCAFEBABE, 77))
    s = v.state()
    assert (s["conn"], s["mode"], s["caps"], s["index"], s["count"], s["label"]) == ("1", "3", "3", "1", "2", "my-repo")
    assert (s["agent"], s["activity"], s["anim"]) == (str(int(P.Agent.TESTING)), "Running tests", str(int(P.Anim.CELEBRATE)))
    assert s["action0"] == "1:" and s["action4"] == "0:No turn is running"
    assert s["peer_boot"] == str(0xCAFEBABE)


def test_enums_match_the_c_header():
    header = (HOST.parent.parent / "proto_companion.h").read_text()
    for prefix, enum in (("PC_AG_", P.Agent), ("PC_ANIM_", P.Anim), ("PC_MODE_", P.Mode), ("PC_CONN_", P.Conn), ("PC_CLOSE_", P.Close), ("PC_ACK_", P.Ack), ("PC_KIND_", P.Kind), ("PC_DECISION_", P.Decision)):
        for m in enum:
            assert f"{prefix}{m.name} = {int(m)}" in header, (prefix, m)
    for name, val in (("PC_T_CONN", P.T_CONN), ("PC_T_APPROVAL_REQ", P.T_APPROVAL_REQ), ("PC_T_HEARTBEAT", P.T_HEARTBEAT), ("PC_T_BUTTON", P.T_BUTTON), ("PC_T_ACTION", P.T_ACTION), ("PC_T_APPROVAL_RESP", P.T_APPROVAL_RESP)):
        assert f"{name} = 0x{val:02X}" in header
    for name, val in (("PC_LABEL_MAX", P.LABEL_MAX), ("PC_ACTIVITY_MAX", P.ACTIVITY_MAX), ("PC_REASON_MAX", P.REASON_MAX), ("PC_TITLE_MAX", P.TITLE_MAX), ("PC_DETAIL_MAX", P.DETAIL_MAX), ("PC_TEXT_MAX", P.TEXT_MAX), ("PC_MAX_PAYLOAD", P.MAX_PAYLOAD)):
        assert f"#define {name} {val}u" in header


def test_approval_round_trip_through_real_c(v):
    assert v.feed(P.T_APPROVAL_REQ, P.approval_req(0xDEADBEEF, P.Kind.COMMAND, P.AF_ACTIONABLE, 120, 2, "Run command?", "npm test"))
    s = v.state()
    assert (s["ap_phase"], s["ap_id"], s["ap_timeout"], s["ap_pending"], s["ap_title"], s["ap_detail"]) == ("1", str(0xDEADBEEF), "120", "2", "Run command?", "npm test")
    v.line("B 0 2000")   # all released, past the arm delay
    v.line("B 16 2100")  # X down
    v.line("T 2120")
    v.line("B 0 2200")   # X up
    tx = [v.read() for _ in range(3)]  # button down, decision, button up
    decision = next(t for t in tx if t.startswith(f"TX {P.T_APPROVAL_RESP} "))
    m = P.decode_inbound(P.T_APPROVAL_RESP, bytes.fromhex(decision.split()[2]))
    assert (m.req_id, m.decision) == (0xDEADBEEF, P.Decision.ALLOW)
    assert v.feed(P.T_APPROVAL_CLOSE, P.approval_close(0xDEADBEEF, P.Close.ALLOWED, "Allowed once"))
    s = v.state()
    assert s["ap_phase"] == "0" and s["toast"] == "Allowed once"


def test_psp_messages_decode_in_python(v):
    assert v.feed(P.T_ACTIONS, P.actions([(i, True, "") for i in range(5)]))
    v.line("B 2 3000")  # DOWN pressed: selects action 1
    v.line("B 0 3050")
    v.line("B 16 3100")  # X: runs it
    tx = [v.read() for _ in range(4)]
    btn = P.decode_inbound(P.T_BUTTON, bytes.fromhex(tx[0].split()[2]))
    assert (btn.name, btn.down) == ("DOWN", True)
    act = next(t for t in tx if t.startswith(f"TX {P.T_ACTION} "))
    m = P.decode_inbound(P.T_ACTION, bytes.fromhex(act.split()[2]))
    assert m.action == P.Action.SUMMARIZE and m.req == 1


def test_truncated_payloads_are_rejected_by_c(v):
    good = P.approval_req(5, 0, 1, 10, 1, "Title", "Detail")
    for cut in range(1, len(good)):
        assert v.feed(P.T_APPROVAL_REQ, good[:cut]) == 0
    assert v.state()["ap_phase"] == "0"


def test_strings_are_capped_and_ascii():
    assert len(P.activity("x" * 500)) == 2 + P.ACTIVITY_MAX
    assert P.activity("é") == bytes([P.VERSION, 1]) + b"?"


def test_every_message_fits_the_psp_buffer():
    worst = [
        P.conn(1, 1, 1, 1, 1, "x" * 99),
        P.activity("x" * 999),
        P.actions([(i, False, "y" * 99) for i in range(5)]),
        P.approval_req(1, 0, 0, 1, 1, "t" * 99, "d" * 999),
        P.approval_close(1, 1, "x" * 99),
        P.action_ack(1, 1, "x" * 99),
    ]
    assert max(map(len, worst)) <= P.MAX_PAYLOAD
