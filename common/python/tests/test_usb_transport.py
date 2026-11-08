"""UsbTransport without hardware: fake endpoints model the deadlock found on a real PSP."""
import pathlib
import sys
import threading
import time
import types

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "common" / "python"))

from pspmac.transport import UsbTransport  # noqa: E402


class FakeTimeout(Exception):
    pass


class FakeUSBError(Exception):
    errno = None


FAKE_USB = types.SimpleNamespace(
    core=types.SimpleNamespace(USBError=FakeUSBError, USBTimeoutError=FakeTimeout),
    util=types.SimpleNamespace(release_interface=lambda *a: None, dispose_resources=lambda *a: None),
)


class FakeEpIn:
    def __init__(self):
        self.items = []
        self.called = threading.Event()
        self.lock = threading.Lock()
        self.error = None

    def push(self, b):
        with self.lock:
            self.items.append(b)

    def read(self, n, timeout):
        self.called.set()
        if self.error:
            raise self.error
        with self.lock:
            if self.items:
                return self.items.pop(0)
        time.sleep(0.005)
        raise FakeTimeout()


class FakeEpOut:
    """Like the real PSP: an OUT write completes only once an IN read has drained the PSP's pending send."""

    def __init__(self, ep_in):
        self.ep_in = ep_in
        self.written = []

    def write(self, data, timeout):
        if not self.ep_in.called.wait(timeout / 1000):
            raise FakeTimeout()
        self.written.append(bytes(data))


def make_transport():
    t = UsbTransport.__new__(UsbTransport)
    t._usb = FAKE_USB
    t.dev = object()
    t.ep_in = FakeEpIn()
    t.ep_out = FakeEpOut(t.ep_in)
    t.mps = 512
    t._start_reader()
    return t


def test_write_does_not_deadlock_without_an_explicit_read():
    t = make_transport()
    try:
        t0 = time.monotonic()
        t.write(b"x" * 1000)  # nobody calls t.read(): the background reader must service IN
        assert time.monotonic() - t0 < 1.0
        assert b"".join(t.ep_out.written) == b"x" * 1000
    finally:
        t.close()


def test_read_returns_queued_data_splits_oversize_and_times_out():
    t = make_transport()
    try:
        t.ep_in.push(b"abcdef")
        assert t.read(4, timeout=1.0) == b"abcd"
        assert t.read(4, timeout=1.0) == b"ef"
        assert t.read(4, timeout=0.02) == b""
    finally:
        t.close()


def test_usb_error_surfaces_as_connection_error():
    t = make_transport()
    try:
        t.ep_in.error = FakeUSBError("gone")
        with pytest.raises(ConnectionError, match="gone"):
            t.read(16, timeout=1.0)
    finally:
        t.close()


def test_write_still_splits_full_packet_lengths():
    t = make_transport()
    try:
        t.write(b"y" * 1024)
        assert [len(w) for w in t.ep_out.written] == [1023, 1]
    finally:
        t.close()
