"""fake_psp plugin for feat/mac-controller: plays the PSP deck app over the mock transport.

    python tools/fake_psp.py --plugin tools/fake_psp_controller.py --once -- --scenario demo --report r.json
    python controller/mac/psp_deck.py --transport mock --dry-run --events-log - --once

Plugin args (after `--`):
  --scenario demo|idle   demo = scripted nub/buttons/wheel run (default); idle = centred nub forever
  --report PATH          write what the fake PSP saw (wheel labels, action results, status) as JSON
  --loop                 repeat the demo scenario instead of finishing
It waits for WHEEL_CONFIG (the Mac pushes it after the handshake), then streams INPUT_STATE at the
fake_psp tick rate (default 60 Hz), like the real PSP app does every vblank.
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "controller" / "mac"))
from deck import proto as C  # noqa: E402

B = C.BUTTONS


def nub_towards_slice(i: int, n: int, r: float = 0.9) -> tuple[int, int]:
    """Nub position pointing at slice i of n (slice 0 at 12 o'clock, clockwise)."""
    a = 2 * math.pi * i / n
    return int(round(128 + 127 * r * math.sin(a))), int(round(128 - 127 * r * math.cos(a)))


def demo_steps(n_slices: int, fire_slice: int):
    """(seconds, buttons, lx, ly, flags, hover, fire) — fire = slice to fire at the end of the step."""
    wx, wy = nub_towards_slice(fire_slice, max(n_slices, 1))
    return [
        (0.2, 0, 128, 128, 0, C.NO_SLICE, None),
        (0.5, 0, 255, 128, 0, C.NO_SLICE, None),                 # cursor right
        (0.1, 0, 128, 128, 0, C.NO_SLICE, None),
        (0.1, B["L"], 128, 128, 0, C.NO_SLICE, None),             # left click
        (0.1, 0, 128, 128, 0, C.NO_SLICE, None),
        (0.3, B["L"], 128, 0, 0, C.NO_SLICE, None),               # drag up
        (0.1, 0, 128, 128, 0, C.NO_SLICE, None),
        (0.1, B["R"], 128, 128, 0, C.NO_SLICE, None),             # right click
        (0.1, 0, 128, 128, 0, C.NO_SLICE, None),
        (0.1, B["CROSS"], 128, 128, 0, C.NO_SLICE, None),         # return
        (0.1, 0, 128, 128, 0, C.NO_SLICE, None),
        (0.7, B["UP"], 128, 128, 0, C.NO_SLICE, None),            # up arrow, auto-repeat
        (0.1, 0, 128, 128, 0, C.NO_SLICE, None),
        (0.3, B["TRIANGLE"], 128, 255, 0, C.NO_SLICE, None),      # scroll down
        (0.1, 0, 128, 128, 0, C.NO_SLICE, None),
        (0.2, B["SELECT"], 128, 128, C.IN_F_WHEEL_OPEN, C.NO_SLICE, None),   # wheel open
        (0.4, B["SELECT"], wx, wy, C.IN_F_WHEEL_OPEN, fire_slice, fire_slice),  # aim + release
        (0.3, 0, 128, 128, 0, C.NO_SLICE, None),
    ]


class Plugin:
    def __init__(self, args):
        ap = argparse.ArgumentParser(prog="fake_psp_controller")
        ap.add_argument("--scenario", default="demo", choices=["demo", "idle"])
        ap.add_argument("--report")
        ap.add_argument("--loop", action="store_true")
        ap.add_argument("--fire-slice", type=int, default=2)
        self.a = ap.parse_args(args)
        self.labels: list[str] | None = None
        self.results: list[dict] = []
        self.status: dict | None = None
        self.steps: list = []
        self.step_i = 0
        self.step_t = 0.0
        self.frame = 0
        self.sent = 0
        self.wait_result_until = 0.0
        self.finished = False
        self.t0 = time.monotonic()

    def on_connect(self, link):
        link.app = C.APP_ID

    def on_frame(self, link, f):
        if f.type == C.T_WHEEL_CONFIG:
            self.labels = C.WheelConfig.unpack(f.payload).labels
            print(f"[fake_psp_controller] wheel labels: {self.labels}", flush=True)
            if not self.steps and self.a.scenario == "demo":
                self.steps = demo_steps(len(self.labels), self.a.fire_slice)
        elif f.type == C.T_ACTION_RESULT:
            r = C.ActionResult.unpack(f.payload)
            self.results.append({"slice": r.slice, "ok": r.ok, "text": r.text})
            print(f"[fake_psp_controller] action result: {self.results[-1]}", flush=True)
        elif f.type == C.T_MAC_STATUS:
            s = C.MacStatus.unpack(f.payload)
            self.status = s.__dict__

    def _send(self, link, buttons, lx, ly, flags, hover):
        t_us = int((time.monotonic() - self.t0) * 1e6) & 0xFFFFFFFF
        link.send(C.T_INPUT_STATE, C.InputState(buttons, lx, ly, flags, hover, t_us, self.frame).pack())
        self.frame += 1
        self.sent += 1

    def tick(self, link, dt):
        if self.labels is None or self.finished:
            return
        if self.a.scenario == "idle":
            self._send(link, 0, 128, 128, 0, C.NO_SLICE)
            return
        if self.step_i >= len(self.steps):
            if self.a.loop:
                self.step_i, self.step_t = 0, 0.0
            elif self.results or time.monotonic() > self.wait_result_until:
                self._finish()
            else:
                self._send(link, 0, 128, 128, 0, C.NO_SLICE)
            return
        dur, buttons, lx, ly, flags, hover, fire = self.steps[self.step_i]
        self._send(link, buttons, lx, ly, flags, hover)
        self.step_t += dt
        if self.step_t >= dur:
            self.step_i += 1
            self.step_t = 0.0
            if fire is not None:
                link.send(C.T_WHEEL_FIRE, C.WheelFire(fire, int((time.monotonic() - self.t0) * 1e6)).pack())
                self.wait_result_until = time.monotonic() + 2.0

    def _finish(self):
        self.finished = True
        if self.a.report:
            pathlib.Path(self.a.report).write_text(json.dumps(
                {"labels": self.labels, "results": self.results, "status": self.status, "inputs_sent": self.sent},
                indent=2))

    def done(self):
        return self.finished
