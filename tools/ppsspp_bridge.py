#!/usr/bin/env python3
"""ppsspp_bridge.py — connect a PSP app running in PPSSPP to Mac code over the mock TCP port.

The PSP app uses common/psp/io_mailbox.c (two byte rings in PSP RAM). This bridge finds the
mailbox through PPSSPP's WebSocket debugger, then shuttles bytes between it and one TCP client:

    Mac app --TCP 127.0.0.1:47100--> bridge --memory.read/write over ws://:45677--> PSP app in PPSSPP

So the Mac side uses transport spec "mock" (or tcp:127.0.0.1:<listen>) exactly as with fake_psp.py.

    python tools/ppsspp.py run examples/emu_echo/EBOOT.PBP
    python tools/ppsspp_bridge.py [--port 45677] [--listen 47100]

Throughput is limited by the debugger round trips (each poll = a few WebSocket requests); see
docs/SETUP.md for measured numbers. Real hardware uses USB instead (common/psp/usb).
"""
from __future__ import annotations

import argparse
import pathlib
import socket
import struct
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from ppsspp import DEFAULT_PORT, Ppsspp  # noqa: E402

MAGIC = b"PSPMACLINK/MBOX1"
HDR = struct.Struct("<16sIIIIIIIIII8x")  # 64 bytes
assert HDR.size == 64
OFF_M2P_HEAD, OFF_P2M_TAIL, OFF_BRIDGE_BEAT = 32, 44, 48
USER_RAM = (0x08800000, 0x0A000000)
DEBUG = bool(int(__import__("os").environ.get("BRIDGE_DEBUG", "0")))


class Mailbox:
    """Bridge end of common/psp/io_mailbox.c. The bridge is the only writer of m2p_head and
    p2m_tail, so it tracks them locally and each poll is ONE pipelined debugger round trip
    (writes + header read), plus one more only when the PSP has sent data."""

    KEYS = ["magic", "self", "version", "m2p_cap", "p2m_cap", "m2p_head", "m2p_tail", "p2m_head", "p2m_tail",
            "bridge_beat", "psp_beat"]

    def __init__(self, emu: Ppsspp, addr: int):
        self.emu, self.addr = emu, addr
        h = self.header()
        self.m2p_cap, self.p2m_cap = h["m2p_cap"], h["p2m_cap"]
        self.m2p = addr + 64
        self.p2m = self.m2p + self.m2p_cap
        self.beat = h["bridge_beat"]
        self.m2p_head = h["m2p_head"]
        self.p2m_tail = h["p2m_tail"]
        self.last = h

    def _parse(self, b64: str) -> dict:
        import base64

        return dict(zip(self.KEYS, HDR.unpack(base64.b64decode(b64))))

    def header(self) -> dict:
        return dict(zip(self.KEYS, HDR.unpack(self.emu.read(self.addr, 64))))

    @staticmethod
    def _split(base: int, cap: int, pos: int, n: int) -> list[tuple[int, int, int]]:
        """[(address, offset_in_data, length)] for a ring access that may wrap."""
        i = pos % cap
        first = min(n, cap - i)
        parts = [(base + i, 0, first)]
        if n > first:
            parts.append((base, first, n - first))
        return parts

    def poll(self, outgoing: bytearray, max_chunk: int = 65536) -> bytes:
        """One exchange: returns PSP->Mac bytes, moves as much of `outgoing` as fits into the PSP."""
        import base64

        reqs: list[tuple[str, dict]] = []
        if outgoing:
            room = self.m2p_cap - ((self.m2p_head - self.last["m2p_tail"]) & 0xFFFFFFFF)
            n = min(room, len(outgoing), max_chunk)
            if n > 0:
                data = bytes(outgoing[:n])
                for addr, off, ln in self._split(self.m2p, self.m2p_cap, self.m2p_head, n):
                    reqs.append(("memory.write", {"address": addr, "base64": base64.b64encode(data[off:off + ln]).decode()}))
                self.m2p_head = (self.m2p_head + n) & 0xFFFFFFFF
                reqs.append(("memory.write_u32", {"address": self.addr + OFF_M2P_HEAD, "value": self.m2p_head}))
                del outgoing[:n]
        self.beat = (self.beat + 1) & 0xFFFFFFFF or 1
        reqs.append(("memory.write_u32", {"address": self.addr + OFF_BRIDGE_BEAT, "value": self.beat}))
        reqs.append(("memory.read", {"address": self.addr, "size": 64}))
        h = self._parse(self.emu.batch(reqs)[-1]["base64"])
        self.last = h
        avail = (h["p2m_head"] - self.p2m_tail) & 0xFFFFFFFF
        if not avail:
            return b""
        n = min(avail, max_chunk)
        parts = self._split(self.p2m, self.p2m_cap, self.p2m_tail, n)
        self.p2m_tail = (self.p2m_tail + n) & 0xFFFFFFFF
        reps = self.emu.batch([("memory.read", {"address": a, "size": ln}) for a, _, ln in parts]
                              + [("memory.write_u32", {"address": self.addr + OFF_P2M_TAIL, "value": self.p2m_tail})])
        return b"".join(base64.b64decode(r["base64"]) for r in reps[:-1])

    def drain(self) -> None:
        h = self.header()
        self.p2m_tail = h["p2m_head"]
        self.emu.write_u32(self.addr + OFF_P2M_TAIL, self.p2m_tail)
        self.last = h


