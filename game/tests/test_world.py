"""World simulation without any link: the loop rules (ping/alert, locks, buoys, win/lose)."""
import bw_proto as G
import world as Wd


def run(seed, ping_every=90, hack_ok=True, easy=False, max_s=400):
    w = Wd.World(seed, easy=easy)
    pid = 0
    reqs = []
    for i in range(int(max_s * 30)):
        w.step(1 / 30, w.autopilot())
        if i % ping_every == 0:
            pid += 1
            w.ping(pid, G.PING_ACTIVE)
        for t, p in w.take_out():
            if t == G.T_HACK_REQ:
                reqs.append(p)
                w.hack_result(p[0], hack_ok)
        if w.state != "play":
            break
    return w, reqs


def test_deterministic():
    a, _ = run(3)
    b, _ = run(3)
    assert (a.state, a.tick, a.sub.hull) == (b.state, b.tick, b.sub.hull)


def test_bot_can_win_easy():
    wins = sum(run(s, easy=True)[0].state == "won" for s in range(1, 11))
    assert wins >= 5  # the creature is a real threat even for the cheating autopilot


def test_locks_block_without_psp():
    w, reqs = run(5, hack_ok=False, max_s=120)
    assert reqs, "touching a bulkhead must request a hack"
    assert w.sub.y < Wd.GATE_YS[0] + 1, "a failed hack must keep the bulkhead closed"
    assert w.stats["hacks_failed"] >= 1


def test_active_ping_alerts_creature_and_passive_does_not():
    w = Wd.World(1)
    w.sub.x, w.sub.y = w.tunnel_point(650)
    w.ping(1, G.PING_PASSIVE)
    assert w.creature.state == "idle"
    cs = w.ping(2, G.PING_ACTIVE)
    assert w.creature.state == "hunt"
    kinds = {c.kind for c in cs}
    assert G.K_MINE in kinds and G.K_GATE in kinds
    assert all(c.range <= Wd.MAX_RANGE for c in cs)
    assert w.sub.noise >= 70


def test_mark_drops_buoy_at_contact():
    w = Wd.World(2)
    w.sub.x, w.sub.y = w.tunnel_point(650)
    cs = w.ping(9, G.PING_ACTIVE)
    i = next(i for i, c in enumerate(cs) if c.kind == G.K_MINE)
    assert w.mark(9, i)
    assert len(w.buoys) == 1
    assert not w.mark(9, 99) and not w.mark(42, 0)


def test_battery_death():
    w = Wd.World(1)
    w.sub.battery = 0.01
    w.step(1 / 30, (0, 0))
    assert w.state == "lost" and "battery" in w.reason


def test_sub_state_payload_roundtrip():
    w = Wd.World(1)
    w.step(1 / 30, (0, 1))
    t = G.S_SUB_STATE.unpack(w.sub_state_payload())
    assert t[1] == int(w.sub.x) and t[2] == int(w.sub.y) and t[8] & G.SF_RUNNING
