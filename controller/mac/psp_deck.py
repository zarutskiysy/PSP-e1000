#!/usr/bin/env python3
"""psp_deck — use a PSP as a Mac control deck (nub -> mouse, buttons -> keys, action wheel -> macros).

  # real PSP over USB (run `usbhostfs_pc` in another terminal first):
  python controller/mac/psp_deck.py --transport hostfs
  # mock PSP (tools/fake_psp.py --plugin tools/fake_psp_controller.py), log events only:
  python controller/mac/psp_deck.py --transport mock --dry-run
  # PSP app in PPSSPP via tools/ppsspp_bridge.py (mock port):
  python controller/mac/psp_deck.py --transport mock --dry-run

Real mode needs the Accessibility permission for the terminal app (checked at start); --dry-run
never touches the system and never needs it.
"""
from __future__ import annotations

import argparse
import pathlib
import signal
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "common" / "python"))
sys.path.insert(0, str(HERE))

from pspmac import protocol as P  # noqa: E402
from pspmac.link import Link  # noqa: E402
from pspmac.transport import open_transport  # noqa: E402

from deck import config as cfgmod  # noqa: E402
from deck.backend import AX_HELP, DryRunBackend, QuartzBackend, accessibility_trusted  # noqa: E402
from deck.daemon import Deck, write_summary  # noqa: E402


def log(*a):
    print("[psp_deck]", *a, file=sys.stderr, flush=True)


def _on_sigterm(*_):
    raise KeyboardInterrupt


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--transport", "-t", default="hostfs",
                    help="hostfs (real PSP via usbhostfs_pc, default) | mock | tcp:HOST:PORT | usb")
    ap.add_argument("--config", "-c", default=str(cfgmod.DEFAULT_PATH), help="deck.toml path")
    ap.add_argument("--dry-run", action="store_true", help="log events instead of posting them")
    ap.add_argument("--events-log", help="dry-run: write events as JSON lines here ('-' = stdout)")
    ap.add_argument("--no-moves", action="store_true", help="dry-run log: skip mouse_move lines")
    ap.add_argument("--duration", type=float, help="stop after N seconds")
    ap.add_argument("--once", action="store_true", help="exit after the first session ends")
    ap.add_argument("--summary", help="write a JSON summary (rates, RTT, results) here at exit")
    ap.add_argument("--stats-every", type=float, default=5.0)
    ap.add_argument("--no-ax-wait", action="store_true",
                    help="real mode: exit instead of waiting when Accessibility is not granted")
    ap.add_argument("--check-config", action="store_true", help="validate the config and exit")
    a = ap.parse_args(argv)
    signal.signal(signal.SIGTERM, _on_sigterm)  # so `kill` still writes the summary

    try:
        cfg = cfgmod.load(a.config)
    except (cfgmod.ConfigError, OSError) as e:
        log(f"config error: {e}")
        return 2
    log(f"config {a.config}: {len(cfg.buttons)} button bindings, wheel = {cfg.labels}")
    if a.check_config:
        return 0

    out = None
    if a.dry_run:
        if a.events_log == "-":
            out = sys.stdout
        elif a.events_log:
            out = open(a.events_log, "w")
        backend = DryRunBackend(out, echo_moves=not a.no_moves)
        ax = False
        log("DRY RUN: events are only logged; Accessibility is not needed")
    else:
        ax = accessibility_trusted(prompt=True)
        if not ax:
            print(AX_HELP, file=sys.stderr, flush=True)
            if a.no_ax_wait:
                return 3
            log("waiting for the Accessibility grant (Ctrl+C to quit) ...")
            while not accessibility_trusted():
                time.sleep(2)
            ax = True
        log("Accessibility: granted")
        backend = QuartzBackend()

    deck = Deck(cfg, backend, ax, log, a.stats_every)
    t_end = None if a.duration is None else time.monotonic() + a.duration
    rc = 0
    try:
        while True:
            remaining = None if t_end is None else t_end - time.monotonic()
            if remaining is not None and remaining <= 0:
                break
            try:
                kw = {} if a.transport.startswith("usb") else {"connect_timeout": 2.0}
                tr = open_transport(a.transport, **kw)
            except ConnectionError as e:
                if a.once:
                    log(f"cannot connect: {e}")
                    rc = 1
                    break
                log(f"waiting for {a.transport}: {e}")
                time.sleep(1.0)
                continue
            log(f"transport {a.transport} open")
            link = Link(tr, role=P.ROLE_MAC, app=P.APP_CONTROLLER, name="psp_deck")
            reason = deck.run_session(link, remaining)
            log(f"session ended: {reason}")
            link.close(bye=reason == "duration")
            if a.once or reason == "duration":
                break
            time.sleep(0.5)
    except KeyboardInterrupt:
        log("interrupted")
    finally:
        backend.close()
        s = deck.stats.summary()
        log(f"summary: inputs={s['inputs']} input_hz={s['input_hz_median']} rtt_ms median={s['rtt_ms_median']} "
            f"p95={s['rtt_ms_p95']} (n={s['rtt_samples']}) events={s['events']} fires={s['wheel_fires']}")
        if a.summary:
            write_summary(a.summary, deck.stats)
        if out not in (None, sys.stdout):
            out.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
