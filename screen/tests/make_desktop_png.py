"""Generates screen/tests/data/desktop.png: a synthetic 'static desktop' (menu bar, two windows with
text, a dock) used as the image:... benchmark source, so no real screenshot is needed."""
import pathlib
import sys

from PIL import Image, ImageDraw, ImageFont

out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else pathlib.Path(__file__).parent / "data" / "desktop.png")
try:
    f = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", 11)
except OSError:
    f = ImageFont.load_default()
im = Image.new("RGB", (480, 272))
d = ImageDraw.Draw(im)
for y in range(272):  # wallpaper gradient
    d.line([0, y, 479, y], fill=(30 + y // 6, 60 + y // 5, 110 + y // 4))
d.rectangle([0, 0, 479, 13], fill=(236, 236, 236))
d.text((6, 1), "  Finder  File  Edit  View  Go  Window  Help            03:14", fill=(0, 0, 0), font=f)
d.rectangle([20, 30, 290, 200], fill=(255, 255, 255), outline=(150, 150, 150))
d.rectangle([20, 30, 290, 46], fill=(220, 220, 220))
for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
    d.ellipse([26 + i * 14, 34, 34 + i * 14, 42], fill=c)
for i in range(11):
    d.text((28, 52 + i * 13), f"def step_{i}(x):  return x * {i} + {i * i}", fill=(30, 30, 30), font=f)
d.rectangle([250, 90, 466, 238], fill=(24, 24, 24), outline=(90, 90, 90))
for i in range(10):
    d.text((256, 96 + i * 13), f"$ make -j8   [{i * 10:3d}%] ok", fill=(0, 230, 0), font=f)
d.rounded_rectangle([140, 246, 340, 270], 6, fill=(200, 200, 210))
for i in range(7):
    d.rounded_rectangle([148 + i * 27, 249, 168 + i * 27, 267], 4, fill=(60 + i * 25, 120, 200 - i * 20))
out.parent.mkdir(parents=True, exist_ok=True)
im.save(out)
print(out)
