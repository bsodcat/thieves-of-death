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
    "host_password": "",   # what friends must type to join your game; blank lets anyone in
    "join_password": "",   # the last one you typed to join someone else's
    "font": "Terminal (10x20)",
    "shape": "@",
    "color": "Gold",
    "holiday_themes": "On",
    "ranged_target": "Strongest",
    "auto_attack": "Off",
    **{controls.setting(action): key for action, _, key in controls.ACTIONS},
}


FOLDER = "Thieves of Death"
OLD_FOLDER = "Togetherogue"  # the game's name before 2.13.1; its folder is moved over on first run


def default_path() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    folder, old = os.path.join(base, FOLDER), os.path.join(base, OLD_FOLDER)
    if not os.path.exists(folder) and os.path.isdir(old):
        try:
            os.rename(old, folder)  # keeps the player's settings and logs
        except OSError:
            return os.path.join(old, "settings.json")
    return os.path.join(folder, "settings.json")


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
