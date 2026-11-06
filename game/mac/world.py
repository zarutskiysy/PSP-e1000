"""Blackwater Ping world simulation (authoritative, Mac side). No pygame here: unit-testable.

A salvage sub descends a dark flooded shaft. The Mac player sees only what the lamp lights; the PSP
console sees threats on sonar. Active pings reveal mines / the creature but the creature hears them.
Sealed bulkheads must be unlocked by the PSP console (HACK_REQ -> HACK_RESULT).
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

import bw_proto as G

W, H = 960, 2400
SUB_R = 9
MINE_R = 9
LAMP_R = 95
MAX_RANGE = 700
GATE_YS = (800, 1600)
EXIT_Y = H - 90

ACCEL = 160.0      # px/s^2 at full thrust
DRAG = 1.4         # 1/s
MAX_SPEED = 120.0
BATTERY_DRAIN = 100 / 300.0  # per second -> 5 min of power
PING_COST, LISTEN_COST = 3.0, 1.0
HACK_TIME_DS = 200           # 20 s to solve a lock
HACK_RETRY_S = 3.0


@dataclass
class Mine:
    x: float
    y: float
    alive: bool = True
    phase: float = 0.0


@dataclass
class Gate:
    id: int
    y: float
    open: bool = False


@dataclass
class Creature:
    x: float
    y: float
    home_x: float
    home_y: float
    state: str = "idle"  # idle | hunt | linger | retreat
    tx: float = 0.0
    ty: float = 0.0
    timer: float = 0.0
    wander: float = 0.0


@dataclass
class Buoy:
    x: float
    y: float
    tag: int


@dataclass
class Sub:
    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0
    hull: float = 100.0
    battery: float = 100.0
    noise: float = 0.0
    heading: float = math.pi  # radians clockwise from north; start facing down


class World:
    def __init__(self, seed: int = 1, level: int = 1, mode: int = G.MODE_COOP, easy: bool = False):
        self.seed, self.level, self.mode, self.easy = seed, level, mode, easy
        self.rng = random.Random(seed)
        r = self.rng
        self.ph = [r.uniform(0, 6.28) for _ in range(4)]
        self.sub = Sub(*self.tunnel_point(60))
        self.mines: list[Mine] = []
        while len(self.mines) < 16:
            y = r.uniform(250, EXIT_Y - 120)
            if any(abs(y - gy) < 90 for gy in GATE_YS):
                continue
            cx, hw = self.tunnel(y)
            self.mines.append(Mine(cx + r.uniform(-0.75, 0.75) * hw, y, phase=r.uniform(0, 6.28)))
        hx, hy = self.tunnel_point(1200)
        self.creature = Creature(hx, hy, hx, hy)
        self.gates = [Gate(i + 1, gy) for i, gy in enumerate(GATE_YS)]
        self.exit = self.tunnel_point(EXIT_Y)
        self.buoys: list[Buoy] = []
        self.state = "play"  # play | won | lost
        self.reason = ""
        self.t = 0.0
        self.tick = 0
        self.out: list[tuple[int, bytes]] = []  # messages for the PSP (type, payload)
        self.echo_log: dict[int, list[tuple[int, object]]] = {}
        self.hack_gate: int | None = None
        self.hack_deadline = 0.0
        self.hack_retry_at = 0.0
        self.at_gate: Gate | None = None
        self.stats = {"pings": 0, "listens": 0, "hacks_ok": 0, "hacks_failed": 0, "marks": 0,
                      "mine_hits": 0, "creature_hits": 0, "wall_hits": 0}
        self._cd: dict[str, float] = {}
        self._battery_low_sent = False
        self.ping_fx: list[tuple[float, int]] = []  # (time, mode) for the renderer

    # ---- geometry -----------------------------------------------------------
    def tunnel(self, y: float) -> tuple[float, float]:
        p = self.ph
        cx = W / 2 + 170 * math.sin(y / 260 + p[0]) + 40 * math.sin(y / 97 + p[1])
        hw = 105 + 35 * math.sin(y / 180 + p[2]) + 15 * math.sin(y / 53 + p[3])
        return cx, hw

    def tunnel_point(self, y: float) -> tuple[float, float]:
        return self.tunnel(y)[0], y

    # ---- helpers --------------------------------------------------------------
    def _event(self, code: int, arg: int = 0) -> None:
        self.out.append((G.T_EVENT, G.pack_event(code, arg)))

    def _cooldown(self, key: str, seconds: float) -> bool:
        if self.t < self._cd.get(key, -1e9):
            return False
        self._cd[key] = self.t + seconds
        return True

    def _damage(self, amount: float, what: str) -> None:
        self.sub.hull = max(0.0, self.sub.hull - amount)
        self._event(G.EV_DAMAGE, int(amount))
        if self.sub.hull <= 0 and self.state == "play":
            self._end(False, f"hull breached ({what})")

    def _end(self, won: bool, reason: str) -> None:
        self.state = "won" if won else "lost"
        self.reason = reason
        self._event(G.EV_WIN if won else G.EV_LOSE)

    def alert_creature(self, x: float, y: float) -> None:
        c = self.creature
        if c.state != "retreat":
            c.state, c.tx, c.ty = "hunt", x, y

    # ---- PSP commands -----------------------------------------------------------
    def ping(self, ping_id: int, mode: int) -> list[G.Contact]:
        if self.state != "play":
            return []
        s = self.sub
        out: list[tuple[float, G.Contact, int, object]] = []

        def add(kind: int, obj, x: float, y: float, passive_range: bool = False):
            dx, dy = x - s.x, y - s.y
            d = math.hypot(dx, dy)
            if d > MAX_RANGE:
                return
            strength = int(255 * (1 - d / MAX_RANGE))
            out.append((d, G.Contact(G.bearing_of(dx, dy), 0 if passive_range else int(d), kind, strength), kind, obj))

        if mode == G.PING_ACTIVE:
            self.stats["pings"] += 1
            s.battery -= PING_COST
            s.noise = min(100.0, s.noise + 70)
            for m in self.mines:
                if m.alive:
                    add(G.K_MINE, m, m.x, m.y)
            for g in self.gates:
                if not g.open:
                    add(G.K_GATE, g, self.tunnel(g.y)[0], g.y)
            add(G.K_EXIT, None, *self.exit)
            add(G.K_CREATURE, self.creature, self.creature.x, self.creature.y)
            self.alert_creature(s.x, s.y)  # it heard that
        else:
            self.stats["listens"] += 1
            s.battery -= LISTEN_COST
            c = self.creature
            if math.hypot(c.x - s.x, c.y - s.y) < 900:
                d = math.hypot(c.x - s.x, c.y - s.y)
                out.append((d, G.Contact(G.bearing_of(c.x - s.x, c.y - s.y), 0, G.K_CREATURE, 200), G.K_CREATURE, c))
        out.sort(key=lambda e: e[0])
        out = out[: G.ECHO_MAX]
        self.echo_log[ping_id & 0xFF] = [(k, o) for _, _, k, o in out]
        self.ping_fx.append((self.t, mode))
        return [c for _, c, _, _ in out]

    def hack_result(self, gate_id: int, ok: bool) -> None:
        if self.hack_gate != gate_id:
            return
        self.hack_gate = None
        g = next((g for g in self.gates if g.id == gate_id), None)
        if g is None:
            return
        if ok:
            g.open = True
            self.stats["hacks_ok"] += 1
            self._event(G.EV_GATE_OPEN, gate_id)
        else:
            self.stats["hacks_failed"] += 1
            self.sub.noise = 100.0
            self.alert_creature(self.sub.x, self.sub.y)
            self.hack_retry_at = self.t + HACK_RETRY_S
            self._event(G.EV_HACK_FAIL, gate_id)

    def mark(self, ping_id: int, index: int) -> bool:
        log = self.echo_log.get(ping_id & 0xFF)
        if not log or index >= len(log):
            return False
        kind, obj = log[index]
        if isinstance(obj, Mine):
            self.buoys.append(Buoy(obj.x, obj.y, kind))
        elif isinstance(obj, Creature):
            self.buoys.append(Buoy(obj.x, obj.y, kind))  # where it WAS
        else:
            return False
        self.stats["marks"] += 1
        self._event(G.EV_MARKED, index)
        return True

    # ---- simulation ------------------------------------------------------------
    def step(self, dt: float, thrust: tuple[float, float]) -> None:
        if self.state != "play":
            return
        self.t += dt
        self.tick += 1
        s = self.sub
        tx, ty = thrust
        n = math.hypot(tx, ty)
        if n > 1:
            tx, ty = tx / n, ty / n
        s.vx += (tx * ACCEL - s.vx * DRAG) * dt
        s.vy += (ty * ACCEL - s.vy * DRAG) * dt
        sp = math.hypot(s.vx, s.vy)
        if sp > MAX_SPEED:
            s.vx, s.vy = s.vx * MAX_SPEED / sp, s.vy * MAX_SPEED / sp
            sp = MAX_SPEED
        if sp > 5:
            s.heading = math.atan2(s.vx, -s.vy)
        nx, ny = s.x + s.vx * dt, s.y + s.vy * dt
        # bulkheads
        self.at_gate = None
        for g in self.gates:
            if not g.open and s.y <= g.y - SUB_R and ny > g.y - SUB_R:
                ny, s.vy = g.y - SUB_R - 0.01, 0.0
            if not g.open and abs(ny - (g.y - SUB_R)) < 3:
                self.at_gate = g
        ny = max(20.0, min(H - 20.0, ny))
        # walls
        cx, hw = self.tunnel(ny)
        lim = hw - SUB_R
        if abs(nx - cx) > lim:
            nx = cx + math.copysign(lim, nx - cx)
            if sp > 70 and self._cooldown("wall", 0.8):
                self.stats["wall_hits"] += 1
                self._damage(5, "rock")
            s.vx *= -0.3
        s.x, s.y = nx, ny
        # mines
        for m in self.mines:
            if m.alive:
                m.phase += dt
                mx = m.x + 6 * math.sin(m.phase * 0.7)
                if math.hypot(mx - s.x, m.y - s.y) < SUB_R + MINE_R:
                    m.alive = False
                    self.stats["mine_hits"] += 1
                    s.noise = 100.0
                    self.alert_creature(s.x, s.y)
                    self._damage(30, "mine")
        self._step_creature(dt)
        # hacking
        if self.at_gate and self.hack_gate is None and self.t >= self.hack_retry_at:
            g = self.at_gate
            self.hack_gate = g.id
            self.hack_deadline = self.t + HACK_TIME_DS / 10 + 5.0
            seed = self.rng.getrandbits(32)
            self.out.append((G.T_HACK_REQ, G.pack_hack_req(g.id, 0, self.level - 1 + g.id - 1, seed, HACK_TIME_DS)))
        if self.hack_gate is not None and self.t > self.hack_deadline:
            self.hack_gate = None  # console never answered: ask again
        # power / noise
        s.battery -= BATTERY_DRAIN * dt
        s.noise = max(sp / 4, s.noise - 30 * dt)
        if s.battery <= 20 and not self._battery_low_sent:
            self._battery_low_sent = True
            self._event(G.EV_BATTERY_LOW, int(s.battery))
        if s.battery <= 0 and self.state == "play":
            s.battery = 0
            self._end(False, "battery dead")
        ex, ey = self.exit
        if self.state == "play" and s.y > ey - 30 and abs(s.x - ex) < 70:
            self._end(True, "reached the exit")

    def _step_creature(self, dt: float) -> None:
        c, s = self.creature, self.sub
        d = math.hypot(c.x - s.x, c.y - s.y)
        sp_sub = math.hypot(s.vx, s.vy)
        if c.state in ("idle", "linger") and d < 150 and sp_sub > 60:
            c.state, c.tx, c.ty = "hunt", s.x, s.y  # engine noise up close
        if c.state == "hunt" and d < 140:
            c.tx, c.ty = s.x, s.y  # close enough to track the hull directly
        if c.state == "idle":
            c.wander += dt * 0.5
            c.tx = c.home_x + 60 * math.sin(c.wander)
            c.ty = c.home_y + 140 * math.sin(c.wander * 0.37)
            speed = 30.0
        elif c.state == "hunt":
            speed = 45.0 if self.easy else 64.0
            if math.hypot(c.tx - c.x, c.ty - c.y) < 12:
                c.state, c.timer = "linger", 2.5
        elif c.state == "linger":
            speed = 0.0
            c.timer -= dt
            if c.timer <= 0:
                c.state, c.home_x, c.home_y = "idle", c.x, c.y
                c.wander = 0.0
        else:  # retreat
            speed = 90.0
            c.timer -= dt
            if c.timer <= 0:
                c.state, c.home_x, c.home_y = "idle", c.x, c.y
                c.wander = 0.0
        dx, dy = c.tx - c.x, c.ty - c.y
        n = math.hypot(dx, dy)
        if n > 1 and speed:
            step = min(n, speed * dt)
            c.x += dx / n * step
            c.y += dy / n * step
        cx, hw = self.tunnel(c.y)
        c.x = max(cx - hw + 10, min(cx + hw - 10, c.x))
        if d < 200 and self._cooldown("near", 4.0):
            self._event(G.EV_CREATURE_NEAR, int(d))
        if d < SUB_R + 14 and c.state != "retreat":
            self.stats["creature_hits"] += 1
            self._damage(12 if self.easy else 25, "creature")
            c.state, c.timer = "retreat", 4.0
            c.tx, c.ty = c.x + (c.x - s.x) * 20, c.y + (c.y - s.y) * 20

    # ---- outgoing state -----------------------------------------------------------
    def sub_state_payload(self) -> bytes:
        s = self.sub
        flags = G.SF_RUNNING if self.state == "play" else 0
        if self.at_gate:
            flags |= G.SF_AT_GATE
        if self.hack_gate is not None:
            flags |= G.SF_HACKING
        if self.creature.state == "hunt":
            flags |= G.SF_HUNTED
        heading = int((s.heading % (2 * math.pi)) * 65536 / (2 * math.pi)) & 0xFFFF
        return G.pack_sub_state(self.tick, s.x, s.y, heading, math.hypot(s.vx, s.vy), s.hull, s.battery, s.noise,
                                flags, sum(g.open for g in self.gates))

    def take_out(self) -> list[tuple[int, bytes]]:
        o, self.out = self.out, []
        return o

    # ---- autopilot (tests / --bot): cheats, it knows the map -------------------------
    def autopilot(self) -> tuple[float, float]:
        s = self.sub
        look = 70.0
        ty = min(s.y + look, self.exit[1])
        tx = self.tunnel(ty)[0]
        if s.y > self.exit[1] - 120:
            tx, ty = self.exit
        ax, ay = tx - s.x, ty - s.y
        n = math.hypot(ax, ay) or 1
        ax, ay = ax / n, ay / n
        for m in self.mines:
            if m.alive:
                dx, dy = s.x - m.x, s.y - m.y
                d = math.hypot(dx, dy)
                if d < 75:
                    ax += dx / d * (75 - d) / 18
                    ay += dy / d * (75 - d) / 30
        c = self.creature
        dx, dy = s.x - c.x, s.y - c.y
        d = math.hypot(dx, dy)
        if d < 90:
            ax += dx / d * 1.5
            ay += dy / d * 1.5
        cx, hw = self.tunnel(s.y)
        off = (s.x - cx) / hw
        if abs(off) > 0.55:  # stay off the rock
            ax -= off * 1.5
        sp = math.hypot(s.vx, s.vy)
        if sp > 70:  # gentle: keep the engine quiet
            ax -= s.vx / sp * 0.8
            ay -= s.vy / sp * 0.8
        return ax, ay
