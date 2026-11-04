"""Tile ids and their properties, stored as lookup tables indexed by tile id."""
import numpy as np

WALL, FLOOR, DOOR, STAIRS_DOWN, STAIRS_UP, SHALLOW, DEEP, PIT, TORCH, LAVA, GRASS, FOLIAGE, TRAMPLED, ALTAR, ALTAR_SPENT, TOWER_WALL, POND = range(17)

# Each locked door has its own tile, so the client draws it in its key's color.
LOCK_COLORS = {"red": (235, 75, 75), "blue": (95, 140, 255), "green": (85, 215, 105), "yellow": (240, 210, 70)}
LOCKED = {name: POND + 1 + i for i, name in enumerate(LOCK_COLORS)}
# A wall a bomb can break, marked so you can spot it, with a hidden room behind it, and what
# fire leaves of grass.
CRACKED = POND + 1 + len(LOCK_COLORS)
ASH = CRACKED + 1

NAMES = ("granite wall", "floor", "door", "downward staircase", "upward staircase",
         "shallow water", "deep water", "pit", "torch", "lava", "grass", "tall grass",
         "trampled grass", "altar", "cold altar", "glowing wall",
         "pond of healing") + tuple(f"{name} locked door" for name in LOCK_COLORS) + ("cracked wall", "ash")
DESCRIPTIONS = ("Solid rock.", "Bare stone.", "Blocks sight unless someone stands in it.",
                "Walk into it to go deeper.", "Walk into it to go back up.",
                "Cold, but safe to wade through.", "Too deep to wade. You could float or walk across.",
                "Step in and you'll fall to the next floor.",
                "Monsters notice you from further away in its light.",
                "Molten rock. Nobody walks on this unprotected.",
                "Short enough to see over.",
                "Too tall to see through until it's trodden down.", "Someone has been through here.",
                "It glows with purple light. Walk into it.", "Its power is spent.", "Old stone, lit green from within.",
                "Bright water. Step in to be healed and warded.") + tuple(
                    f"Needs the {name} key." for name in LOCK_COLORS) + (
                "Crumbling stone with something behind it. A bomb would break it open.",
                "All that's left of the grass.")

_LOCKS = len(LOCKED)
# Stairs sit inside the wall, as in Brogue: you walk into them to use them.
WALKABLE = np.array([False, True, True, False, False, True, False, False, False, False, True, True, True, False, False, False, True] + [False] * _LOCKS + [False, True])
# Everything a levitating player can be over, and all that diagonal moves can't cut past the rest.
HOVER = np.array([False, True, True, False, False, True, True, True, False, True, True, True, True, False, False, False, True] + [False] * _LOCKS + [False, True])
# Doors block sight unless someone is standing in the doorway (see Level).
TRANSPARENT = np.array([False, True, False, False, False, True, True, True, False, True, True, False, True, True, True, False, True] + [False] * _LOCKS + [False, True])

GLYPH = np.array([ord("#"), 0xB7, ord("+"), ord(">"), ord("<"), ord("~"), 0x2248, 0x2591, 0xA1, 0x2248, ord('"'), 0x3C4, ord(","), 0x2229, 0x2229, ord("#"), 0x2248]
                 + [ord("+")] * _LOCKS + [0x2592, ord(",")], dtype=np.int32)
FG = np.array(
    [(150, 140, 128), (88, 88, 104), (196, 146, 84), (255, 255, 255), (255, 255, 255),
     (110, 150, 190), (105, 155, 235), (64, 58, 76), (255, 180, 70), (255, 170, 40), (100, 175, 70), (60, 150, 60), (90, 115, 75), (225, 140, 255), (110, 100, 120), (110, 255, 130), (150, 255, 240)] + list(LOCK_COLORS.values())
    + [(235, 196, 120), (70, 66, 62)],  # a cracked wall is warmer and brighter than the granite
    dtype=np.uint8,
)
BG = np.array(
    [(44, 40, 36), (16, 16, 22), (66, 44, 22), (78, 64, 128), (78, 64, 128),
     (22, 42, 66), (14, 34, 100), (4, 3, 8), (70, 44, 22), (150, 40, 8), (14, 30, 14), (10, 34, 14), (16, 20, 18), (70, 22, 105), (26, 24, 30), (16, 72, 30), (0, 130, 125)] + [(40, 34, 30)] * _LOCKS
    + [(34, 26, 18), (20, 18, 18)],
    dtype=np.uint8,
)
