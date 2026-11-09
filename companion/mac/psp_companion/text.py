"""Turns raw Codex data (paths, shell commands, messages) into short ASCII the PSP can draw."""
from __future__ import annotations

import re
import shlex
import unicodedata

_CYR = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z", "и": "i", "й": "y",
    "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f",
    "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}
_PUNCT = {"—": "-", "–": "-", "…": "...", "«": '"', "»": '"', "“": '"', "”": '"', "‘": "'", "’": "'", "→": "->", "×": "x"}


def to_ascii(text: str) -> str:
    """Printable ASCII only: Cyrillic is transliterated, accents dropped, anything else becomes '?'."""
    out: list[str] = []
    for ch in text:
        if " " <= ch <= "~":
            out.append(ch)
        elif ch in "\t\r\n":
            out.append(" ")
        elif ch.lower() in _CYR:
            t = _CYR[ch.lower()]
            out.append(t.capitalize() if ch.isupper() else t)
        elif ch in _PUNCT:
            out.append(_PUNCT[ch])
        else:
            d = unicodedata.normalize("NFKD", ch).encode("ascii", "ignore").decode()
            out.append(d if d.strip() else "?")
    return re.sub(r" {2,}", " ", "".join(out)).strip()


def ellipsize(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def shorten_path(path: str, limit: int = 40) -> str:
    """Keeps the file name, then as many trailing directories as fit: long/path/to/x.py -> .../to/x.py"""
    path = to_ascii(path).rstrip("/")
    if len(path) <= limit:
        return path
    parts = path.split("/")
    out = parts[-1]
    if len(out) > limit:
        return "..." + out[-(limit - 3) :]
    for part in reversed(parts[:-1]):
        if len(out) + len(part) + 5 > limit:
            break
        out = f"{part}/{out}"
    return ".../" + out


_SHELLS = {"bash", "sh", "zsh", "dash", "fish"}
_TEST_RE = re.compile(
    r"(^|[\s;&|/(])("
    r"pytest|py\.test|unittest|tox|nox|jest|vitest|mocha|rspec|phpunit|ctest|"
    r"(npm|pnpm|yarn|bun|deno)(\s+run)?\s+test|"
    r"(cargo|go|swift|mvn|gradle|\./gradlew|dotnet|mix|zig)\s+test|"
    r"xcodebuild\s+test|make\s+(test|tests|check)"
    r")(\s|$|[;&|:])"
)


def unwrap_shell(command) -> str:
    """Accepts a string or argv; drops a `zsh -lc '...'` wrapper and returns the inner command line."""
    if isinstance(command, (list, tuple)):
        argv = [str(a) for a in command]
    else:
        text = str(command or "").strip()
        try:
            argv = shlex.split(text)
        except ValueError:
            return text
    if len(argv) >= 3 and argv[0].rsplit("/", 1)[-1] in _SHELLS and argv[1] in ("-c", "-lc", "-ic", "-l", "-lic"):
        if argv[1] == "-l" and len(argv) >= 4 and argv[2] == "-c":
            return argv[3]
        return argv[2]
    return " ".join(argv) if isinstance(command, (list, tuple)) else str(command).strip()


def is_test_command(command) -> bool:
    return bool(_TEST_RE.search(unwrap_shell(command)))


def summarize_command(command, limit: int = 60) -> str:
    inner = re.sub(r"\s+", " ", unwrap_shell(command)).strip()
    # "cd some/dir && real command" -> the command is what the user cares about
    inner = re.sub(r"^cd\s+(\"[^\"]*\"|'[^']*'|\S+)\s*&&\s*", "", inner)
    return ellipsize(to_ascii(inner), limit)
