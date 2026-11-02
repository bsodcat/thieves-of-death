"""The keys a player can change. No tcod here, so the tests and settings can use it freely.

Movement and sprinting are held down, so they're tracked by key, as a tcod KeySym name such
as "W" or "LSHIFT". Everything else is pressed once and goes by the character it types, such
as ">", so it works on any keyboard layout. Keys that don't type anything, such as F3, are
kept by name instead.
"""
from __future__ import annotations

# (action, what the options screen calls it, default key)
ACTIONS = (
    ("up", "Move up", "W"),
    ("down", "Move down", "S"),
    ("left", "Move left", "A"),
    ("right", "Move right", "D"),
    ("sprint", "Sprint", "LSHIFT"),
    ("heal", "Quick heal", "q"),
    ("pickup", "Pick up", "g"),
    ("pack", "Pack", "i"),
    ("sort", "Sort pack", "o"),
    ("drop", "Drop", "x"),
    ("tally", "Tally", "t"),
    ("log", "Action log", "v"),
    ("descend", "Go downstairs", ">"),
    ("ascend", "Go upstairs", "<"),
    ("help", "Help", "?"),
    ("quit", "Leave game", "Q"),
)
HELD = ("up", "down", "left", "right", "sprint")
DIRECTIONS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
# Keys with a job of their own: chat, the console and the pack's slots.
RESERVED = {"ESCAPE", "RETURN", "RETURN2", "KP_ENTER", "BACKSPACE", "TAB", "GRAVE", "F1", "F2", "`", "~", "$",
            *"0123456789", *(f"N{d}" for d in range(10))}
NAMES = {"LSHIFT": "Shift", "RSHIFT": "Right Shift", "LCTRL": "Left Ctrl", "RCTRL": "Right Ctrl",
         "LALT": "Left Alt", "RALT": "Right Alt", "SPACE": "Space"}


def defaults() -> dict:
    return {action: key for action, _, key in ACTIONS}


def setting(action: str) -> str:
    """The name of an action's key in settings.json."""
    return f"key_{action}"


def load(config: dict) -> dict:
    """The player's keys from their settings, keeping the default for anything unusable."""
    keys = defaults()
    for action in keys:
        saved = config.get(setting(action), "")
        if saved and not saved.isspace():
            keys[action] = saved
    return keys


def key_id(action: str, key: str) -> str:
    """So that W held down and w typed count as the one key, while q and Q stay different."""
    return key.lower() if action in HELD and len(key) == 1 else key


def label(key: str) -> str:
    """A key as the player would call it."""
    return NAMES.get(key, key)


def labels(keys: dict) -> dict:
    """Each action's key for showing on screen. Held letters read as lower case, like the rest."""
    return {action: key.lower() if action in HELD and len(key) == 1 else label(key) for action, key in keys.items()}


def assign(keys: dict, action: str, name: str, text: str = "") -> str:
    """Gives an action the key with this KeySym name, which typed `text` if it typed anything.
    Returns why not if it can't, and leaves `keys` alone."""
    key = name if action in HELD or not text or text.isspace() else text
    shown = label(key_id(action, key))
    if name in RESERVED or key in RESERVED:
        return f"{shown} is already used by the game."
    for other, held in keys.items():
        if other != action and key_id(other, held) == key_id(action, key):
            return f"{shown} is already {dict((a, n) for a, n, _ in ACTIONS)[other]}."
    keys[action] = key
    return ""
