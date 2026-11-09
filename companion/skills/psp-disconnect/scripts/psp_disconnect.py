#!/usr/bin/env python3
"""Entry point for $psp-disconnect: runs `psp-companion disconnect` for this session."""
import json
import os
import sys


def main() -> int:
    home = os.path.expanduser(os.environ.get("PSP_COMPANION_HOME") or "~/.psp-companion")
    try:
        with open(os.path.join(home, "config.json")) as f:
            root = json.load(f)["root"]
    except (OSError, ValueError, KeyError):
        print("PSP companion is not installed.")
        return 2
    launcher = os.path.join(root, "tools", "psp-companion")
    os.execv(launcher, [launcher, "disconnect"] + sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
