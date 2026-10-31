"""Reads Windows .fon bitmap fonts, such as the classic Terminal font (8514oem.fon).

A .fon file is a 16-bit Windows executable holding one .fnt resource per font size.
Only fixed-width version 2 faces are read, which covers Terminal and its relatives.
Returns plain numpy tiles, so this file doesn't need tcod.
"""
from __future__ import annotations

import struct

import numpy as np

RT_FONT = 0x8008
FNT_V2 = 0x200
CHAR_TABLE = 118  # the v2 header size


def read_faces(path: str) -> list[bytes]:
    """Every .fnt resource in a .fon file."""
    with open(path, "rb") as f:
        data = f.read()
    if data[:2] != b"MZ":
        raise ValueError(f"{path} is not a .fon file")
    ne = struct.unpack_from("<I", data, 0x3C)[0]
    if data[ne:ne + 2] != b"NE":
        raise ValueError(f"{path} is not a .fon file")
    table = ne + struct.unpack_from("<H", data, ne + 0x24)[0]
    shift = struct.unpack_from("<H", data, table)[0]
    pos = table + 2
    faces = []
    while True:
        kind, count = struct.unpack_from("<HH", data, pos)
        pos += 8
        if kind == 0:
            return faces
        for _ in range(count):
            offset, length = struct.unpack_from("<HH", data, pos)
            pos += 12
            if kind == RT_FONT:
                faces.append(data[offset << shift:(offset + length) << shift])


def face_size(face: bytes) -> tuple[int, int]:
    """(width, height) in pixels; width is 0 for proportional faces."""
    return struct.unpack_from("<HH", face, 0x56)


def face_tiles(face: bytes) -> dict[int, np.ndarray]:
    """Maps character codes to (height, width) alpha tiles."""
    width, height = face_size(face)
    first, last = face[0x5F], face[0x60]
    columns = (width + 7) // 8
    tiles = {}
    for code in range(first, last + 1):
        offset = struct.unpack_from("<H", face, CHAR_TABLE + 4 * (code - first) + 2)[0]
        # Bitmaps are stored as whole columns of bytes, left to right.
        raw = np.frombuffer(face, np.uint8, columns * height, offset)
        rows = raw.reshape(columns, height).T
        tiles[code] = np.unpackbits(rows, axis=1)[:, :width] * 255
    return tiles


def load(path: str, size: tuple[int, int] | None = None) -> tuple[int, int, dict[int, np.ndarray]]:
    """Returns (width, height, tiles) for the face matching size, or else the first usable one."""
    faces = [f for f in read_faces(path)
             if struct.unpack_from("<H", f)[0] == FNT_V2 and face_size(f)[0]]
    if not faces:
        raise ValueError(f"{path} has no fixed-width bitmap fonts")
    face = next((f for f in faces if face_size(f) == size), faces[0])
    return (*face_size(face), face_tiles(face))
