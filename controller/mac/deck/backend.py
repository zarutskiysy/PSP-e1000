"""Event sinks: DryRunBackend (logs JSON lines, used by tests) and QuartzBackend (real CGEvents).

QuartzBackend references (see docs/research/mac-controller.md facts #22-#27):
  CGEventCreateMouseEvent / CGEventCreateKeyboardEvent / CGEventCreateScrollWheelEvent / CGEventPost
  media keys: NSEvent systemDefined (type 14), subtype 8 (NX_SUBTYPE_AUX_CONTROL_BUTTONS),
  data1 = (NX_KEYTYPE << 16) | ((0xA down | 0xB up) << 8)  — gist fredrikw/4078034.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from typing import IO

from .mapper import Event

# NX_KEYTYPE_* from IOKit/hidsystem/ev_keymap.h (checked in the local macOS SDK)
NX_KEYTYPE = {"volup": 0, "voldown": 1, "mute": 7, "playpause": 16, "next": 17, "previous": 18}

ONE_SHOT = ("media", "shell", "app", "mission_control")


class Backend:
    dry_run = True
    events = 0

    def post(self, ev: Event) -> str:
        """Perform the event; return a short human result (shown on the PSP for macros).
        Raise on failure."""
        raise NotImplementedError

    def close(self) -> None:
        pass


class DryRunBackend(Backend):
    """Never touches the system. Writes one JSON object per event to `out` (file or stdout)."""
    dry_run = True

    def __init__(self, out: IO[str] | None = None, echo_moves: bool = True):
        self.out = out
        self.echo_moves = echo_moves
        self.log: list[dict] = []
        self.events = 0

    def post(self, ev: Event) -> str:
        self.events += 1
        rec = {"t": round(time.monotonic(), 4), **ev.to_json()}
        self.log.append(rec)
        if self.out is not None and (self.echo_moves or ev.kind != "mouse_move"):
            self.out.write(json.dumps(rec) + "\n")
            self.out.flush()
        if ev.kind == "shell":
            return f"dry-run: would run {ev['cmd']}"
        if ev.kind == "app":
            return f"dry-run: would open {ev['name']}"
        return f"dry-run: {ev.kind}"


def accessibility_trusted(prompt: bool = False) -> bool:
    """AXIsProcessTrusted(); with prompt=True macOS shows the 'grant Accessibility' dialog."""
    import ApplicationServices as AS

    if prompt:
        return bool(AS.AXIsProcessTrustedWithOptions({AS.kAXTrustedCheckOptionPrompt: True}))
    return bool(AS.AXIsProcessTrusted())


AX_HELP = """\
Accessibility permission is missing, so macOS would silently drop the synthetic mouse/key events.
Grant it once:
  System Settings -> Privacy & Security -> Accessibility -> enable the app that runs this daemon
  (Terminal / iTerm / Ghostty / Cursor ...; Python inherits the terminal's grant).
  If the app is not listed, press '+' and add it. Then quit and reopen that terminal app.
Or run with --dry-run to only log events."""


class QuartzBackend(Backend):
    dry_run = False
    DOUBLE_CLICK_S = 0.35

    def __init__(self, verbose: bool = False):
        import Quartz as Q  # pyobjc-framework-Quartz

        self.Q = Q
        self.verbose = verbose
        self.events = 0
        self.held: set[str] = set()
        self._last_click = ("", 0.0, 0)  # button, time, count

    # -- helpers -------------------------------------------------------------
    def _pos(self):
        Q = self.Q
        return Q.CGEventGetLocation(Q.CGEventCreate(None))

    def _displays(self):
        Q = self.Q
        err, ids, n = Q.CGGetActiveDisplayList(16, None, None)
        return [Q.CGDisplayBounds(i) for i in ids[:n]] if err == 0 else [Q.CGDisplayBounds(Q.CGMainDisplayID())]

    @staticmethod
    def _inside(r, x, y) -> bool:
        return r.origin.x <= x < r.origin.x + r.size.width and r.origin.y <= y < r.origin.y + r.size.height

    def _clamp(self, old, x, y):
        rects = self._displays()
        if any(self._inside(r, x, y) for r in rects):
            return x, y
        home = next((r for r in rects if self._inside(r, old.x, old.y)), rects[0])
        x = min(max(x, home.origin.x), home.origin.x + home.size.width - 1)
        y = min(max(y, home.origin.y), home.origin.y + home.size.height - 1)
        return x, y

    def _post(self, ev) -> None:
        self.Q.CGEventPost(self.Q.kCGHIDEventTap, ev)
        self.events += 1

    # -- events --------------------------------------------------------------
    def post(self, ev: Event) -> str:
        Q = self.Q
        k = ev.kind
        if k == "mouse_move":
            old = self._pos()
            x, y = self._clamp(old, old.x + ev["dx"], old.y + ev["dy"])
            if "left" in self.held:
                t, b = Q.kCGEventLeftMouseDragged, Q.kCGMouseButtonLeft
            elif "right" in self.held:
                t, b = Q.kCGEventRightMouseDragged, Q.kCGMouseButtonRight
            elif "middle" in self.held:
                t, b = Q.kCGEventOtherMouseDragged, Q.kCGMouseButtonCenter
            else:
                t, b = Q.kCGEventMouseMoved, Q.kCGMouseButtonLeft
            e = Q.CGEventCreateMouseEvent(None, t, (x, y), b)
            Q.CGEventSetIntegerValueField(e, Q.kCGMouseEventDeltaX, int(ev["dx"]))
            Q.CGEventSetIntegerValueField(e, Q.kCGMouseEventDeltaY, int(ev["dy"]))
            self._post(e)
            return "moved"
        if k == "mouse_button":
            btn, down = ev["button"], ev["down"]
            types = {
                "left": (Q.kCGEventLeftMouseDown, Q.kCGEventLeftMouseUp, Q.kCGMouseButtonLeft),
                "right": (Q.kCGEventRightMouseDown, Q.kCGEventRightMouseUp, Q.kCGMouseButtonRight),
                "middle": (Q.kCGEventOtherMouseDown, Q.kCGEventOtherMouseUp, Q.kCGMouseButtonCenter),
            }[btn]
            now = time.monotonic()
            if down:
                lb, lt, lc = self._last_click
                count = lc + 1 if (lb == btn and now - lt < self.DOUBLE_CLICK_S) else 1
                self._last_click = (btn, now, count)
                self.held.add(btn)
            else:
                count = self._last_click[2] if self._last_click[0] == btn else 1
                self.held.discard(btn)
            e = Q.CGEventCreateMouseEvent(None, types[0] if down else types[1], self._pos(), types[2])
            Q.CGEventSetIntegerValueField(e, Q.kCGMouseEventClickState, count)
            self._post(e)
            return f"{btn} {'down' if down else 'up'}"
        if k == "scroll":
            e = Q.CGEventCreateScrollWheelEvent(None, Q.kCGScrollEventUnitLine, 1, int(ev["dy"]))
            self._post(e)
            return "scrolled"
        if k == "key":
            from .keys import flags_for

            e = Q.CGEventCreateKeyboardEvent(None, ev["keycode"], bool(ev["down"]))
            if ev["mods"]:
                Q.CGEventSetFlags(e, flags_for(tuple(ev["mods"])))
            if ev.args.get("repeat"):
                Q.CGEventSetIntegerValueField(e, Q.kCGKeyboardEventAutorepeat, 1)
            self._post(e)
            return f"key {ev['key']}"
        if k == "media":
            self._media(NX_KEYTYPE[ev["key"]])
            return f"media {ev['key']}"
        if k == "mission_control":
            subprocess.run(["open", "-a", "Mission Control"], check=True, timeout=5)
            self.events += 1
            return "Mission Control"
        if k == "app":
            subprocess.run(["open", "-a", ev["name"]], check=True, timeout=10)
            self.events += 1
            return f"opened {ev['name']}"
        if k == "shell":
            p = subprocess.Popen(ev["cmd"], shell=True, start_new_session=True,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.events += 1
            print(f"[psp_deck] shell pid={p.pid}: {ev['cmd']}", file=sys.stderr, flush=True)
            return f"started pid {p.pid}"
        raise ValueError(f"unknown event kind {k}")

    def _media(self, key: int) -> None:
        from AppKit import NSEvent  # pyobjc-framework-Cocoa

        for down in (True, False):
            ev = NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
                14, (0, 0), 0xA00 if down else 0xB00, 0, 0, None, 8,
                (key << 16) | ((0xA if down else 0xB) << 8), -1)
            self._post(ev.CGEvent())

    def close(self) -> None:
        # never leave a mouse button stuck down
        for b in list(self.held):
            try:
                self.post(Event("mouse_button", {"button": b, "down": False}))
            except Exception:
                pass
