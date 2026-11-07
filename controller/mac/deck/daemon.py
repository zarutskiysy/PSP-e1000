"""Session logic: handshake, wheel config push, input mapping, wheel macros, RTT/rate stats."""
from __future__ import annotations

import json
import statistics
import struct
import sys
import time
from dataclasses import dataclass, field

from pspmac import protocol as P
from pspmac.link import Link

from . import proto as C
from .backend import Backend
from .config import Config
from .mapper import Event, Mapper

MAX_PAYLOAD = 4096  # largest frame the deck accepts; our biggest is 196 B (main's parser resyncs on oversize)

HELLO_EVERY = 1.0
PING_EVERY = 1.0
STALE_INPUT_S = 0.5  # no INPUT_STATE for this long -> release held buttons/keys


@dataclass
class Stats:
    inputs: int = 0
    fires: int = 0
    events: int = 0
    errors: int = 0
    bad_frames: int = 0
    rtts_ms: list[float] = field(default_factory=list)
    input_hz_windows: list[float] = field(default_factory=list)
    psp_rtt_us: int = 0
    labels_sent: list[str] = field(default_factory=list)
    results: list[dict] = field(default_factory=list)
    peer_name: str = ""

    def summary(self) -> dict:
        r = sorted(self.rtts_ms)
        hz = self.input_hz_windows[1:] or self.input_hz_windows  # first window is partial
        return {
            "inputs": self.inputs, "wheel_fires": self.fires, "events": self.events, "errors": self.errors,
            "bad_frames": self.bad_frames,
            "rtt_ms_min": round(r[0], 3) if r else None,
            "rtt_ms_median": round(statistics.median(r), 3) if r else None,
            "rtt_ms_p95": round(r[min(len(r) - 1, int(0.95 * len(r)))], 3) if r else None,
            "rtt_samples": len(r),
            "input_hz_median": round(statistics.median(hz), 1) if hz else None,
            "labels_sent": self.labels_sent, "results": self.results, "peer": self.peer_name,
        }


