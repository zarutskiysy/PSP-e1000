#!/usr/bin/env python3
"""psp_screen.py — stream a 480x272 picture from the Mac to the PSP (feat/second-screen).

  send   (default)  capture/generate frames, encode (PSP 565 + 16x16 dirty tiles + optional LZ4), send
  probe             Mac->PSP throughput probe at several USB transfer sizes (run on hardware)
  bench             codec benchmark per source: bytes/frame, encode ms (no link needed)

Transports (--transport): mock (tools/fake_psp.py or the PPSSPP bridge, 127.0.0.1:47100),
usb (real PSP, pspmaclink.prx, pyusb), hostfs (real PSP via usbhostfs_pc :10004), tcp:H:P,
record:FILE (write the byte stream to a file; the PSP app can replay it in emulator demo mode).

Examples:
  python screen/mac/psp_screen.py --transport mock --source test-pattern --fps 30
  python screen/mac/psp_screen.py --transport usb --source screen:0,0 --fps 30
  python screen/mac/psp_screen.py probe --transport usb --sizes 16,64,256 --mb 8
  python screen/mac/psp_screen.py bench --frames 120
"""
from __future__ import annotations

import argparse
import pathlib
import struct
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "common" / "python"))

import numpy as np  # noqa: E402

from pspmac import protocol as P  # noqa: E402
from pspmac.link import Link  # noqa: E402
from pspmac.transport import Transport, UsbTransport, open_transport  # noqa: E402

import proto_screen as S  # noqa: E402
from screencodec import Encoder, psp565_to_rgb  # noqa: E402
from sources import make_source  # noqa: E402


class FileTransport(Transport):
    """record:FILE — every byte that would go to the PSP is appended to FILE; nothing comes back."""

    def __init__(self, path: str):
        self.f = open(path, "wb")

    def write(self, data: bytes) -> None:
        self.f.write(data)

    def read(self, max_bytes: int = 65536, timeout: float | None = 0.1) -> bytes:
        return b""

    def close(self) -> None:
        self.f.close()


def open_any(spec: str, wait: float = 0.0) -> Transport:
    if spec.startswith("record:"):
        return FileTransport(spec[7:])
    if spec.startswith("usb"):
        return open_transport(spec, wait=wait)
    return open_transport(spec)


def save_png(frame565: np.ndarray, path: str) -> None:
    from PIL import Image
    Image.fromarray(psp565_to_rgb(frame565)).save(path)


# --------------------------------------------------------------------------------------------- send
HOSTFS_MAX_CHUNK = 3000  # usbhostfs keeps a 4 KiB Mac->PSP async ring and drops overflow (usbasync.h)


def apply_transport_defaults(a) -> None:
    """HOSTFS can only buffer 4 KiB on the PSP: small chunks, stop-and-wait per chunk, one frame in flight."""
    hostfs = a.transport == "hostfs"
    if a.max_chunk is None:
        a.max_chunk = HOSTFS_MAX_CHUNK if hostfs else 0
    if a.chunk_ack is None:
        a.chunk_ack = hostfs
    if a.chunk_ack:
        a.window = 1


def connect(a):
    """Opens the transport and does the HELLO handshake. Returns (link, max_payload)."""
    t = open_any(a.transport, a.usb_wait)
    link = Link(t, app=P.APP_SCREEN, name="mac-screen")
    max_payload = S.SCR_MAX_PAYLOAD
    if not a.transport.startswith("record:"):
        try:
            peer = link.handshake(timeout=a.handshake_timeout)
        except Exception:
            link.close(bye=False)
            raise
        if peer.app != P.APP_SCREEN:
            print(f"[warn] peer app id {peer.app} (expected {P.APP_SCREEN}: screen); continuing", flush=True)
        max_payload = min(S.SCR_MAX_PAYLOAD, peer.max_payload)
        print(f"[psp_screen] peer '{peer.name}' max_payload={peer.max_payload}", flush=True)
    if a.max_chunk:
        max_payload = min(max_payload, a.max_chunk)
    return link, max_payload


