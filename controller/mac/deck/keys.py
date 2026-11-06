"""macOS virtual key codes and modifier flags.

Key codes were extracted from the local macOS 26 SDK header
HIToolbox.framework/Headers/Events.h (kVK_* constants), not typed from memory.
Modifier masks are kCGEventFlagMask* from CoreGraphics/CGEventTypes.h.
"""
from __future__ import annotations

KEYCODES: dict[str, int] = {
    # letters (ANSI layout positions)
    "a": 0x00, "s": 0x01, "d": 0x02, "f": 0x03, "h": 0x04, "g": 0x05, "z": 0x06, "x": 0x07,
    "c": 0x08, "v": 0x09, "b": 0x0B, "q": 0x0C, "w": 0x0D, "e": 0x0E, "r": 0x0F, "y": 0x10,
    "t": 0x11, "o": 0x1F, "u": 0x20, "i": 0x22, "p": 0x23, "l": 0x25, "j": 0x26, "k": 0x28,
    "n": 0x2D, "m": 0x2E,
    # digits
    "1": 0x12, "2": 0x13, "3": 0x14, "4": 0x15, "6": 0x16, "5": 0x17, "9": 0x19, "7": 0x1A,
    "8": 0x1C, "0": 0x1D,
    # punctuation
    "equal": 0x18, "minus": 0x1B, "rightbracket": 0x1E, "leftbracket": 0x21, "quote": 0x27,
    "semicolon": 0x29, "backslash": 0x2A, "comma": 0x2B, "slash": 0x2C, "period": 0x2F, "grave": 0x32,
    # control keys
    "return": 0x24, "enter": 0x24, "tab": 0x30, "space": 0x31, "delete": 0x33, "backspace": 0x33,
    "escape": 0x35, "esc": 0x35, "forwarddelete": 0x75, "home": 0x73, "end": 0x77,
    "pageup": 0x74, "pagedown": 0x79,
    "left": 0x7B, "right": 0x7C, "down": 0x7D, "up": 0x7E,
    # function keys
    "f1": 0x7A, "f2": 0x78, "f3": 0x63, "f4": 0x76, "f5": 0x60, "f6": 0x61, "f7": 0x62, "f8": 0x64,
    "f9": 0x65, "f10": 0x6D, "f11": 0x67, "f12": 0x6F, "f13": 0x69, "f14": 0x6B, "f15": 0x71,
    "f16": 0x6A, "f17": 0x40, "f18": 0x4F, "f19": 0x50, "f20": 0x5A,
}

# kCGEventFlagMask* (CGEventTypes.h)
MOD_FLAGS: dict[str, int] = {
    "shift": 0x00020000,
    "ctrl": 0x00040000,
    "alt": 0x00080000,
    "cmd": 0x00100000,
    "fn": 0x00800000,
}
MOD_ALIASES = {"command": "cmd", "control": "ctrl", "option": "alt", "opt": "alt"}


def parse_combo(combo: str) -> tuple[int, tuple[str, ...]]:
    """'cmd+shift+3' -> (0x14, ('cmd', 'shift')). Raises ValueError."""
    parts = [p.strip().lower() for p in combo.split("+") if p.strip()]
    if not parts:
        raise ValueError("empty key combo")
    *mods, key = parts
    norm = []
    for m in mods:
        m = MOD_ALIASES.get(m, m)
        if m not in MOD_FLAGS:
            raise ValueError(f"unknown modifier {m!r} (one of {sorted(MOD_FLAGS)})")
        norm.append(m)
    if key not in KEYCODES:
        raise ValueError(f"unknown key {key!r}")
    return KEYCODES[key], tuple(norm)


def flags_for(mods: tuple[str, ...]) -> int:
    f = 0
    for m in mods:
        f |= MOD_FLAGS[m]
    return f