def find_mailbox(emu: Ppsspp, timeout: float = 15.0, chunk: int = 1 << 20) -> int:
    """Scan user RAM for the magic; verify the self pointer to skip the string literal copy."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for base in range(USER_RAM[0], USER_RAM[1], chunk):
            data = emu.read(base, chunk + 64)
            i = data.find(MAGIC)
            while i >= 0:
                addr = base + i
                (self_ptr,) = struct.unpack_from("<I", data, i + 16) if i + 20 <= len(data) else (0,)
                if addr % 64 == 0 and (self_ptr & 0x1FFFFFFF) == (addr & 0x1FFFFFFF):
                    return addr
                i = data.find(MAGIC, i + 1)
        time.sleep(0.5)
    raise TimeoutError("mailbox not found in PSP RAM (is the PSP app using io_mailbox and running?)")


def serve(emu_port: int, listen_host: str, listen_port: int, idle_sleep: float, once: bool, quiet: bool) -> int:
    log = (lambda *_: None) if quiet else (lambda *a: print("[bridge]", *a, flush=True))
    # PPSSPP drops debugger WebSockets that sit idle (we don't answer its pings while blocked in
    # accept()), so we use a fresh debugger connection per TCP client and keep it busy.
    emu = Ppsspp(emu_port)
    addr = find_mailbox(emu)
    log(f"mailbox at 0x{addr:08X}")
    emu.ws.close()
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((listen_host, listen_port))
    srv.listen(1)
    print(f"LISTEN {srv.getsockname()[1]}", flush=True)
    while True:
        cli, _ = srv.accept()
        cli.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        cli.setblocking(False)
        log("client connected")
        emu = Ppsspp(emu_port)
        try:
            mb = Mailbox(emu, addr)
        except Exception:
            addr = find_mailbox(emu)  # app restarted: the mailbox may have moved
            mb = Mailbox(emu, addr)
        mb.drain()
        outgoing = bytearray()
        polls, t0, up, down = 0, time.monotonic(), 0, 0
        try:
            while True:
                try:
                    d = cli.recv(65536)
                    if not d:
                        break
                    outgoing += d
                    down += len(d)
                except BlockingIOError:
                    pass
                got = mb.poll(outgoing)
                polls += 1
                if DEBUG:
                    h = mb.last
                    log(f"poll {polls}: got {len(got)} out {len(outgoing)} m2p {h['m2p_head']}/{h['m2p_tail']} "
                        f"p2m {h['p2m_head']}/{h['p2m_tail']} local {mb.m2p_head}/{mb.p2m_tail}")
                if got:
                    cli.setblocking(True)
                    cli.sendall(got)
                    cli.setblocking(False)
                    up += len(got)
                if not got and not outgoing:
                    time.sleep(idle_sleep)
        except (ConnectionError, OSError) as e:
            log(f"client error: {e}")
        except Exception as e:  # websocket closed by PPSSPP (e.g. game restarted)
            log(f"emulator link error: {e!r}")
        dt = time.monotonic() - t0
        log(f"client gone after {dt:.1f}s, {polls} polls ({polls / max(dt, 1e-9):.0f}/s), "
            f"{up} B psp->mac, {down} B mac->psp")
        cli.close()
        try:
            emu.ws.close()
        except Exception:
            pass
        if once:
            return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help="PPSSPP debugger port")
    ap.add_argument("--listen", type=int, default=47100, help="TCP port for the Mac app (0 = random)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--idle-sleep", type=float, default=0.02,
                    help="seconds between idle polls; polling harder stalls the emulated CPU")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    return serve(a.port, a.host, a.listen, a.idle_sleep, a.once, a.quiet)


if __name__ == "__main__":
    sys.exit(main())
