"""Tile ids and their properties, stored as lookup tables indexed by tile id."""
import numpy as np

WALL, FLOOR, DOOR, STAIRS_DOWN, STAIRS_UP, SHALLOW, DEEP, PIT, TORCH = range(9)

# Each locked door has its own tile, so the client draws it in its key's color.
LOCK_COLORS = {"red": (235, 75, 75), "blue": (95, 140, 255), "green": (85, 215, 105), "yellow": (240, 210, 70)}
LOCKED = {name: TORCH + 1 + i for i, name in enumerate(LOCK_COLORS)}

NAMES = ("granite wall", "floor", "door", "downward staircase", "upward staircase",
         "shallow water", "deep water", "pit", "torch") + tuple(f"{name} locked door" for name in LOCK_COLORS)
DESCRIPTIONS = ("Solid rock.", "Bare stone.", "Blocks sight unless someone stands in it.",
                "Walk into it to go deeper.", "Walk into it to go back up.",
                "Cold, but safe to wade through.", "Too deep to wade. You could float across.",
                "Step in and you'll fall to the next floor.",
                "Monsters notice you from further away in its light.") + tuple(
                    f"Needs the {name} key." for name in LOCK_COLORS)

# Stairs sit inside the wall, as in Brogue: you walk into them to use them.
WALKABLE = np.array([False, True, True, False, False, True, False, False, False] + [False] * len(LOCKED))
# Everything a levitating player can be over, and all that diagonal moves can't cut past the rest.
HOVER = np.array([False, True, True, False, False, True, True, True, False] + [False] * len(LOCKED))
# Doors block sight unless someone is standing in the doorway (see Level).
TRANSPARENT = np.array([False, True, False, False, False, True, True, True, False] + [False] * len(LOCKED))

GLYPH = np.array([ord("#"), 0xB7, ord("+"), ord(">"), ord("<"), ord("~"), 0x2248, 0x2591, 0xA1]
                 + [ord("+")] * len(LOCKED), dtype=np.int32)
FG = np.array(
    [(150, 140, 128), (88, 88, 104), (196, 146, 84), (255, 255, 255), (255, 255, 255),
     (110, 150, 190), (105, 155, 235), (64, 58, 76), (255, 180, 70)] + list(LOCK_COLORS.values()),
    dtype=np.uint8,
)
BG = np.array(
    [(44, 40, 36), (16, 16, 22), (66, 44, 22), (78, 64, 128), (78, 64, 128),
     (22, 42, 66), (14, 34, 100), (4, 3, 8), (70, 44, 22)] + [(40, 34, 30)] * len(LOCKED),
    dtype=np.uint8,
)
