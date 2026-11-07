"""Optional: the real EBOOT in PPSSPP (replay + live mailbox bridge), pixel-exact.
Slow (~1 min) and needs PPSSPP + the PSP toolchain: run with RUN_PPSSPP=1.
Ports: PSP_SCREEN_PPSSPP_PORT (debugger, default 45672), PSP_SCREEN_BRIDGE_PORT (bridge, default 47102);
ppsspp_e2e.py reads both from the environment, which subprocess inherits."""
import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(os.environ.get("RUN_PPSSPP") != "1", reason="set RUN_PPSSPP=1")


@pytest.mark.parametrize("mode,source", [("replay", "image:screen/tests/data/desktop.png"),
                                         ("mailbox", "test-pattern")])
def test_ppsspp_pixel_exact(mode, source):
    r = subprocess.run([sys.executable, str(ROOT / "screen/tests/ppsspp_e2e.py"), "--mode", mode, "--source", source,
                        "--frames", "20"], cwd=ROOT, capture_output=True, text=True, timeout=600)
    assert r.returncode == 0 and "PIXEL-EXACT" in r.stdout, r.stdout[-2000:] + r.stderr[-2000:]
