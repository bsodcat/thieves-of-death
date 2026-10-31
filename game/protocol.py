"""Wire format: one JSON object per line, UTF-8.

Client -> server
    {"t": "hello", "name": "Alice", "glyph": "@", "color": "Gold"}
    {"t": "act", "a": "move", "dx": 1, "dy": 0}                  one step
    {"t": "act", "a": "hold", "dx": 1, "dy": 0, "press": true}   keep walking until told otherwise;
                                                                 dx = dy = 0 stops, press buffers a step
    {"t": "act", "a": "use" | "drop", "slot": 0}
    {"t": "act", "a": "descend" | "ascend" | "pickup" | "dropgold"}
    {"t": "chat", "text": "hi"}
    {"t": "pong", "n": 7}    answers a ping straight away

Server -> client
    {"t": "welcome", "id": 3, "name": "Alice", "version": 11}
    {"t": "level", "depth": 1, "run": 1, "w": 79, "h": 29, "tiles": <base64 uint8>}
    {"t": "state", ...}      see World.state_for
    {"t": "pack", ...}       see World.pack_msg; sent only when it changes
    {"t": "msg", "text": "...", "c": [r, g, b]}
    {"t": "ping", "n": 7}
    {"t": "reject", "text": "..."}   the versions don't match; the server then hangs up
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