def reconnect(a):
    deadline = time.monotonic() + a.reconnect
    while time.monotonic() < deadline:
        try:
            return connect(a)
        except (ConnectionError, TimeoutError, OSError, RuntimeError):
            time.sleep(1.0)
    return None


def cmd_send(a) -> int:
    apply_transport_defaults(a)
    src = make_source(a.source, a.capture)
    recording = a.transport.startswith("record:")
    try:
        link, max_payload = connect(a)
    except (ConnectionError, TimeoutError) as e:
        print(f"[psp_screen] cannot connect over '{a.transport}': {e}", flush=True)
        return 2
    enc = Encoder(lz4=a.lz4, max_payload=max_payload)
    print(f"[psp_screen] source={getattr(src, 'name', a.source)} transport={a.transport} fps={a.fps} "
          f"window={a.window} lz4={a.lz4} chunks<={max_payload} B chunk_ack={a.chunk_ack}", flush=True)

    inflight: dict[int, float] = {}
    chunk_acks: set[tuple[int, int]] = set()
    force_key = False
    last_key = time.monotonic()
    stats = dict(frames=0, acked=0, wire=0, enc_ms=0.0, dec_us=0, rtt=0.0, skipped=0, keys=0)
    last_ack: S.Ack | None = None
    t_start = t_stat = time.monotonic()
    n = 0
    period = 1.0 / a.fps if a.fps > 0 else 0.0
    next_t = time.perf_counter()
    last_frame = None
    rc = 0

    def handle(f):
        nonlocal force_key, last_ack
        if f.type == S.SCR_T_ACK and len(f.payload) >= S.SCR_ACK_SIZE:
            ack = S.Ack.unpack(f.payload)
            last_ack = ack
            sent = inflight.pop(ack.frame_id, None)
            # an ACK also releases older frames (their ACKs could have been lost)
            for k in [k for k in inflight if (ack.frame_id - k) & 0xFFFFFFFF < 0x80000000]:
                inflight.pop(k)
            if sent is not None:
                stats["acked"] += 1
                stats["rtt"] += time.monotonic() - sent
                stats["dec_us"] += ack.decode_us
            if ack.flags & S.SCR_ACKF_NEED_KEY:
                force_key = True
        elif f.type == S.SCR_T_CHUNK_ACK and len(f.payload) >= S.SCR_CHUNK_ACK_SIZE:
            chunk_acks.add(S.CHUNK_ACK.unpack_from(f.payload))
        elif f.type == P.T_LOG:
            print("[psp]", f.payload.decode(errors="replace"), flush=True)

    def send_chunks(chunks, fid) -> bool:
        """Sends one frame. With chunk_ack: stop-and-wait per chunk (HOSTFS). False = gave up on the frame."""
        nonlocal force_key
        for i, c in enumerate(chunks):
            last = i == len(chunks) - 1
            if not a.chunk_ack or last:
                link.send(S.SCR_T_CHUNK, c)
                continue
            link.send(S.SCR_T_CHUNK, c, flags=P.F_ACK_REQ)
            deadline = time.monotonic() + a.ack_timeout
            while (fid, i) not in chunk_acks:
                f = link.recv(0.05)
                if f is not None:
                    handle(f)
                if time.monotonic() > deadline:
                    print(f"[warn] no CHUNK_ACK for frame {fid} chunk {i}; abandoning the frame", flush=True)
                    force_key = True
                    return False
            chunk_acks.discard((fid, i))
        return True

    def drain_and_wait():
        nonlocal force_key
        while True:
            f = link.recv(0)
            if f is None:
                break
            handle(f)
        wait_start = time.monotonic()
        while len(inflight) >= a.window:
            f = link.recv(0.05)
            if f is not None:
                handle(f)
            if time.monotonic() - wait_start > a.ack_timeout:
                print(f"[warn] no ACK for {a.ack_timeout}s; dropping {len(inflight)} in-flight frame(s), "
                      "sending a keyframe", flush=True)
                inflight.clear()
                force_key = True

    while True:
        try:
            while a.frames <= 0 or n < a.frames:
                if a.duration > 0 and time.monotonic() - t_start > a.duration:
                    break
                if not recording:
                    drain_and_wait()  # flow control: at most `window` unacknowledged frames in flight
                frame = src.frame(n)
                key = force_key or (a.key_interval > 0 and time.monotonic() - last_key >= a.key_interval)
                chunks = enc.encode(frame, key=key)
                st = enc.last
                if st.key:
                    last_key, force_key = time.monotonic(), False
                    stats["keys"] += 1
                if chunks:
                    inflight[st.frame_id] = time.monotonic()
                    if not send_chunks(chunks, st.frame_id):
                        inflight.pop(st.frame_id, None)
                    stats["frames"] += 1
                    stats["wire"] += st.wire_bytes
                else:
                    stats["skipped"] += 1
                stats["enc_ms"] += st.encode_ms
                last_frame = frame
                n += 1
                now = time.monotonic()
                if now - t_stat >= a.stats_interval:
                    dt = now - t_stat
                    fr, ac = stats["frames"], max(1, stats["acked"])
                    psp = (f" | PSP fps {last_ack.fps_x10 / 10:.1f} dec {stats['dec_us'] / ac / 1000:.2f} ms "
                           f"rtt {stats['rtt'] / ac * 1000:.1f} ms err {last_ack.decode_errors}") if last_ack else ""
                    print(f"[stats] sent {fr / dt:5.1f} fps acked {stats['acked'] / dt:5.1f} fps "
                          f"{stats['wire'] / dt / 1e6:6.2f} MB/s {stats['wire'] / max(1, fr) / 1024:6.1f} KiB/frame "
                          f"enc {stats['enc_ms'] / max(1, fr + stats['skipped']):.2f} ms "
                          f"unchanged {stats['skipped']} keys {stats['keys']}{psp}", flush=True)
                    stats.update(frames=0, acked=0, wire=0, enc_ms=0.0, dec_us=0, rtt=0.0, skipped=0, keys=0)
                    t_stat = now
                if period:
                    next_t += period
                    dt = next_t - time.perf_counter()
                    if dt > 0:
                        time.sleep(dt)
                    else:
                        next_t = time.perf_counter()
            # drain the last ACKs so the PSP finished presenting before we say BYE
            if not recording:
                deadline = time.monotonic() + a.ack_timeout
                while inflight and time.monotonic() < deadline:
                    f = link.recv(0.05)
                    if f is not None:
                        handle(f)
            link.close(bye=not recording)
            break
        except KeyboardInterrupt:
            link.close(bye=not recording)
            break
        except ConnectionError as e:
            link.close(bye=False)
            if recording or a.reconnect <= 0:
                print(f"[psp_screen] link lost: {e}", flush=True)
                rc = 3
                break
            print(f"[psp_screen] link lost ({e}); reconnecting for up to {a.reconnect:.0f} s "
                  "(restart the PSP app / replug the cable)...", flush=True)
            r = reconnect(a)
            if r is None:
                print("[psp_screen] gave up reconnecting", flush=True)
                rc = 3
                break
            link, max_payload = r
            enc = Encoder(lz4=a.lz4, max_payload=max_payload)  # fresh encoder -> next frame is a keyframe
            inflight.clear()
            chunk_acks.clear()
            print("[psp_screen] reconnected; sending a keyframe", flush=True)
    if a.save_last and last_frame is not None:
        save_png(last_frame, a.save_last)
    print(f"[psp_screen] done: {n} frames", flush=True)
    return rc


