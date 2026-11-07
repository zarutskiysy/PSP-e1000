#!/usr/bin/env python3
"""Blackwater Ping — Mac main screen (pygame-ce). The PSP is the sonar + lock console.

    python game/mac/blackwater.py                        # mock: tools/fake_psp.py / psp_host on :47100
    python game/mac/blackwater.py --transport hostfs     # real PSP over USB (usbhostfs_pc running)
    python game/mac/blackwater.py --transport tcp:127.0.0.1:47103   # PSP app in PPSSPP via ppsspp_bridge
    python game/mac/blackwater.py --headless --bot --exit-on-over --summary out.json   # automated run

Keys: arrows / WASD thrust, ENTER dive (or press START on the PSP), F12 screenshot, ESC quit.
Debug only: P = active ping from the Mac (normally the PSP's job).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import pathlib
import statistics
import struct
import sys
import threading
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "common" / "python"))
sys.path.insert(0, str(HERE))

import bw_proto as G  # noqa: E402
import world as Wd  # noqa: E402
from pspmac import protocol as P  # noqa: E402
from pspmac.link import Link  # noqa: E402
from pspmac.transport import open_transport  # noqa: E402

SCREEN_W, SCREEN_H = 960, 540
FPS = 30
DT = 1.0 / FPS

EVENT_TEXT = {
    G.EV_DAMAGE: "HULL DAMAGE", G.EV_CREATURE_NEAR: "SOMETHING IS CLOSE...", G.EV_GATE_OPEN: "BULKHEAD {arg} OPEN",
    G.EV_WIN: "SURFACED", G.EV_LOSE: "SIGNAL LOST", G.EV_BATTERY_LOW: "BATTERY LOW",
    G.EV_HACK_FAIL: "LOCK ALARM - IT HEARD THAT", G.EV_MARKED: "PSP DROPPED A BUOY",
}


class LinkManager:
    """Owns the Link; (re)connects in a background thread so the game never blocks on it."""

    def __init__(self, spec: str | None, log):
        self.spec, self.log = spec, log
        self.link: Link | None = None
        self.peer = ""
        self.last_peer = ""
        self.lock = threading.Lock()
        self.rtts: list[float] = []
        self.last_ping = 0.0
        self.by_type_tx: dict[str, int] = {}
        self.by_type_rx: dict[str, int] = {}
        self.tx_bytes = self.rx_bytes = 0
        self.t_connected: float | None = None
        self.last_rx = 0.0      # monotonic time of the last frame from the PSP
        self.last_hello = 0.0
        self._connecting = False
        self.connect()

    def connect(self) -> None:
        if self.spec in (None, "none") or self._connecting:
            return
        self._connecting = True

        def run():
            while True:
                try:
                    t = open_transport(self.spec, connect_timeout=1.0) if self.spec != "usb" else open_transport("usb")
                    lk = Link(t, role=P.ROLE_MAC, app=G.APP_ID, name="blackwater_mac")
                    lk.send(P.T_HELLO, lk.hello_payload())
                    with self.lock:
                        self.link = lk
                        self.t_connected = time.monotonic()
                    self.log(f"link up ({self.spec})")
                    break
                except (ConnectionError, OSError) as e:
                    self.log(f"waiting for PSP on {self.spec}: {e}")
                    time.sleep(1.0)
            self._connecting = False

        threading.Thread(target=run, daemon=True).start()

    @property
    def up(self) -> bool:
        return self.link is not None

    @property
    def peer_ok(self) -> bool:
        """Transport up AND the PSP app answered recently. With "hostfs", usbhostfs_pc accepts TCP before
        a PSP is attached, so `up` alone proves nothing."""
        return self.link is not None and time.monotonic() - self.last_rx < 3.0

    def _drop(self, why: str) -> None:
        with self.lock:
            if self.link is not None:
                self.tx_bytes += self.link.tx_bytes
                self.rx_bytes += self.link.rx_bytes
                try:
                    self.link.t.close()
                except Exception:
                    pass
            self.link = None
            self.peer = ""
        self.log(f"link lost: {why}")
        self.connect()

    def send(self, type_: int, payload: bytes = b"") -> None:
        lk = self.link
        if lk is None:
            return
        try:
            lk.send(type_, payload)
            n = G.NAMES.get(type_, P.TYPE_NAMES.get(type_, hex(type_)))
            self.by_type_tx[n] = self.by_type_tx.get(n, 0) + 1
        except ConnectionError as e:
            self._drop(str(e))

    def poll(self, max_frames: int = 64) -> list[P.Frame]:
        lk = self.link
        out: list[P.Frame] = []
        if lk is None:
            return out
        try:
            now = time.perf_counter()
            if now - self.last_ping > 1.0:
                self.last_ping = now
                lk.send(P.T_PING, struct.pack("<d", now))
            mono = time.monotonic()
            if not self.peer_ok and mono - self.last_hello > 1.0:
                # the first HELLO may have been lost (hostfs before the PSP attached, PSP app restarted)
                self.last_hello = mono
                lk.send(P.T_HELLO, lk.hello_payload())
            while len(out) < max_frames:
                f = lk.recv(0)
                if f is None:
                    break
                n = G.NAMES.get(f.type, P.TYPE_NAMES.get(f.type, hex(f.type)))
                self.by_type_rx[n] = self.by_type_rx.get(n, 0) + 1
                self.last_rx = time.monotonic()
                if f.type == P.T_PONG and len(f.payload) == 8:
                    self.rtts.append(time.perf_counter() - struct.unpack("<d", f.payload)[0])
                    continue
                if f.type in (P.T_HELLO, P.T_HELLO_ACK) and lk.peer:
                    self.peer = self.last_peer = lk.peer.name
                if f.type == P.T_BYE:
                    raise ConnectionError("peer said BYE")
                out.append(f)
        except ConnectionError as e:
            self._drop(str(e))
        return out

    def totals(self) -> tuple[int, int]:
        lk = self.link
        return (self.tx_bytes + (lk.tx_bytes if lk else 0), self.rx_bytes + (lk.rx_bytes if lk else 0))

    def close(self) -> None:
        lk = self.link
        if lk is not None:
            self.tx_bytes, self.rx_bytes = self.totals()
            self.link = None
            lk.close()


class Game:
    def __init__(self, a: argparse.Namespace):
        self.a = a
        self.quiet = a.quiet
        self.links = LinkManager(a.transport, self.log)
        self.world: Wd.World | None = None
        self.games = 0
        self.frame = 0
        self.ticker: list[tuple[float, str]] = []
        self.pilot = (0.0, 0.0)
        self.pilot_t = -1e9
        self.last_state_wall = 0.0
        self.over_wall: float | None = None
        self.shots_done: set[str] = set()
        self.t0 = time.monotonic()
        self.echoes_sent = 0
        self.screen = None
        self.font = self.font_big = None
        self.lamp = None

    def log(self, msg: str) -> None:
        if not self.quiet:
            print(f"[blackwater] {msg}", flush=True)

    def event_log(self, rec: dict) -> None:
        if self.a.event_log:
            with open(self.a.event_log, "a") as fh:
                fh.write(json.dumps(rec) + "\n")

    def say(self, text: str) -> None:
        self.ticker.append((time.monotonic(), text))
        self.ticker = self.ticker[-6:]

    # ---- game flow ---------------------------------------------------------------
    def start_game(self) -> None:
        self.games += 1
        seed = (self.a.seed + self.games - 1) & 0xFFFFFFFF
        self.world = Wd.World(seed, level=1, mode=G.MODE_SOLO if self.a.solo else G.MODE_COOP, easy=self.a.easy)
        self.over_wall = None
        self.links.send(G.T_GAME_START, G.pack_game_start(1, self.world.mode, seed, Wd.MAX_RANGE))
        self.say(f"DIVE #{self.games} (seed {seed})")
        self.log(f"game start seed={seed}")

    def handle(self, f: P.Frame) -> None:
        w = self.world
        if f.type == G.T_READY:
            if w is None or w.state != "play":
                self.start_game()
            else:  # PSP app (re)started mid-dive: let it rejoin the running game
                self.links.send(G.T_GAME_START, G.pack_game_start(w.level, w.mode, w.seed, Wd.MAX_RANGE))
                self.say("PSP CONSOLE REJOINED")
                if w.hack_gate is not None:
                    w.hack_gate = None  # re-issue the lock puzzle on the next tick
        elif f.type == G.T_PING_CMD and len(f.payload) >= G.S_PING_CMD.size and w is not None:
            pid, mode, _b, _wd = G.S_PING_CMD.unpack_from(f.payload)
            contacts = w.ping(pid, mode)
            if w.state == "play":
                self.links.send(G.T_ECHO, G.pack_echo(pid, mode, contacts))
                self.echoes_sent += 1
                self.say("PSP: ACTIVE PING (LOUD)" if mode == G.PING_ACTIVE else "PSP: LISTENING")
        elif f.type == G.T_HACK_RESULT and len(f.payload) >= G.S_HACK_RESULT.size and w is not None:
            gid, ok, el = G.S_HACK_RESULT.unpack_from(f.payload)
            w.hack_result(gid, bool(ok))
            self.log(f"hack result gate={gid} ok={ok} {el / 10:.1f}s")
        elif f.type == G.T_MARK and len(f.payload) >= G.S_MARK.size and w is not None:
            pid, idx, _tag = G.S_MARK.unpack_from(f.payload)
            w.mark(pid, idx)
        elif f.type == G.T_PILOT and len(f.payload) >= G.S_PILOT.size:
            ax, ay, _btn = G.S_PILOT.unpack_from(f.payload)
            self.pilot = (ax / 127.0, ay / 127.0)
            self.pilot_t = time.monotonic()

    def thrust(self, keys) -> tuple[float, float]:
        tx = ty = 0.0
        if keys is not None:
            import pygame

            tx = (keys[pygame.K_RIGHT] or keys[pygame.K_d]) - (keys[pygame.K_LEFT] or keys[pygame.K_a])
            ty = (keys[pygame.K_DOWN] or keys[pygame.K_s]) - (keys[pygame.K_UP] or keys[pygame.K_w])
        if tx or ty:
            return float(tx), float(ty)
        if time.monotonic() - self.pilot_t < 0.6 and self.pilot != (0.0, 0.0):
            return self.pilot
        if self.a.bot and self.world is not None:
            return self.world.autopilot()
        return 0.0, 0.0

    def step(self, keys) -> None:
        for f in self.links.poll():
            self.handle(f)
        w = self.world
        if w is not None:
            prev = w.state
            w.step(DT, self.thrust(keys))
            for t, p in w.take_out():
                self.links.send(t, p)
                if t == G.T_EVENT:
                    code, arg = G.S_EVENT.unpack_from(p)
                    self.say(EVENT_TEXT.get(code, f"EVENT {code}").format(arg=arg))
                elif t == G.T_HACK_REQ:
                    self.say(f"BULKHEAD {p[0]} SEALED - PSP: CRACK THE LOCK")
                    gid, pz, diff, seed, lim = G.S_HACK_REQ.unpack(p)
                    self.event_log({"ev": "hack_req", "gate": gid, "puzzle": pz, "difficulty": diff, "seed": seed,
                                    "time_limit_ds": lim})
            if prev == "play" and w.state != "play":
                self.over_wall = time.monotonic()
                self.event_log({"ev": "over", "state": w.state, "reason": w.reason})
                self.log(f"game over: {w.state} ({w.reason}) t={w.t:.1f}s stats={w.stats}")
        now = time.monotonic()
        if now - self.last_state_wall >= 1.0 / self.a.state_hz and w is not None and self.links.peer_ok:
            self.last_state_wall = now
            self.links.send(G.T_SUB_STATE, w.sub_state_payload())
        if self.a.autostart and w is None and (self.links.peer_ok or self.a.transport == "none"):
            self.start_game()

    # ---- rendering -----------------------------------------------------------------
    def init_video(self) -> None:
        import pygame

        pygame.display.init()
        pygame.font.init()
        self.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
        pygame.display.set_caption("Blackwater Ping (Mac)")
        self.font = pygame.font.Font(None, 22)
        self.font_big = pygame.font.Font(None, 64)
        r = Wd.LAMP_R
        lamp = pygame.Surface((2 * r, 2 * r), pygame.SRCALPHA)
        lamp.fill((0, 0, 0, 255))
        for rr in range(r, 0, -2):
            pygame.draw.circle(lamp, (0, 0, 0, int(242 * (rr / r) ** 2)), (r, r), rr)
        self.lamp = lamp
        self.dark = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)

    def text(self, s: str, pos, color=(170, 230, 210), big=False, center=False) -> None:
        img = (self.font_big if big else self.font).render(s, True, color)
        r = img.get_rect()
        if center:
            r.center = pos
        else:
            r.topleft = pos
        self.screen.blit(img, r)

    def bar(self, x, y, label, v, color) -> None:
        import pygame

        self.text(label, (x, y))
        pygame.draw.rect(self.screen, (40, 80, 70), (x + 60, y + 2, 122, 12), 1)
        pygame.draw.rect(self.screen, color, (x + 61, y + 3, int(max(0, min(100, v)) * 1.2), 10))

    def render(self) -> None:
        import pygame

        scr = self.screen
        w = self.world
        scr.fill((6, 18, 26) if w is not None else (0, 0, 0))
        if w is None:
            self.render_title()
            pygame.display.flip()
            return
        s = w.sub
        cam = max(0.0, min(Wd.H - SCREEN_H, s.y - 200))

        def sy(y):
            return int(y - cam)

        # rock walls
        for y in range(0, SCREEN_H, 6):
            cx, hw = w.tunnel(cam + y)
            pygame.draw.rect(scr, (66, 72, 74), (0, y, int(cx - hw), 6))
            pygame.draw.rect(scr, (66, 72, 74), (int(cx + hw), y, SCREEN_W, 6))
            pygame.draw.rect(scr, (120, 126, 118), (int(cx - hw) - 2, y, 3, 6))
            pygame.draw.rect(scr, (120, 126, 118), (int(cx + hw), y, 3, 6))
        # bulkheads
        for g in w.gates:
            cx, hw = w.tunnel(g.y)
            y = sy(g.y)
            if g.open:
                for x in range(int(cx - hw), int(cx + hw), 16):
                    pygame.draw.line(scr, (50, 90, 130), (x, y), (x + 6, y), 2)
            else:
                pygame.draw.rect(scr, (70, 120, 190), (int(cx - hw), y - 3, int(2 * hw), 7))
                for x in range(int(cx - hw), int(cx + hw), 20):
                    pygame.draw.line(scr, (230, 200, 60), (x, y - 3), (x + 8, y + 3), 2)
        # mines and the creature (only seen through the lamp)
        def lit(x, y, pad=20):
            return math.hypot(x - s.x, y - s.y) < Wd.LAMP_R + pad

        for m in w.mines:
            if m.alive and lit(m.x, m.y):
                mx, my = int(m.x + 6 * math.sin(m.phase * 0.7)), sy(m.y)
                pygame.draw.circle(scr, (190, 160, 60), (mx, my), Wd.MINE_R)
                for k in range(6):
                    a = k * math.pi / 3 + m.phase * 0.3
                    pygame.draw.line(scr, (190, 160, 60), (mx, my),
                                     (mx + int(14 * math.cos(a)), my + int(14 * math.sin(a))), 2)
        c = w.creature
        cxs, cys = int(c.x), sy(c.y)
        if lit(c.x, c.y, 30):
            pygame.draw.ellipse(scr, (110, 20, 30), (cxs - 22, cys - 14, 44, 28))
            pygame.draw.circle(scr, (255, 220, 120), (cxs - 8, cys - 3), 3)
            pygame.draw.circle(scr, (255, 220, 120), (cxs + 8, cys - 3), 3)
        # darkness with the lamp hole
        self.dark.fill((0, 0, 0, 242))
        self.dark.blit(self.lamp, (int(s.x) - Wd.LAMP_R, sy(s.y) - Wd.LAMP_R), special_flags=pygame.BLEND_RGBA_MIN)
        scr.blit(self.dark, (0, 0))
        # always visible: exit beacon, buoys, ping rings, the sub
        ex, ey = w.exit
        if (self.frame // 10) % 2:
            pygame.draw.circle(scr, (60, 255, 120), (int(ex), sy(ey)), 10, 2)
        pygame.draw.circle(scr, (30, 120, 60), (int(ex), sy(ey)), 4)
        for b in w.buoys:
            col = (255, 230, 90) if b.tag == G.K_MINE else (255, 90, 90)
            bx, by = int(b.x), sy(b.y)
            pygame.draw.polygon(scr, col, [(bx, by - 8), (bx + 6, by), (bx, by + 8), (bx - 6, by)], 2)
            if (self.frame // 8) % 2:
                pygame.draw.circle(scr, col, (bx, by), 2)
        for t, mode in w.ping_fx[-4:]:
            age = w.t - t
            if age < 1.2:
                r = int(age * Wd.MAX_RANGE / 1.2)
                col = (80, 200, 170) if mode == G.PING_ACTIVE else (60, 90, 90)
                pygame.draw.circle(scr, col, (int(s.x), sy(s.y)), max(r, 2), 1)
        hx, hy = math.sin(s.heading), -math.cos(s.heading)
        px, py = int(s.x), sy(s.y)
        pts = [(px + hx * 14, py + hy * 14), (px - hx * 9 - hy * 7, py - hy * 9 + hx * 7),
               (px - hx * 9 + hy * 7, py - hy * 9 - hx * 7)]
        pygame.draw.polygon(scr, (240, 200, 70), pts)
        self.render_hud()
        pygame.display.flip()

    def render_hud(self) -> None:
        import pygame

        w = self.world
        s = w.sub
        self.bar(12, 10, "HULL", s.hull, (90, 230, 120) if s.hull > 35 else (240, 80, 60))
        self.bar(12, 28, "BATT", s.battery, (230, 200, 70) if s.battery > 20 else (240, 80, 60))
        self.bar(12, 46, "NOISE", s.noise, (230, 70, 70))
        self.text(f"DEPTH {int(s.y)} / {Wd.EXIT_Y}   GATES {sum(g.open for g in w.gates)}/{len(w.gates)}", (12, 66))
        rt = self.links.rtts[-20:]
        if self.links.peer_ok:
            link = f"PSP LINK {self.links.peer or 'UP'}" + (f"  RTT {1000 * statistics.median(rt):.0f} ms" if rt else "")
        elif self.links.up:
            link = f"PSP SILENT ({self.a.transport}) - is the PSP app running?"
        else:
            link = f"NO PSP LINK ({self.a.transport})"
        self.text(link, (SCREEN_W - 330, 10), (90, 230, 120) if self.links.peer_ok else (240, 80, 60))
        self.text("SONAR IS ON THE PSP: ASK FOR PINGS", (SCREEN_W - 330, 28), (90, 130, 120))
        if w.hack_gate is not None:
            left = max(0.0, w.hack_deadline - 5.0 - w.t)
            self.text(f"BULKHEAD {w.hack_gate} SEALED - PSP CRACKING THE LOCK ({left:.0f}s)", (SCREEN_W // 2, 110),
                      (120, 180, 255), center=True)
        now = time.monotonic()
        for i, (t, msg) in enumerate(reversed(self.ticker)):
            if now - t < 6:
                self.text(msg, (12, SCREEN_H - 24 - 18 * i), (170, 230, 210) if i == 0 else (90, 130, 120))
        if w.state != "play":
            won = w.state == "won"
            overlay = pygame.Surface((SCREEN_W, 150), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 200))
            self.screen.blit(overlay, (0, SCREEN_H // 2 - 75))
            self.text("SURFACED - SALVAGE SAFE" if won else "LOST", (SCREEN_W // 2, SCREEN_H // 2 - 20),
                      (90, 255, 140) if won else (255, 80, 60), big=True, center=True)
            self.text(f"{w.reason}  |  time {w.t:.0f}s  pings {w.stats['pings']}  locks {w.stats['hacks_ok']}  "
                      f"buoys {w.stats['marks']}", (SCREEN_W // 2, SCREEN_H // 2 + 22), center=True)
            self.text("ENTER or PSP START: dive again", (SCREEN_W // 2, SCREEN_H // 2 + 46), center=True)

    def render_title(self) -> None:
        self.text("BLACKWATER PING", (SCREEN_W // 2, 150), (80, 220, 180), big=True, center=True)
        lines = [
            "A salvage sub in a flooded shaft. Your lamp shows the rock. Only the PSP sonar shows what moves.",
            "Mac: steer (arrows / WASD).   PSP: X ping (loud!), SQUARE listen, TRIANGLE drop buoy, crack locks.",
            "Every active ping wakes the thing in the dark.",
        ]
        for i, l in enumerate(lines):
            self.text(l, (SCREEN_W // 2, 230 + 24 * i), center=True)
        st = (f"PSP linked: {self.links.peer or 'yes'}" if self.links.peer_ok else f"waiting for PSP ({self.a.transport})")
        self.text(st, (SCREEN_W // 2, 340), (90, 230, 120) if self.links.peer_ok else (240, 80, 60), center=True)
        if (self.frame // 15) % 2:
            self.text("ENTER or PSP START to dive", (SCREEN_W // 2, 380), center=True)

    def shot(self, path: str) -> None:
        import pygame

        if self.screen is not None:
            pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
            self.render()
            pygame.image.save(self.screen, path)
            self.log(f"screenshot -> {path}")

    # ---- main loop ------------------------------------------------------------------
    def run(self) -> dict:
        import pygame

        a = self.a
        self.init_video()
        wall_per_frame = DT / a.speed
        running = True
        while running:
            t_frame = time.monotonic()
            keys = None
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    running = False
                elif ev.type == pygame.KEYDOWN:
                    if ev.key == pygame.K_ESCAPE:
                        running = False
                    elif ev.key == pygame.K_RETURN and (self.world is None or self.world.state != "play"):
                        self.start_game()
                    elif ev.key == pygame.K_F12:
                        self.shot(str(ROOT / "docs" / "img" / f"mac_{int(time.time())}.png"))
                    elif ev.key == pygame.K_p and self.world is not None:
                        self.handle(P.Frame(G.T_PING_CMD, 0, 0, G.pack_ping_cmd(200 + self.frame % 50, 1)))
            if not a.headless:
                keys = pygame.key.get_pressed()
            self.step(keys)
            self.frame += 1
            w = self.world
            if a.shot_hack and "hack" not in self.shots_done and w is not None and w.hack_gate is not None \
                    and w.t - (w.hack_deadline - Wd.HACK_TIME_DS / 10 - 5.0) > 0.5:
                self.shots_done.add("hack")
                self.shot(a.shot_hack)
            if a.shot_ping and "ping" not in self.shots_done and w is not None and w.ping_fx \
                    and 0.35 < w.t - w.ping_fx[-1][0] < 0.6 and w.stats["pings"] >= 3:
                self.shots_done.add("ping")
                self.shot(a.shot_ping)
            if not a.headless or self.frame % a.render_every == 0:
                self.render()
            if a.frames and self.frame >= a.frames:
                break
            if a.max_seconds and time.monotonic() - self.t0 > a.max_seconds:
                self.log("max-seconds reached")
                break
            if a.exit_on_over and self.over_wall is not None and time.monotonic() - self.over_wall > 1.0:
                break
            sleep = wall_per_frame - (time.monotonic() - t_frame)
            if sleep > 0:
                time.sleep(sleep)
        if a.shot:
            self.shot(a.shot)
        summary = self.summary()
        self.links.close()
        pygame.quit()
        return summary

    def summary(self) -> dict:
        w = self.world
        el = max(1e-6, time.monotonic() - (self.links.t_connected or self.t0))
        tx, rx = self.links.totals()
        rt = [1000 * x for x in self.links.rtts]
        return {
            "outcome": w.state if w else "not_started",
            "reason": w.reason if w else "",
            "games": self.games,
            "sim_time_s": round(w.t, 2) if w else 0,
            "frames": self.frame,
            "stats": w.stats if w else {},
            "gates_open": sum(g.open for g in w.gates) if w else 0,
            "hull": round(w.sub.hull, 1) if w else None,
            "battery": round(w.sub.battery, 1) if w else None,
            "echoes_sent": self.echoes_sent,
            "peer": self.links.last_peer,
            "rtt_ms": {"n": len(rt), "median": round(statistics.median(rt), 2) if rt else None,
                       "max": round(max(rt), 2) if rt else None},
            "tx_bytes": tx, "rx_bytes": rx, "wall_s": round(el, 2),
            "tx_Bps": round(tx / el, 1), "rx_Bps": round(rx / el, 1),
            "tx_frames": self.links.by_type_tx, "rx_frames": self.links.by_type_rx,
        }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--transport", default="mock", help='mock | hostfs | usb | tcp:HOST:PORT | none')
    ap.add_argument("--headless", action="store_true", help="SDL dummy video driver, no window")
    ap.add_argument("--bot", action="store_true", help="autopilot steers the sub (tests)")
    ap.add_argument("--autostart", action="store_true", help="dive as soon as the link is up")
    ap.add_argument("--solo", action="store_true", help="solo mode flag (PSP nub steers; it always can)")
    ap.add_argument("--easy", action="store_true", help="slower, weaker creature")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--speed", type=float, default=1.0, help="simulation speed multiplier (headless tests)")
    ap.add_argument("--state-hz", type=float, default=10.0, help="SUB_STATE rate (wall clock)")
    ap.add_argument("--frames", type=int, default=0)
    ap.add_argument("--max-seconds", type=float, default=0)
    ap.add_argument("--exit-on-over", action="store_true")
    ap.add_argument("--render-every", type=int, default=15, help="headless: render every N frames")
    ap.add_argument("--shot", help="save a PNG of the window at exit")
    ap.add_argument("--shot-hack", help="save a PNG while the first lock is being cracked")
    ap.add_argument("--shot-ping", help="save a PNG right after an active ping (3rd one)")
    ap.add_argument("--summary", help="write the JSON summary here")
    ap.add_argument("--event-log", help="append JSON lines (hack requests, game over) for test drivers")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    if a.headless:
        os.environ["SDL_VIDEODRIVER"] = "dummy"
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    g = Game(a)
    s = g.run()
    js = json.dumps(s)
    print(js, flush=True)
    if a.summary:
        pathlib.Path(a.summary).write_text(js + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
