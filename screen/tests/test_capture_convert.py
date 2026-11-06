"""The capture path can't be run without the Screen Recording permission, but its CGImage -> PSP 565
conversion can: build a CGImage in memory with the same layout ScreenCaptureKit returns
(32-bit, premultiplied-first, little-endian = BGRA bytes) and check the colours."""
import sys

import numpy as np
import pytest

pytest.importorskip("Quartz")
import Quartz  # noqa: E402

import capture  # noqa: E402


def make_cgimage(rgb, w, h):
    cs = Quartz.CGColorSpaceCreateDeviceRGB()
    info = Quartz.kCGImageAlphaPremultipliedFirst | Quartz.kCGBitmapByteOrder32Little
    ctx = Quartz.CGBitmapContextCreate(None, w, h, 8, w * 4, cs, info)
    Quartz.CGContextSetRGBFillColor(ctx, *(c / 255 for c in rgb), 1.0)
    Quartz.CGContextFillRect(ctx, Quartz.CGRectMake(0, 0, w, h))
    return Quartz.CGBitmapContextCreateImage(ctx)


@pytest.mark.parametrize("rgb,want", [((255, 0, 0), 0x001F), ((0, 255, 0), 0x07E0), ((0, 0, 255), 0xF800)])
def test_cgimage_to_565(rgb, want):
    img = make_cgimage(rgb, 480, 272)
    v = capture._cgimage_to_565(img)
    assert v.shape == (272, 480) and np.all(v == want)


def test_cgimage_scaled():
    v = capture._cgimage_to_565(make_cgimage((255, 0, 0), 960, 544))  # Retina-sized grab
    assert v.shape == (272, 480) and np.all(v == 0x001F)


def test_parse_rect():
    assert capture._parse_rect("screen") == (0.0, 0.0, 480.0, 272.0)
    assert capture._parse_rect("screen:10,20") == (10.0, 20.0, 480.0, 272.0)
    assert capture._parse_rect("screen:0,0,960,544") == (0.0, 0.0, 960.0, 544.0)
