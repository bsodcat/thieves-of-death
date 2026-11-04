"""The player's saved choices, kept in their user folder so the exe can stay anywhere."""
from __future__ import annotations

import json
import os

from . import controls
from .constants import DEFAULT_DIFFICULTY, DEFAULT_PORT

DEFAULTS = {
    "name": os.environ.get("USERNAME") or os.environ.get("USER") or "Adventurer",
    "address": "127.0.0.1",
    "port": str(DEFAULT_PORT),
    "seed": "",
    "difficulty": DEFAULT_DIFFICULTY,
    "font": "Terminal (10x20)",
    "shape": "@",
    "color": "Gold",
    "holiday_themes": "On",
    "ranged_target": "Strongest",
    "auto_attack": "Off",
    **{controls.setting(action): key for action, _, key in controls.ACTIONS},
}


def default_path() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "Togetherogue", "settings.json")


def load(path: str | None = None) -> dict:
    """Saved settings over the defaults. A missing or damaged file just gives the defaults."""
    settings = dict(DEFAULTS)
    try:
        with open(path or default_path(), encoding="utf-8") as f:
            saved = json.load(f)
    except (OSError, ValueError):
        return settings
    if isinstance(saved, dict):
        settings.update({k: str(v) for k, v in saved.items() if k in DEFAULTS})
    return settings


def save(settings: dict, path: str | None = None) -> None:
    path = path or default_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
    except OSError:
        pass  # not being able to save shouldn't stop anyone playing
