---
name: psp-disconnect
description: Disconnect the current Codex session from the user's physical PSP companion pet. Use only when the user explicitly asks to disconnect the PSP, for example by typing $psp-disconnect.
---

# PSP disconnect

Stops showing this Codex session on the PSP. Other attached sessions and the daemon keep running.

1. Run exactly this command once:

   ```
   python3 "$HOME/.agents/skills/psp-disconnect/scripts/psp_disconnect.py"
   ```

2. If it exits with status 75, the Codex sandbox blocked it: rerun the same command with escalated sandbox permissions and the justification "Disconnect this session from the local PSP companion daemon".

3. Tell the user the result as printed. Do not change anything else.
