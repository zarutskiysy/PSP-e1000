# Source me: `source tools/env.sh` — puts the pspdev toolchain and the venv on PATH.
export PSPDEV="${PSPDEV:-$HOME/pspdev}"
export PATH="$PSPDEV/bin:$PATH"
_here="$(cd "$(dirname "${BASH_SOURCE[0]:-${(%):-%x}}")/.." && pwd)"
[ -d "$_here/.venv" ] && export PATH="$_here/.venv/bin:$PATH"
export PSP_E1000_ROOT="$_here"
unset _here
