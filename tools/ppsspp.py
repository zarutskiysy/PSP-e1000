#!/usr/bin/env python3
"""ppsspp.py — drive PPSSPP (1.20.4, macOS SDL build) from scripts via its WebSocket debugger.

PPSSPP runs with a sandboxed HOME (<repo>/.ppsspp_home/<port>/) so the user's own emulator config
is never touched; the generated ppsspp.ini enables the remote debugger on a fixed port.

CLI:
  python tools/ppsspp.py run path/EBOOT.PBP [--port 45677]   # start (detached), wait for debugger
  python tools/ppsspp.py shot out.png [--port ...]              # screenshot (pauses CPU briefly)
  python tools/ppsspp.py press cross [--frames 2]               # press+release a button
  python tools/ppsspp.py hold cross,ltrigger / release cross    # set button state
  python tools/ppsspp.py analog 0.5 -1.0                        # left stick (-1..1, +y = up: y=-1 -> Ly=255); 0 0 centers
  python tools/ppsspp.py status | quit

Library: `from ppsspp import Ppsspp; emu = Ppsspp.launch(eboot, port); emu.screenshot("a.png"); emu.quit()`

Debugger API (PPSSPP v1.20.4 source, Core/Debugger/WebSocket/*.cpp): endpoint ws://HOST:PORT/debugger,
subprotocol "debugger.ppsspp.org"; gpu.buffer.screenshot only works while the CPU is stepping, so
shot = cpu.stepping -> gpu.buffer.screenshot(type=uri) -> cpu.resume.
If several worktrees run PPSSPP at once, give each its own --port.
"""
from __future__ import annotations

import argparse
import base64
import itertools
import json
import os
import pathlib
import signal
import socket
import subprocess
import sys
import time

import websocket  # websocket-client

ROOT = pathlib.Path(__file__).resolve().parents[1]
PPSSPP_BIN = os.environ.get("PPSSPP_BIN", "/Applications/PPSSPPSDL.app/Contents/MacOS/PPSSPPSDL")
DEFAULT_PORT = int(os.environ.get("PPSSPP_PORT", "45677"))

INI = """[General]
FirstRun = False
CheckForNewVersion = False
DiscordRichPresence = False
RemoteDebuggerOnStartup = True
RemoteDebuggerLocal = True
RemoteISOPort = {port}
PauseOnLostFocus = False
PauseWhenMinimized = False
[Graphics]
FrameSkip = 0
GraphicsBackend = 0 (OPENGL)
SoftwareRendering = True
[Network]
EnableWlan = False
"""


def sandbox(port: int) -> pathlib.Path:
    return ROOT / ".ppsspp_home" / str(port)


def _port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.2)
        return s.connect_ex(("127.0.0.1", port)) == 0


