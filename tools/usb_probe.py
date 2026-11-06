#!/usr/bin/env python3
"""usb_probe.py — morning hardware smoke test for the PSP USB link (Mac side).

    python tools/usb_probe.py list                     # Sony USB devices seen by libusb (VID 054C)
    python tools/usb_probe.py echo --spec usb          # needs examples/echo (USB build) running, MACLINK mode
    python tools/usb_probe.py echo --spec hostfs       # HOSTFS mode: start `usbhostfs_pc` first (another tab)
    python tools/usb_probe.py echo --spec mock         # dry run against tools/fake_psp.py / the emulator bridge

`echo` does HELLO, 50 pings (RTT min/median/max) and round-trip echo throughput at several sizes,
and prints one line per result for docs/MORNING_REPORT.md.
"""
from __future__ import annotations

import argparse
import pathlib
import statistics
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "common" / "python"))

from pspmac import protocol as P  # noqa: E402
from pspmac.link import Link  # noqa: E402
from pspmac.transport import _libusb_backend, open_transport  # noqa: E402

SPEEDS = {1: "low", 2: "full (12 Mbit/s)", 3: "high (480 Mbit/s)", 4: "super"}


def cmd_list() -> int:
    import usb.core

    devs = list(usb.core.find(find_all=True, idVendor=P.USB_VID, backend=_libusb_backend()))
    if not devs:
        print("no Sony (054C) USB devices. Is the PSP app running and the cable a DATA cable?")
        return 1
    for d in devs:
        what = {0x01C9: "psplink usbhostfs (HOSTFS mode)", 0x01CB: "pspmaclink (MACLINK mode)"}.get(d.idProduct, "?")
        print(f"054C:{d.idProduct:04X}  speed={SPEEDS.get(d.speed, d.speed)}  {what}")
    return 0


def cmd_echo(spec: str, sizes: list[int], seconds: float) -> int:
    t = open_transport(spec, **({"wait": 10.0} if spec.startswith("usb") else {}))
    link = Link(t, name="usb_probe")
    peer = link.handshake(timeout=2, attempts=15)
    print(f"peer: {peer.name!r} role={peer.role} app={peer.app} max_payload={peer.max_payload}")
    rtts = [link.ping(timeout=2) * 1e3 for _ in range(50)]
    print(f"RESULT {spec} ping rtt ms: min {min(rtts):.2f} median {statistics.median(rtts):.2f} max {max(rtts):.2f}")
    for size in sizes:
        size = min(size, peer.max_payload)
        payload = bytes(i & 0xFF for i in range(size))
        n, t0 = 0, time.perf_counter()
        while time.perf_counter() - t0 < seconds:
            link.send(0xF1, payload)
            f = link.wait_for(0xF1, 5)
            if f is None or f.payload != payload:
                print(f"RESULT {spec} echo {size} B: FAILED (got {None if f is None else len(f.payload)})")
                return 2
            n += 1
        dt = time.perf_counter() - t0
        print(f"RESULT {spec} echo {size} B: {n / dt:.1f} round trips/s, {size * n / dt / 1e6:.2f} MB/s each way")
    link.close()
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["list", "echo"])
    ap.add_argument("--spec", default="usb", help="usb | hostfs | mock | tcp:H:P")
    ap.add_argument("--sizes", default="512,4096,16384,65000")
    ap.add_argument("--seconds", type=float, default=2.0, help="per size")
    a = ap.parse_args(argv)
    if a.cmd == "list":
        return cmd_list()
    return cmd_echo(a.spec, [int(x) for x in a.sizes.split(",")], a.seconds)


if __name__ == "__main__":
    sys.exit(main())
