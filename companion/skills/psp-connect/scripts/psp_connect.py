#!/usr/bin/env python3
"""Entry point for $psp-connect: finds the installed companion and runs `psp-companion connect`.

Standard library only, because it may run under any python3. Exit 75 = blocked by the Codex sandbox.
"""
import json
import os
import sys


def main() -> int:
    home = os.path.expanduser(os.environ.get("PSP_COMPANION_HOME") or "~/.psp-companion")
    try:
        with open(os.path.join(home, "config.json")) as f:
            root = json.load(f)["root"]
    except (OSError, ValueError, KeyError):
        print("PSP companion is not installed. Run `tools/psp-companion install` from the PSP project.")
        return 2
    launcher = os.path.join(root, "tools", "psp-companion")
    if not os.path.exists(launcher):
        print(f"PSP project not found at {root}. Run `tools/psp-companion install` from the PSP project.")
        return 2
    command = os.environ.get("PSP_CONNECT_COMMAND", "connect")
    os.execv(launcher, [launcher, command] + sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
