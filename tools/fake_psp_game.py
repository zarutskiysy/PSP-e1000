"""fake_psp plugin: a scripted PSP console for Blackwater Ping (track C), so the Mac game can be
tested headless without a PSP or an emulator.

    python tools/fake_psp.py --plugin tools/fake_psp_game.py --app 3 -- [options]
options (after --):
    --ping-every S    active ping period in seconds (default 2.5)
    --listen-every S  passive listen period (default 0 = never)
    --hack-delay S    time to "solve" a lock (default 0.8)
    --fail-first      fail the first lock on purpose (exercises the alarm path)
    --mark            drop a buoy on the nearest mine after each echo
    --pilot           steer the sub from here (solo mode) instead of the Mac autopilot
    --games N         exit after N finished games (default 1; 0 = never)
    --summary PATH    write a JSON summary on exit
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "game" / "mac"))
import bw_proto as G  # noqa: E402


class Plugin:
    def __init__(self, args):
        ap = argparse.ArgumentParser(prog="fake_psp_game")
        ap.add_argument("--ping-every", type=float, default=2.5)
        ap.add_argument("--listen-every", type=float, default=0.0)
        ap.add_argument("--hack-delay", type=float, default=0.8)
        ap.add_argument("--fail-first", action="store_true")
        ap.add_argument("--mark", action="store_true")
        ap.add_argument("--pilot", action="store_true")
        ap.add_argument("--games", type=int, default=1)
        ap.add_argument("--summary")
        self.a = ap.parse_args(args)
        self.reset()
        self.stats = {"games": 0, "wins": 0, "losses": 0, "pings": 0, "listens": 0, "echoes": 0, "contacts": 0,
                      "hacks_ok": 0, "hacks_failed": 0, "marks": 0, "sub_states": 0, "events": {}}

    def reset(self):
        self.connected_at = None
        self.ready_sent = 0.0
        self.playing = False
        self.ping_id = 0
        self.last_ping = self.last_listen = 0.0
        self.hack = None  # (gate_id, due_time, t0)
        self.failed_once = False
        self.sub = None
        self.finished = False

    def on_connect(self, link):
        self.reset()
        self.connected_at = time.monotonic()

    def on_frame(self, link, f):
        st = self.stats
        if f.type == G.T_GAME_START:
            self.playing = True
            self.hack = None
        elif f.type == G.T_SUB_STATE:
            st["sub_states"] += 1
            self.sub = G.S_SUB_STATE.unpack_from(f.payload)
        elif f.type == G.T_ECHO:
            pid, mode, cs = G.unpack_echo(f.payload)
            st["echoes"] += 1
            st["contacts"] += len(cs)
            if self.a.mark and mode == G.PING_ACTIVE:
                mines = [(c.range, i) for i, c in enumerate(cs) if c.kind == G.K_MINE]
                if mines:
                    link.send(G.T_MARK, G.pack_mark(pid, min(mines)[1], G.K_MINE))
                    st["marks"] += 1
        elif f.type == G.T_HACK_REQ:
            gid, _pz, diff, _x, seed, limit = (f.payload[0], f.payload[1], f.payload[2], 0,
                                               int.from_bytes(f.payload[4:8], "little"),
                                               int.from_bytes(f.payload[8:10], "little"))
            if self.hack is None or self.hack[0] != gid:
                now = time.monotonic()
                self.hack = (gid, now + self.a.hack_delay, now)
        elif f.type == G.T_EVENT:
            code, arg = G.S_EVENT.unpack_from(f.payload)
            ev = st["events"]
            ev[str(code)] = ev.get(str(code), 0) + 1
            if code in (G.EV_WIN, G.EV_LOSE):
                self.playing = False
                st["games"] += 1
                st["wins" if code == G.EV_WIN else "losses"] += 1
                self.ready_sent = time.monotonic()  # do not re-ready immediately

    def tick(self, link, dt):
        now = time.monotonic()
        if not self.playing:
            done = self.a.games and self.stats["games"] >= self.a.games
            if not done and self.connected_at and now - self.connected_at > 0.3 and now - self.ready_sent > 2.0:
                link.send(G.T_READY, G.pack_ready(1))
                self.ready_sent = now
            return
        if self.hack is not None:
            gid, due, t0 = self.hack
            if now >= due:
                ok = not (self.a.fail_first and not self.failed_once)
                self.failed_once = True
                link.send(G.T_HACK_RESULT, G.pack_hack_result(gid, ok, int((now - t0) * 10)))
                self.stats["hacks_ok" if ok else "hacks_failed"] += 1
                self.hack = None
            return
        if self.a.ping_every and now - self.last_ping >= self.a.ping_every:
            self.ping_id = (self.ping_id % 255) + 1
            link.send(G.T_PING_CMD, G.pack_ping_cmd(self.ping_id, G.PING_ACTIVE))
            self.last_ping = now
            self.stats["pings"] += 1
        if self.a.listen_every and now - self.last_listen >= self.a.listen_every:
            self.ping_id = (self.ping_id % 255) + 1
            link.send(G.T_PING_CMD, G.pack_ping_cmd(self.ping_id, G.PING_PASSIVE))
            self.last_listen = now
            self.stats["listens"] += 1
        if self.a.pilot and self.sub is not None:
            link.send(G.T_PILOT, G.pack_pilot(0, 90, 0))  # straight down: crude but it exercises PILOT

    def done(self):
        d = bool(self.a.games) and self.stats["games"] >= self.a.games
        if d and not self.finished:
            self.finished = True
            js = json.dumps(self.stats)
            print(js, flush=True)
            if self.a.summary:
                pathlib.Path(self.a.summary).write_text(js + "\n")
        return d