class Deck:
    def __init__(self, cfg: Config, backend: Backend, ax_trusted: bool, log=None, stats_every: float = 5.0):
        self.cfg = cfg
        self.backend = backend
        self.ax_trusted = ax_trusted
        self.mapper = Mapper(cfg)
        self.stats = Stats()
        self.stats_every = stats_every
        self.log = log or (lambda *a: print("[psp_deck]", *a, file=sys.stderr, flush=True))

    # -- outgoing ------------------------------------------------------------
    def send_config(self, link: Link) -> None:
        link.send(C.T_WHEEL_CONFIG, C.WheelConfig(self.cfg.labels).pack())
        self.stats.labels_sent = list(self.cfg.labels)

    def send_status(self, link: Link, input_hz: float) -> None:
        rtt = int(self.stats.rtts_ms[-1] * 1000) if self.stats.rtts_ms else 0
        link.send(C.T_MAC_STATUS, C.MacStatus(rtt, self.backend.events, int(round(input_hz)),
                                              self.backend.dry_run, self.ax_trusted).pack())

    def _post(self, evs: list[Event], raise_errors: bool = False) -> str:
        last = ""
        for ev in evs:
            try:
                last = self.backend.post(ev)
                self.stats.events += 1
            except Exception as e:  # never let one bad event kill the session
                self.stats.errors += 1
                self.log(f"event {ev.kind} failed: {e}")
                if raise_errors:
                    raise
        return last

    def fire(self, link: Link, idx: int) -> C.ActionResult:
        self.stats.fires += 1
        try:
            label, evs = self.mapper.wheel_events(idx)
            text = self._post(evs, raise_errors=True) or "ok"
            res = C.ActionResult(idx, True, f"{label}: {text}")
        except Exception as e:
            res = C.ActionResult(idx, False, f"error: {e}")
        self.log(f"wheel slice {idx} -> {'OK' if res.ok else 'FAIL'} {res.text}")
        self.stats.results.append({"slice": idx, "ok": res.ok, "text": res.text})
        link.send(C.T_ACTION_RESULT, res.pack())
        return res

    # -- session -------------------------------------------------------------
    def run_session(self, link: Link, duration: float | None = None) -> str:
        """Runs until BYE / disconnect / duration. Returns the reason."""
        t0 = now = time.monotonic()
        next_hello = now
        next_ping = now + 0.2
        next_stats = now + self.stats_every
        win_start, win_inputs, input_hz = now, 0, 0.0
        last_input = now
        held = False
        pings: dict[int, float] = {}
        ping_id = 0
        configured = False
        reason = "duration"
        try:
            while duration is None or now - t0 < duration:
                now = time.monotonic()
                if not configured and now >= next_hello:
                    link.send(P.T_HELLO, link.hello_payload())
                    next_hello = now + HELLO_EVERY
                if configured and now >= next_ping:
                    ping_id += 1
                    pings[ping_id] = time.perf_counter()
                    link.send(P.T_PING, struct.pack("<Q", ping_id))
                    next_ping = now + PING_EVERY
                    if len(pings) > 16:
                        pings.pop(min(pings))
                if now - win_start >= 1.0:
                    input_hz = win_inputs / (now - win_start)
                    if configured:
                        self.stats.input_hz_windows.append(input_hz)
                        self.send_status(link, input_hz)
                    win_start, win_inputs = now, 0
                if held and now - last_input > STALE_INPUT_S:
                    self.log("input stalled; releasing held buttons")
                    self._post(self.mapper.release_all())
                    held = False
                if now >= next_stats and configured:
                    s = self.stats.summary()
                    self.log(f"input {input_hz:.1f} Hz | rtt median {s['rtt_ms_median']} ms "
                             f"p95 {s['rtt_ms_p95']} ms | events {self.stats.events} | fires {self.stats.fires}")
                    next_stats = now + self.stats_every
                f = link.recv(0.005)
                if f is None:
                    continue
                if f.type == P.T_BYE:
                    reason = "bye"
                    break
                try:
                    configured, held, last_input, win_inputs = self._dispatch(
                        link, f, now, configured, held, last_input, win_inputs, pings)
                except (ValueError, struct.error, IndexError) as e:
                    # a CRC-valid but malformed frame (wrong length) must not kill the session
                    self.stats.bad_frames += 1
                    self.log(f"dropped malformed {C.TYPE_NAMES.get(f.type, f.name)} frame (len {len(f.payload)}): {e}")
        except ConnectionError as e:
            reason = f"disconnected: {e}"
        finally:
            try:
                self._post(self.mapper.release_all())
            except Exception:
                pass
        return reason

    def _dispatch(self, link, f, now, configured, held, last_input, win_inputs, pings):
        """Handle one frame; returns the updated session state. Raises on malformed payloads."""
        if f.type in (P.T_HELLO, P.T_HELLO_ACK):
            peer = link.peer
            self.stats.peer_name = peer.name if peer else ""
            if peer and peer.app != C.APP_ID:
                self.log(f"warning: peer app id {peer.app} != {C.APP_ID} (not the deck app?)")
            if not configured:
                self.log(f"connected to {self.stats.peer_name or 'PSP'}; sending {len(self.cfg.wheel)} wheel labels")
            configured = True
            self.send_config(link)
        elif f.type == C.T_CONFIG_REQ:
            configured = True
            self.send_config(link)
        elif f.type == C.T_INPUT_STATE:
            st = C.InputState.unpack(f.payload)
            self.stats.inputs += 1
            win_inputs += 1
            last_input = now
            held = st.buttons != 0
            self._post(self.mapper.on_input(st))
        elif f.type == C.T_WHEEL_FIRE:
            self.fire(link, C.WheelFire.unpack(f.payload).slice)
        elif f.type == P.T_PONG and len(f.payload) == 8:
            (pid,) = struct.unpack("<Q", f.payload)
            t = pings.pop(pid, None)
            if t is not None:
                self.stats.rtts_ms.append((time.perf_counter() - t) * 1000)
        elif f.type == P.T_LOG:
            self.log("PSP:", f.payload.decode(errors="replace"))
        return configured, held, last_input, win_inputs


def write_summary(path: str, stats: Stats) -> None:
    with open(path, "w") as f:
        json.dump(stats.summary(), f, indent=2)
