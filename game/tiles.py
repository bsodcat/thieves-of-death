"""Tile ids and their properties, stored as lookup tables indexed by tile id."""
import numpy as np

WALL, FLOOR, DOOR, STAIRS_DOWN, STAIRS_UP = range(5)

NAMES = ("granite wall", "floor", "door", "downward staircase", "upward staircase")
DESCRIPTIONS = ("Solid rock.", "Bare stone.", "Blocks sight unless someone stands in it.",
                "Walk into it to go deeper.", "Walk into it to go back up.")

# Stairs sit inside the wall, as in Brogue: you walk into them to use them.
WALKABLE = np.array([False, True, True, False, False])
# Doors block sight unless someone is standing in the doorway (see Level).
TRANSPARENT = np.array([False, True, False, False, False])

GLYPH = np.array([ord("#"), 0xB7, ord("+"), ord(">"), ord("<")], dtype=np.int32)
FG = np.array(
    [(150, 140, 128), (88, 88, 104), (196, 146, 84), (255, 255, 255), (255, 255, 255)],
    dtype=np.uint8,
)
BG = np.array(
    [(44, 40, 36), (16, 16, 22), (66, 44, 22), (78, 64, 128), (78, 64, 128)],
    dtype=np.uint8,
)
