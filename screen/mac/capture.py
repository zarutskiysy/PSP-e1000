"""Real Mac screen capture for the second screen (needs the Screen Recording permission).

Backends (chosen with --capture, default "auto" = sck then mss):
  sck  ScreenCaptureKit one-shot screenshots: SCScreenshotManager.captureImageWithFilter:configuration:
       completionHandler: (macOS 14+), with SCStreamConfiguration.sourceRect + width/height 480x272 so
       the GPU does the scaling. Apple docs: https://developer.apple.com/documentation/screencapturekit
  mss  python-mss (CGWindowListCreateImage via ctypes; deprecated API, still exported on macOS 26).

Specs:  screen              top-left 480x272 points of the main display
        screen:X,Y          480x272 points at (X, Y)
        screen:X,Y,W,H      that rectangle scaled to 480x272
        window:TITLE        first on-screen window whose title or app name contains TITLE (sck only)

Permission: CGPreflightScreenCaptureAccess() is checked first; if it is False we call
CGRequestScreenCaptureAccess(), which shows the system prompt (System Settings > Privacy & Security >
Screen & System Audio Recording > enable your terminal app, then restart the terminal).
UNVERIFIED tonight: no permission was available while writing this; the synthetic sources were used.
"""
from __future__ import annotations

import threading

import numpy as np

from proto_screen import SCR_H, SCR_W
from screencodec import bgra_to_psp565


def ensure_permission() -> bool:
    import Quartz

    if Quartz.CGPreflightScreenCaptureAccess():
        return True
    print("[capture] Screen Recording permission missing -> requesting it (a system dialog should appear).\n"
          "          Grant it to your terminal app in System Settings > Privacy & Security >\n"
          "          Screen & System Audio Recording, then quit and reopen the terminal.")
    Quartz.CGRequestScreenCaptureAccess()
    return bool(Quartz.CGPreflightScreenCaptureAccess())


def _parse_rect(spec: str):
    if spec == "screen":
        return 0.0, 0.0, float(SCR_W), float(SCR_H)
    parts = [float(v) for v in spec.split(":", 1)[1].split(",")]
    if len(parts) == 2:
        return parts[0], parts[1], float(SCR_W), float(SCR_H)
    if len(parts) == 4:
        return tuple(parts)
    raise ValueError("screen spec: screen | screen:X,Y | screen:X,Y,W,H")


def _cgimage_to_565(img) -> np.ndarray:
    import Quartz

    w, h = Quartz.CGImageGetWidth(img), Quartz.CGImageGetHeight(img)
    bpr = Quartz.CGImageGetBytesPerRow(img)
    data = Quartz.CGDataProviderCopyData(Quartz.CGImageGetDataProvider(img))
    a = np.frombuffer(bytes(data), np.uint8).reshape(h, bpr)[:, : w * 4].reshape(h, w, 4)
    # SCK/CG deliver 32-bit little-endian, alpha-first -> bytes B,G,R,A (kCVPixelFormatType_32BGRA).
    if (w, h) != (SCR_W, SCR_H):
        from PIL import Image
        a = np.asarray(Image.fromarray(a[..., [2, 1, 0]]).resize((SCR_W, SCR_H), Image.BILINEAR))[..., [2, 1, 0]]
        a = np.concatenate([a, np.full((SCR_H, SCR_W, 1), 255, np.uint8)], axis=-1)
    return bgra_to_psp565(a)


def _wait(fn, timeout=5.0):
    """Calls an SCK async API and waits for its completion handler (called on a GCD queue)."""
    ev, box = threading.Event(), {}

    def done(*args):
        box["args"] = args
        ev.set()

    fn(done)
    if not ev.wait(timeout):
        raise TimeoutError("ScreenCaptureKit did not answer (permission dialog pending?)")
    *vals, err = box["args"]
    if err is not None:
        raise RuntimeError(f"ScreenCaptureKit error: {err}")
    return vals[0] if len(vals) == 1 else vals


class SckCapture:
    def __init__(self, spec: str):
        import ScreenCaptureKit as S

        self.S = S
        self.name = f"{spec} (ScreenCaptureKit)"
        content = _wait(lambda h: S.SCShareableContent.getShareableContentWithCompletionHandler_(h))
        cfg = S.SCStreamConfiguration.alloc().init()
        cfg.setWidth_(SCR_W)
        cfg.setHeight_(SCR_H)
        cfg.setShowsCursor_(True)
        if spec.startswith("window:"):
            q = spec[7:].lower()
            wins = [w for w in content.windows() if w.isOnScreen() and (
                q in (w.title() or "").lower() or q in (w.owningApplication().applicationName() or "").lower())]
            if not wins:
                raise RuntimeError(f"no on-screen window matches {q!r}")
            self.filter = S.SCContentFilter.alloc().initWithDesktopIndependentWindow_(wins[0])
            self.name = f"window '{wins[0].title()}' (ScreenCaptureKit)"
        else:
            import Quartz
            x, y, w, h = _parse_rect(spec)
            disp = content.displays()[0]
            self.filter = S.SCContentFilter.alloc().initWithDisplay_excludingWindows_(disp, [])
            cfg.setSourceRect_(Quartz.CGRectMake(x, y, w, h))
        self.cfg = cfg

    def frame(self, n: int) -> np.ndarray:
        img = _wait(lambda h: self.S.SCScreenshotManager.captureImageWithFilter_configuration_completionHandler_(
            self.filter, self.cfg, h))
        return _cgimage_to_565(img)


class MssCapture:
    def __init__(self, spec: str):
        import mss

        if spec.startswith("window:"):
            raise RuntimeError("window capture needs --capture sck")
        x, y, w, h = _parse_rect(spec)
        self.box = {"left": int(x), "top": int(y), "width": int(w), "height": int(h)}
        self.sct = mss.mss()
        self.name = f"{spec} (mss)"

    def frame(self, n: int) -> np.ndarray:
        shot = self.sct.grab(self.box)  # BGRA, physical pixels (2x on Retina)
        a = np.asarray(shot, np.uint8)
        if a.shape[:2] != (SCR_H, SCR_W):
            from PIL import Image
            rgb = Image.fromarray(a[..., [2, 1, 0]]).resize((SCR_W, SCR_H), Image.BILINEAR)
            a = np.asarray(rgb)[..., [2, 1, 0, 0]]
        return bgra_to_psp565(a)


def make_capture(spec: str, backend: str = "auto"):
    if not ensure_permission():
        raise PermissionError("Screen Recording permission not granted (see HARDWARE_TEST.md)")
    errors = []
    for b in (["sck", "mss"] if backend == "auto" else [backend]):
        try:
            return SckCapture(spec) if b == "sck" else MssCapture(spec)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{b}: {e}")
    raise RuntimeError("no capture backend works: " + "; ".join(errors))
