import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
for p in (ROOT / "companion/mac", ROOT / "common/python", ROOT / "companion/tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
