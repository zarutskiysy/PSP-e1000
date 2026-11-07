import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
for p in (ROOT / "game" / "mac", ROOT / "common" / "python", ROOT / "tools"):
    sys.path.insert(0, str(p))
