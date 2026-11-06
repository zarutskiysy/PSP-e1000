import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
for p in (ROOT / "screen" / "mac", ROOT / "tools", ROOT / "common" / "python"):
    sys.path.insert(0, str(p))
