"""Mac-side byte transports. The framing lives in link.py; a transport only moves bytes.

* TcpTransport        – client; connects to tools/fake_psp.py (the mock PSP) or to a host build of
                        PSP C code (common/psp/io_posix_tcp.c).
* TcpServerTransport  – server; used by fake_psp.py to play the PSP side.
* UsbTransport        – real PSP via libusb/pyusb (vendor-specific interface of pspmaclink.prx).

Spec strings for open_transport():
  "mock"          = tcp:127.0.0.1:47100 (tools/fake_psp.py)
  "hostfs"        = tcp:127.0.0.1:10004 — real PSP through psplink's usbhostfs: run `usbhostfs_pc`
                    (pspdev toolchain) first; it exposes usbhostfs async channel 4 on that port
  "tcp:HOST:PORT" = any TCP peer
  "usb"           = real PSP through our pspmaclink.prx (pyusb), "usb:VID:PID" (hex) to override
"""
from __future__ import annotations

import abc
import socket
import time

from . import protocol as P

MOCK_HOST = "127.0.0.1"
MOCK_PORT = 47100
HOSTFS_PORT = 10004  # usbhostfs_pc base port 10000 + async channel 4 (ASYNC_USER)


class Transport(abc.ABC):
    @abc.abstractmethod
    def write(self, data: bytes) -> None:
        """Write all bytes or raise ConnectionError."""

    @abc.abstractmethod
    def read(self, max_bytes: int = 65536, timeout: float | None = 0.1) -> bytes:
        """Return up to max_bytes; b"" on timeout. Raise ConnectionError if the peer is gone."""

    @abc.abstractmethod
    def close(self) -> None: ...

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class _SocketTransport(Transport):
    sock: socket.socket

    def write(self, data: bytes) -> None:
        try:
            self.sock.sendall(data)
        except OSError as e:
            raise ConnectionError(str(e)) from e

    def read(self, max_bytes: int = 65536, timeout: float | None = 0.1) -> bytes:
        self.sock.settimeout(timeout)
        try:
            d = self.sock.recv(max_bytes)
        except socket.timeout:
            return b""
        except OSError as e:
            raise ConnectionError(str(e)) from e
        if not d:
            raise ConnectionError("peer closed")
        return d

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


class TcpTransport(_SocketTransport):
    def __init__(self, host: str = MOCK_HOST, port: int = MOCK_PORT, connect_timeout: float = 10.0):
        deadline = time.monotonic() + connect_timeout
        last: Exception | None = None
        while time.monotonic() < deadline:
            try:
                self.sock = socket.create_connection((host, port), timeout=1.0)
                self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                return
            except OSError as e:
                last = e
                time.sleep(0.1)
        raise ConnectionError(f"cannot connect to {host}:{port}: {last}")


class TcpServerTransport(_SocketTransport):
    """Listens and accepts a single client. Call accept() (blocking) before read/write."""

    def __init__(self, host: str = MOCK_HOST, port: int = MOCK_PORT):
        self.lsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.lsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.lsock.bind((host, port))
        self.lsock.listen(1)
        self.port = self.lsock.getsockname()[1]

    def accept(self, timeout: float | None = None) -> None:
        self.lsock.settimeout(timeout)
        self.sock, _ = self.lsock.accept()
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    def close(self) -> None:
        super().close() if hasattr(self, "sock") else None
        self.lsock.close()


def _libusb_backend():
    """pyusb needs libusb-1.0; on Apple Silicon Homebrew puts it in /opt/homebrew/lib."""
    import usb.backend.libusb1 as lb

    for path in (None, "/opt/homebrew/lib/libusb-1.0.dylib", "/usr/local/lib/libusb-1.0.dylib"):
        be = lb.get_backend(find_library=(lambda _n, p=path: p) if path else None)
        if be is not None:
            return be
    raise RuntimeError("libusb-1.0 not found: brew install libusb")


class UsbTransport(Transport):
    """Talks to pspmaclink.prx (vendor class 0xFF, bulk IN 0x81, bulk OUT 0x02).

    The PSP side completes a bulk-OUT request on a short packet, so writes whose length is a
    multiple of the endpoint packet size are split (len-1, 1) to always end on a short packet
    (macOS libusb cannot send zero-length packets automatically)."""

    def __init__(self, vid: int = P.USB_VID, pid: int = P.USB_PID, wait: float = 0.0):
        import usb.core
        import usb.util

        self._usb = usb
        be = _libusb_backend()
        deadline = time.monotonic() + wait
        while True:
            self.dev = usb.core.find(idVendor=vid, idProduct=pid, backend=be)
            if self.dev is not None or time.monotonic() >= deadline:
                break
            time.sleep(0.25)
        if self.dev is None:
            raise ConnectionError(
                f"PSP not found on USB (VID {vid:04x} PID {pid:04x}); is the PSP app running and the cable in?"
            )
        try:
            self.dev.set_configuration()
        except usb.core.USBError:
            pass  # already configured
        usb.util.claim_interface(self.dev, 0)
        intf = self.dev.get_active_configuration()[(0, 0)]
        self.ep_in = usb.util.find_descriptor(intf, bEndpointAddress=P.USB_EP_IN)
        self.ep_out = usb.util.find_descriptor(intf, bEndpointAddress=P.USB_EP_OUT)
        if self.ep_in is None or self.ep_out is None:
            raise ConnectionError("PSP USB endpoints 0x81/0x02 not found")
        self.mps = self.ep_out.wMaxPacketSize or 512

    def write(self, data: bytes) -> None:
        mv = memoryview(bytes(data))
        chunk = 64 * 1024
        try:
            while mv:
                part = mv[:chunk]
                mv = mv[chunk:]
                if len(part) % self.mps == 0:
                    self.ep_out.write(part[:-1], timeout=2000)
                    self.ep_out.write(part[-1:], timeout=2000)
                else:
                    self.ep_out.write(part, timeout=2000)
        except self._usb.core.USBError as e:
            raise ConnectionError(str(e)) from e

    def read(self, max_bytes: int = 65536, timeout: float | None = 0.1) -> bytes:
        ms = 0 if timeout is None else max(1, int(timeout * 1000))
        try:
            return bytes(self.ep_in.read(max_bytes, timeout=ms))
        except self._usb.core.USBTimeoutError:
            return b""
        except self._usb.core.USBError as e:
            if getattr(e, "errno", None) in (60, 110):  # ETIMEDOUT on some backends
                return b""
            raise ConnectionError(str(e)) from e

    def close(self) -> None:
        try:
            self._usb.util.release_interface(self.dev, 0)
            self._usb.util.dispose_resources(self.dev)
        except Exception:
            pass


def open_transport(spec: str = "mock", **kw) -> Transport:
    if spec == "mock":
        return TcpTransport(MOCK_HOST, MOCK_PORT, **kw)
    if spec == "hostfs":
        return TcpTransport(MOCK_HOST, HOSTFS_PORT, **kw)
    if spec.startswith("tcp:"):
        _, host, port = spec.split(":")
        return TcpTransport(host, int(port), **kw)
    if spec == "usb":
        return UsbTransport(**kw)
    if spec.startswith("usb:"):
        _, vid, pid = spec.split(":")
        return UsbTransport(int(vid, 16), int(pid, 16), **kw)
    raise ValueError(f"unknown transport spec {spec!r}")
