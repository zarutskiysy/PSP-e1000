#!/usr/bin/env python3
"""fake_psp.py — plays the PSP end of the link on the Mac (mock transport = TCP).

The Mac app connects to it exactly like it would open the USB device:
    python tools/fake_psp.py                    # listen on 127.0.0.1:47100, generic PSP
    python tools/fake_psp.py --plugin tools/fake_psp_controller.py   # track-specific behaviour
    python tools/fake_psp.py --port 0 --print-port                    # random port (tests)

Generic behaviour: answers HELLO with HELLO_ACK, PING with PONG, prints every frame.
A plugin is a Python file defining `class Plugin` with any of:
    __init__(self, args)                 # args = list of extra CLI args after `--`
    on_connect(self, link)               # after accept
    on_frame(self, link, frame)          # every received frame (after auto-replies)
    tick(self, link, dt)                 # called ~every --tick seconds
    done(self) -> bool                   # return True to exit cleanly
Plugins live in the track branches (main only has this generic runner).
"""
from __future__ import annotations

import argparse
import importlib.util
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "common" / "python"))

from pspmac import protocol as P  # noqa: E402
from pspmac.link import Link  # noqa: E402
from pspmac.transport import MOCK_HOST, MOCK_PORT, TcpServerTransport  # noqa: E402


def load_plugin(path: str, extra: list[str]):
    spec = importlib.util.spec_from_file_location("fake_psp_plugin", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(mod)
    return mod.Plugin(extra)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default=MOCK_HOST)
    ap.add_argument("--port", type=int, default=MOCK_PORT)
    ap.add_argument("--print-port", action="store_true", help="print 'PORT <n>' once listening")
    ap.add_argument("--plugin", help="path to a plugin .py file")
    ap.add_argument("--app", type=int, default=P.APP_GENERIC, help="app id in HELLO_ACK")
    ap.add_argument("--tick", type=float, default=1 / 60)
    ap.add_argument("--once", action="store_true", help="exit when the client disconnects")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("extra", nargs="*", help="args passed to the plugin (put after --)")
    a = ap.parse_args(argv)

    plugin = load_plugin(a.plugin, a.extra) if a.plugin else None
    srv = TcpServerTransport(a.host, a.port)
    if a.print_port:
        print(f"PORT {srv.port}", flush=True)
    log = (lambda *_: None) if a.quiet else (lambda *x: print("[fake_psp]", *x, flush=True))
    log(f"listening on {a.host}:{srv.port}")
    while True:
        srv.accept()
        link = Link(srv, role=P.ROLE_PSP, app=a.app, name="fake_psp")
        log("client connected")
        if plugin and hasattr(plugin, "on_connect"):
            plugin.on_connect(link)
        last = time.monotonic()
        try:
            while True:
                f = link.recv(a.tick)
                if f is not None:
                    if f.type != P.T_TEST:
                        log(f"rx {f.name} seq={f.seq} len={len(f.payload)}")
                    if f.type == P.T_BYE:
                        break
                    if plugin and hasattr(plugin, "on_frame"):
                        plugin.on_frame(link, f)
                now = time.monotonic()
                if plugin and hasattr(plugin, "tick") and now - last >= a.tick:
                    plugin.tick(link, now - last)
                    last = now
                if plugin and hasattr(plugin, "done") and plugin.done():
                    link.close()
                    return 0
        except ConnectionError as e:
            log(f"disconnected: {e}")
        if a.once:
            break
    srv.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