class Ppsspp:
    def __init__(self, port: int = DEFAULT_PORT, timeout: float = 10.0):
        self.port = port
        self.ws = websocket.create_connection(
            f"ws://127.0.0.1:{port}/debugger", subprotocols=["debugger.ppsspp.org"], timeout=timeout
        )
        self._tickets = itertools.count(1)

    # -- process management -------------------------------------------------
    @classmethod
    def launch(cls, eboot: str | os.PathLike, port: int = DEFAULT_PORT, wait: float = 20.0,
               log: str | os.PathLike | None = None) -> "Ppsspp":
        home = sandbox(port)
        sysdir = home / ".config/ppsspp/PSP/SYSTEM"
        sysdir.mkdir(parents=True, exist_ok=True)
        (sysdir / "ppsspp.ini").write_text(INI.format(port=port))
        if _port_open(port):
            raise RuntimeError(f"port {port} already in use (another PPSSPP?): `ppsspp.py quit --port {port}`")
        env = dict(os.environ, HOME=str(home))
        logf = open(log or home / "ppsspp.log", "wb")
        proc = subprocess.Popen([PPSSPP_BIN, "--windowed", "--pause-menu-exit", str(pathlib.Path(eboot).resolve())],
                                env=env, stdout=logf, stderr=subprocess.STDOUT, start_new_session=True)
        (home / "pid").write_text(str(proc.pid))
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise RuntimeError(f"PPSSPP exited with {proc.returncode}; see {logf.name}")
            if _port_open(port):
                emu = cls(port)
                emu.wait_running(max(1.0, deadline - time.monotonic()))
                return emu
            time.sleep(0.2)
        raise TimeoutError("PPSSPP debugger did not come up")

    @staticmethod
    def kill(port: int = DEFAULT_PORT) -> bool:
        pidf = sandbox(port) / "pid"
        if not pidf.exists():
            return False
        pid = int(pidf.read_text())
        try:
            os.kill(pid, signal.SIGTERM)
            for _ in range(30):
                time.sleep(0.1)
                os.kill(pid, 0)
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        pidf.unlink(missing_ok=True)
        return True

    def quit(self) -> None:
        try:
            self.ws.close()
        finally:
            self.kill(self.port)

    # -- protocol -------------------------------------------------------------
    def request(self, event: str, timeout: float = 10.0, _by_event: bool = False, **params) -> dict:
        """Send an event and wait for its reply (matched by ticket, or by event name when the
        reply is an untagged broadcast, as for cpu.stepping / cpu.resume)."""
        ticket = str(next(self._tickets))
        self.ws.send(json.dumps({"event": event, "ticket": ticket, **params}))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.ws.settimeout(max(0.05, deadline - time.monotonic()))
            msg = json.loads(self.ws.recv())
            if msg.get("ticket") == ticket or (_by_event and msg.get("event") == event):
                if msg.get("event") == "error":
                    raise RuntimeError(f"{event}: {msg.get('message')}")
                return msg
        raise TimeoutError(event)

    def batch(self, reqs: list[tuple[str, dict]], timeout: float = 10.0) -> list[dict]:
        """Pipeline several requests in one go (PPSSPP handles all queued requests in one Process()
        tick, ~16 ms), then collect the replies in order. Much faster than one request() each."""
        tickets = []
        for event, params in reqs:
            t = str(next(self._tickets))
            tickets.append(t)
            self.ws.send(json.dumps({"event": event, "ticket": t, **params}))
        replies: dict[str, dict] = {}
        deadline = time.monotonic() + timeout
        while len(replies) < len(tickets):
            if time.monotonic() > deadline:
                raise TimeoutError(f"batch: {len(replies)}/{len(tickets)} replies")
            self.ws.settimeout(max(0.05, deadline - time.monotonic()))
            msg = json.loads(self.ws.recv())
            t = msg.get("ticket")
            if t in tickets:
                if msg.get("event") == "error":
                    raise RuntimeError(f"batch: {msg.get('message')}")
                replies[t] = msg
        return [replies[t] for t in tickets]

    def status(self) -> dict:
        return self.request("game.status")

    def wait_running(self, timeout: float = 10.0) -> dict:
        deadline = time.monotonic() + timeout
        st: dict = {}
        while time.monotonic() < deadline:
            st = self.status()
            if st.get("game"):
                return st
            time.sleep(0.2)
        raise TimeoutError(f"game not running: {st}")

    def screenshot(self, path: str | os.PathLike | None = None, fb: str | None = None) -> bytes:
        """PNG of the PSP screen. Tries PPSSPP's gpu.buffer.screenshot first; that fails for apps
        that draw straight into VRAM without the GE (e.g. pspDebugScreen), so it falls back to
        reading the framebuffer from emulated memory: fb = "ADDR:FMT:STRIDE", FMT 8888|565|5551|4444,
        default "0x04000000:8888:512" (pspDebugScreen's buffer)."""
        png = None
        self.request("cpu.stepping", _by_event=True)
        try:
            if fb is None:
                try:
                    r = self.request("gpu.buffer.screenshot", type="uri")
                    png = base64.b64decode(r["uri"].split(",", 1)[1])
                except RuntimeError:
                    fb = "0x04000000:8888:512"
            if png is None:
                png = self._fb_png(fb)
        finally:
            self.request("cpu.resume", _by_event=True)
        if path:
            pathlib.Path(path).write_bytes(png)
        return png

    def _fb_png(self, fb: str) -> bytes:
        import io

        from PIL import Image

        addr_s, fmt, stride_s = fb.split(":")
        addr, stride = int(addr_s, 0), int(stride_s)
        bpp = 4 if fmt == "8888" else 2
        raw = self.read(addr, stride * 272 * bpp)
        if bpp == 4:
            img = Image.frombuffer("RGBA", (stride, 272), raw, "raw", "RGBA", 0, 1).convert("RGB")
        else:
            px = bytearray()
            for i in range(0, len(raw), 2):
                v = raw[i] | (raw[i + 1] << 8)
                if fmt == "565":
                    r, g, b = (v & 31) << 3, ((v >> 5) & 63) << 2, ((v >> 11) & 31) << 3
                elif fmt == "5551":
                    r, g, b = (v & 31) << 3, ((v >> 5) & 31) << 3, ((v >> 10) & 31) << 3
                else:  # 4444
                    r, g, b = (v & 15) << 4, ((v >> 4) & 15) << 4, ((v >> 8) & 15) << 4
                px += bytes((r, g, b))
            img = Image.frombytes("RGB", (stride, 272), bytes(px))
        img = img.crop((0, 0, 480, 272))
        out = io.BytesIO()
        img.save(out, "PNG")
        return out.getvalue()

    def press(self, button: str, frames: int = 2) -> None:
        self.request("input.buttons.press", button=button, duration=frames)

    def buttons(self, **state: bool) -> None:
        self.request("input.buttons.send", buttons=state)

    def analog(self, x: float, y: float, stick: str = "left") -> None:
        self.request("input.analog.send", x=x, y=y, stick=stick)

    # memory access (used by tools/ppsspp_bridge.py)
    def read(self, address: int, size: int) -> bytes:
        return base64.b64decode(self.request("memory.read", address=address, size=size)["base64"])

    def write(self, address: int, data: bytes) -> None:
        self.request("memory.write", address=address, base64=base64.b64encode(data).decode())

    def read_u32(self, address: int) -> int:
        return int(self.request("memory.read_u32", address=address)["value"])

    def write_u32(self, address: int, value: int) -> None:
        self.request("memory.write_u32", address=address, value=value)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["run", "shot", "press", "hold", "release", "analog", "status", "quit"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--frames", type=int, default=2)
    ap.add_argument("--fb", help='shot: read framebuffer from memory "ADDR:FMT:STRIDE" (e.g. 0x04000000:565:512)')
    a = ap.parse_args(argv)
    if a.cmd == "run":
        emu = Ppsspp.launch(a.args[0], a.port)
        print(json.dumps(emu.status()))
        return 0
    if a.cmd == "quit":
        print("killed" if Ppsspp.kill(a.port) else "not running")
        return 0
    emu = Ppsspp(a.port)
    if a.cmd == "shot":
        emu.screenshot(a.args[0], a.fb)
        print(a.args[0])
    elif a.cmd == "press":
        emu.press(a.args[0], a.frames)
    elif a.cmd in ("hold", "release"):
        emu.buttons(**{b: a.cmd == "hold" for b in a.args[0].split(",")})
    elif a.cmd == "analog":
        emu.analog(float(a.args[0]), float(a.args[1]))
    elif a.cmd == "status":
        print(json.dumps(emu.status()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
