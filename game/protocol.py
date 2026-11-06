"""Wire format: one JSON object per line, UTF-8.

Client -> server
    {"t": "hello", "name": "Alice", "glyph": "@", "color": "Gold", "password": ""}
                             the password is checked only if the server has one
    {"t": "act", "a": "move", "dx": 1, "dy": 0}                  one step
    {"t": "act", "a": "hold", "dx": 1, "dy": 0, "press": true}   keep walking until told otherwise;
                                                                 dx = dy = 0 stops, press buffers a step
    {"t": "act", "a": "use" | "drop" | "sell", "slot": 0}       sell: to the merchant beside you
    {"t": "act", "a": "descend" | "ascend" | "pickup" | "dropgold"}
    {"t": "act", "a": "buy", "id": 2}                            an item in the shop
    {"t": "chat", "text": "hi"}
    {"t": "pong", "n": 7}    answers a ping straight away

Server -> client
    {"t": "welcome", "id": 3, "name": "Alice", "version": 12}
    {"t": "level", "depth": 1, "run": 1, "w": 79, "h": 29, "tiles": <base64 uint8>,
     "lights": [<base64 uint8>, ...],   one brightness map per torch
     "stains": [[x, y, "blood"], ...],  what monsters have left where they died
     "vault": {"c": [r, g, b], "cells": [[x, y], ...]},  a locked room's walls and key color, if any
     "webs": [[x, y], ...]}            spider webs
    {"t": "stains", "depth": 1, "cells": [[x, y, "goo"], ...]}   new ones since
    {"t": "webs", "depth": 1, "cells": [[x, y], ...]}   all the webs, when any are spun or burned
    {"t": "state", ...}      see World.state_for
    {"t": "fx", "kind": "fire", "cells": [[x, y], ...]}   a wand's bolt, "blink" for a teleport,
                             "hit" where a player has just struck a monster, "blast" for a bomb,
                             "lightning", "rock", "fireball", "web" (spat), "leap" (a spider's),
                             "bow", or "boomerang" for one thrown out to its target. "from": [x, y]
                             is where it came from; a player's shot that killed adds
                             "fell": {"g": "r", "c": [r, g, b]}. bow, rock, fireball and web fly.
    {"t": "tip", "who": "The fisherman"}   someone gives this player a tip, in their own keys
    {"t": "console", "text": "...", "c": [r, g, b]}       a line for the test console
    {"t": "prompt", "text": "...", "x": 1, "y": 2}   a yes or no question about an altar
    {"t": "tiles", "depth": 1, "cells": [[x, y, tile], ...]}   tiles that changed
    {"t": "pack", ...}       see World.pack_msg; sent only when it changes
    {"t": "msg", "text": "...", "c": [r, g, b]}
    {"t": "ping", "n": 7}
    {"t": "shop", "name": "merchant", "x": 4, "y": 9, "stock": [...]}   sent when you're at the shop
    {"t": "reject", "text": "..."}   why the server is hanging up: the versions don't match, the
                             password is wrong, the game is full, or the player sent too much

Limits on what a player sends (see constants.py): a line is at most MAX_LINE bytes, about
MSG_RATE messages a second with bursts of MSG_BURST, and CHAT_RATE chat lines. Messages over
the rate are ignored, and the server hangs up on a player who keeps going over it.
"""
from __future__ import annotations

import base64
import json

import numpy as np


def encode(msg: dict) -> bytes:
    return (json.dumps(msg, separators=(",", ":")) + "\n").encode("utf-8")


def decode(line: bytes | str) -> dict:
    """Raises ValueError on anything that isn't a JSON object."""
    if isinstance(line, bytes):
        line = line.decode("utf-8")
    msg = json.loads(line)
    if not isinstance(msg, dict):
        raise ValueError("message must be a JSON object")
    return msg


def pack_bool(a: np.ndarray) -> str:
    return base64.b64encode(np.packbits(np.ascontiguousarray(a, dtype=bool).ravel())).decode("ascii")


def unpack_bool(s: str, shape: tuple[int, int]) -> np.ndarray:
    bits = np.unpackbits(np.frombuffer(base64.b64decode(s), np.uint8))[: shape[0] * shape[1]]
    return bits.reshape(shape).astype(bool)


def pack_u8(a: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(a, dtype=np.uint8).tobytes()).decode("ascii")


def unpack_u8(s: str, shape: tuple[int, int]) -> np.ndarray:
    return np.frombuffer(base64.b64decode(s), np.uint8).reshape(shape).copy()