# -------------------------------------------------------------------------------------------- probe
def cmd_probe(a) -> int:
    if a.transport == "hostfs":
        print("[probe] HOSTFS buffers only 4 KiB on the PSP and drops overflow, so a bulk probe is meaningless.\n"
              "        Link check: python tools/usb_probe.py echo --spec hostfs --sizes 512,2048")
        return 2
    t = open_any(a.transport, a.usb_wait)
    link = Link(t, app=P.APP_SCREEN, name="mac-probe")
    peer = link.handshake(timeout=a.handshake_timeout)
    if isinstance(t, UsbTransport):
        print(f"[probe] USB speed code: {getattr(t.dev, 'speed', '?')} (3 = High-Speed 480 Mbit/s)")
    payload = min(S.SCR_MAX_PAYLOAD, peer.max_payload) - 64
    total = int(a.mb * 1024 * 1024)
    print(f"[probe] peer '{peer.name}' max_payload={peer.max_payload}; frames of {payload} B, {a.mb} MiB per size")
    rows = []
    for tag, kb in enumerate(int(s) for s in a.sizes.split(",")):
        size = kb * 1024
        link.send(S.SCR_T_PROBE_RESET)
        nfr = max(1, total // (payload + P.OVERHEAD))
        blob = b"".join(P.encode(S.SCR_T_PROBE_DATA, bytes(payload), i) for i in range(nfr))
        t0 = time.perf_counter()
        mv = memoryview(blob)
        for off in range(0, len(blob), size):
            part = mv[off:off + size]
            if isinstance(t, UsbTransport) and len(part) == size:
                t.ep_out.write(part, timeout=5000)  # raw transfer of exactly `size` bytes
            else:
                t.write(bytes(part))  # last (short) part: transport guarantees a short packet
        link.send(S.SCR_T_PROBE_END, struct.pack("<I", tag))
        f = None
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            f = link.recv(0.5)
            if f is not None and f.type == S.SCR_T_PROBE_RESULT:
                break
        t1 = time.perf_counter()
        if f is None or f.type != S.SCR_T_PROBE_RESULT:
            print(f"[probe] {kb:4d} KiB: no PROBE_RESULT")
            continue
        r = S.ProbeResult.unpack(f.payload)
        mac_mbs = len(blob) / (t1 - t0) / 1e6
        # the PSP clock starts when the FIRST probe frame is complete, so its bytes are not in the interval
        first = payload + P.OVERHEAD
        psp_mbs = (r.bytes - first) / r.us if r.us else float("nan")
        rows.append((kb, len(blob), mac_mbs, r.bytes, psp_mbs, r.crc_errors))
        print(f"[probe] {kb:4d} KiB transfers: Mac wall {mac_mbs:6.2f} MB/s | PSP saw {r.bytes} B in "
              f"{r.us / 1000:.1f} ms = {psp_mbs:6.2f} MB/s, {r.frames} frames, crc_err {r.crc_errors}")
    print("\n| transfer | bytes sent | Mac wall MB/s | PSP-timed MB/s | CRC errors |\n|---|---|---|---|---|")
    for kb, nb, m, _, p, c in rows:
        print(f"| {kb} KiB | {nb} | {m:.2f} | {p:.2f} | {c} |")
    for r in rows:
        fps = r[2] * 1e6 / (S.SCR_W * S.SCR_H * 2)
        print(f"-> at {r[0]} KiB: raw full-frame ceiling {fps:.1f} fps")
    link.close()
    return 0


# -------------------------------------------------------------------------------------------- bench
def cmd_bench(a) -> int:
    sys.path.insert(0, str(ROOT / "tools"))
    from fake_psp_screen import CScreen  # the PSP decoder (scr_codec.c) via ctypes
    specs = a.sources.split(",")
    print("| source | lz4 | frames | avg KiB/frame | max KiB/frame | key KiB | avg dirty tiles | avg encode ms | "
          "C decode ms (Mac M-series) | link-only fps @8 MB/s | @16 MB/s |\n|---|---|---|---|---|---|---|---|---|---|---|")
    for spec in specs:
        src = make_source(spec)
        for mode in ("off", "auto"):
            enc = Encoder(lz4=mode)
            dec = CScreen()
            sizes, dirty, ems, dms, key_kb = [], [], [], [], 0.0
            for n in range(a.frames):
                fr = src.frame(n)
                chunks = enc.encode(fr, key=(n == 0))
                t0 = time.perf_counter()
                for c in chunks:
                    dec.chunk(c)
                dec.present()
                dms.append((time.perf_counter() - t0) * 1e3)
                if a.verify:
                    assert np.array_equal(dec.visible, fr), spec
                if n == 0:
                    key_kb = (enc.last.wire_bytes + 12 * enc.last.chunks) / 1024
                    continue
                sizes.append(enc.last.wire_bytes + 12 * enc.last.chunks)  # + link framing
                dirty.append(enc.last.dirty)
                ems.append(enc.last.encode_ms)
            avg = float(np.mean(sizes))
            fps8 = min(60.0, 8e6 / avg) if avg else 60.0
            fps16 = min(60.0, 16e6 / avg) if avg else 60.0
            print(f"| {spec} | {mode} | {a.frames - 1} | {avg / 1024:.1f} | {max(sizes) / 1024:.1f} | {key_kb:.1f} | "
                  f"{np.mean(dirty):.0f} | {np.mean(ems):.2f} | {np.mean(dms[1:]):.3f} | {fps8:.0f} | {fps16:.0f} |", flush=True)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", nargs="?", default="send", choices=["send", "probe", "bench"])
    ap.add_argument("--transport", default="mock", help="mock | usb | hostfs | tcp:H:P | record:FILE")
    ap.add_argument("--usb-wait", type=float, default=10.0, help="seconds to wait for the PSP to enumerate")
    ap.add_argument("--handshake-timeout", type=float, default=5.0)
    ap.add_argument("--source", default="test-pattern",
                    help="test-pattern | image:PATH | video-ish | screen[:X,Y[,W,H]] | window:TITLE")
    ap.add_argument("--capture", default="auto", choices=["auto", "sck", "mss"])
    ap.add_argument("--fps", type=float, default=30.0, help="target frame rate (0 = as fast as possible)")
    ap.add_argument("--window", type=int, default=2, help="max unacknowledged frames in flight")
    ap.add_argument("--ack-timeout", type=float, default=3.0)
    ap.add_argument("--lz4", default="auto", choices=["off", "on", "auto"])
    ap.add_argument("--key-interval", type=float, default=5.0, help="seconds between forced keyframes (0 = never)")
    ap.add_argument("--frames", type=int, default=0, help="stop after N frames (0 = forever)")
    ap.add_argument("--duration", type=float, default=0.0, help="stop after S seconds")
    ap.add_argument("--stats-interval", type=float, default=1.0)
    ap.add_argument("--save-last", help="write the last source frame (as the PSP should show it) to PNG")
    ap.add_argument("--max-chunk", type=int, default=None,
                    help=f"max SCR_CHUNK payload bytes (default 64 KiB; {HOSTFS_MAX_CHUNK} for hostfs)")
    ap.add_argument("--chunk-ack", action=argparse.BooleanOptionalAction, default=None,
                    help="stop-and-wait per chunk (default on for hostfs only; forces --window 1)")
    ap.add_argument("--reconnect", type=float, default=30.0,
                    help="seconds to keep trying to reconnect after the link drops (0 = exit)")
    # probe
    ap.add_argument("--sizes", default="16,64,256", help="probe: USB transfer sizes in KiB")
    ap.add_argument("--mb", type=float, default=8.0, help="probe: MiB per transfer size")
    # bench
    ap.add_argument("--sources", default="test-pattern,image:screen/tests/data/desktop.png,video-ish")
    ap.add_argument("--verify", action="store_true", help="bench: also decode and check pixel-exactness")
    a = ap.parse_args(argv)
    return {"send": cmd_send, "probe": cmd_probe, "bench": cmd_bench}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
