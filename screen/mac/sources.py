"""Frame sources for the second-screen sender. Every source returns (272, 480) uint16 PSP-565 frames.

  test-pattern     colour bars + moving box + running clock (changes a small area per frame)
  image:PATH       a still image, letterboxed to 480x272 (static desktop-like content)
  video-ish        scrolling terminal text (every row changes every frame: worst case for tiles)
  screen[:X,Y[,W,H]]   real capture of a Mac screen region (points), scaled to 480x272 (capture.py)
  window:TITLE     real capture of one window whose title/app contains TITLE (capture.py)
Synthetic sources are deterministic functions of the frame number, so tests can reproduce them.
"""
from __future__ import annotations

import time

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from proto_screen import SCR_H, SCR_W
from screencodec import rgb_to_psp565

W, H = SCR_W, SCR_H


def _font(size: int = 14):
    for path in ("/System/Library/Fonts/Menlo.ttc", "/System/Library/Fonts/Monaco.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default()


class TestPattern:
    name = "test-pattern"

    def __init__(self):
        bars = [(255, 255, 255), (255, 255, 0), (0, 255, 255), (0, 255, 0), (255, 0, 255), (255, 0, 0), (0, 0, 255),
                (0, 0, 0)]
        img = Image.new("RGB", (W, H), (16, 16, 32))
        d = ImageDraw.Draw(img)
        bw = W // len(bars)
        for i, c in enumerate(bars):
            d.rectangle([i * bw, 0, (i + 1) * bw - 1, 119], fill=c)
        for x in range(W):  # gradient strip: checks R/G/B order and 565 rounding
            v = x * 255 // (W - 1)
            d.line([x, 120, x, 135], fill=(v, 0, 0))
            d.line([x, 136, x, 151], fill=(0, v, 0))
            d.line([x, 152, x, 167], fill=(0, 0, v))
        d.text((8, 176), "PSP E1000 second screen  R G B", fill=(255, 255, 255), font=_font(16))
        self.base = img
        self.font = _font(20)

    def frame(self, n: int) -> np.ndarray:
        img = self.base.copy()
        d = ImageDraw.Draw(img)
        x = (n * 4) % (W - 40)
        d.rectangle([x, 204, x + 39, 243], fill=(255, 128, 0))
        d.text((8, 246), f"frame {n:06d}  t={n / 30:8.2f}s", fill=(0, 255, 128), font=self.font)
        return rgb_to_psp565(np.asarray(img))


class ImageSource:
    def __init__(self, path: str):
        self.name = f"image:{path}"
        im = Image.open(path).convert("RGB")
        im.thumbnail((W, H), Image.LANCZOS) if (im.width > W or im.height > H) else None
        canvas = Image.new("RGB", (W, H), (0, 0, 0))
        canvas.paste(im, ((W - im.width) // 2, (H - im.height) // 2))
        self.f = rgb_to_psp565(np.asarray(canvas))

    def frame(self, n: int) -> np.ndarray:
        return self.f


class VideoIsh:
    """Scrolling terminal log: 2 px per frame, so every text row changes every frame."""
    name = "video-ish"

    def __init__(self, speed: int = 2):
        font = _font(13)
        lines = [f"[{i:05d}] build step {i % 17:2d}/16  ok  cc -O2 -c src/mod_{i % 97:02d}.c  {'#' * (i * 7 % 40)}"
                 for i in range(200)]
        lh = 16
        img = Image.new("RGB", (W, lh * len(lines)), (12, 12, 12))
        d = ImageDraw.Draw(img)
        for i, s in enumerate(lines):
            d.text((4, i * lh), s, fill=(0, 220, 0) if i % 5 else (240, 240, 80), font=font)
        self.tall = rgb_to_psp565(np.asarray(img))
        self.speed = speed

    def frame(self, n: int) -> np.ndarray:
        y = (n * self.speed) % (self.tall.shape[0] - H)
        return np.ascontiguousarray(self.tall[y:y + H])


def make_source(spec: str, capture: str = "auto"):
    if spec == "test-pattern":
        return TestPattern()
    if spec == "video-ish":
        return VideoIsh()
    if spec.startswith("image:"):
        return ImageSource(spec[6:])
    if spec.startswith("screen") or spec.startswith("window:"):
        from capture import make_capture
        return make_capture(spec, capture)
    raise ValueError(f"unknown source {spec!r}")


def frame_iter(src, fps: float):
    """Yields (n, frame) paced at fps (no pacing if fps <= 0)."""
    n = 0
    t0 = time.perf_counter()
    while True:
        yield n, src.frame(n)
        n += 1
        if fps > 0:
            dt = t0 + n / fps - time.perf_counter()
            if dt > 0:
                time.sleep(dt)
