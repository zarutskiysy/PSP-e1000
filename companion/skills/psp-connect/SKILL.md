---
name: psp-connect
description: Connect the current Codex session to the user's physical PSP companion pet over USB, so the pet shows live agent status. Use only when the user explicitly asks to connect the PSP, for example by typing $psp-connect.
---

# PSP connect

Attaches this Codex session to the PSP companion daemon. The daemon keeps running after this skill finishes, so monitoring continues on its own. Running it again is safe: there is one daemon and one attachment per session.

## Steps

1. Run exactly this command once, from any directory:

   ```
   python3 "$HOME/.agents/skills/psp-connect/scripts/psp_connect.py"
   ```

2. If it exits with status 75, the Codex sandbox blocked it: the command must reach a local Unix socket and the USB port outside the workspace. Rerun the same command with escalated sandbox permissions and the justification "Connect this session to the local PSP companion daemon". Do not change any Codex settings or the approval policy to get around this.

3. Report the command's output to the user briefly: whether the PSP is linked, the connection mode, and which capabilities are available in this mode. Quote limitations as printed; do not claim more than the output says.

## Rules

- Do not attach a session the command did not identify. If it exits with status 3, it could not determine this session; show the user the candidates it printed and ask which one to use, then pass it with `--thread <id>`.
- Do not start, stop or install anything else, and do not edit files as part of this skill.
- If it reports the companion is not installed, tell the user to run `tools/psp-companion install` from the PSP project.
