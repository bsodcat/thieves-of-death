"""Brogue-style level generation.

Brogue doesn't use "rooms and corridors". It grows a level by accretion:
start with one big room, then repeatedly generate a random room shape
(sometimes with a hallway sticking out of it) and try to fit it against a
wall of what already exists, connected by a single doorway. Afterwards it
adds loops by knocking through walls that separate two areas which are
far apart by foot. This module follows that recipe.

Water and pits go in last, over the finished level. Lakes and rivers run through
rock as well as rooms, so they can cut the level up. A ford is only left where it's
needed to walk between the stairs, or to a locked room's door. Anything else the
water cuts off stays cut off, as an island. Pits and lava never make one, so a
player who gets out to an island can always swim back; see World._player_move.

How a level grows depends on its depth (see `_style`). Floors 1 to 8 mix rooms and caves.
From CAVE_FLOORS they're mostly caves, from ROUND_FLOORS round rooms come back, and from
MIRROR_FLOORS rooms tend to come in pairs mirrored across the middle. Floors ODD_FLOORS each
start from one of a few other layouts instead: a maze, rings, a grid of rooms, a pillared hall
or one great cavern.

The end of the dungeon isn't grown at all. The atrium and the buried tower below it
are laid out by hand, with one half drawn and mirrored, so they're symmetrical.
"""
from __future__ import annotations

import math
import random
from collections import deque
from dataclasses import dataclass

import numpy as np

from .constants import (ATRIUM_FLOOR, LAKE_CHANCE, LAST_FLOOR, LAVA_CHANCE, LAVA_FIRST, LAVA_POOLS, MAP_H, MAP_W, PIT_CHANCE,
                        PLANT_CHANCE, PLANT_PATCHES, POND_CHANCE, TOWER_FIRST, PIT_COUNT, RIVER_CHANCE, TORCH_COUNT, TORCH_RADIUS,
                        TORCH_SPACING)
from .tiles import (CRACKED, DEEP, DOOR, FLOOR, FOLIAGE, GRASS, LAVA, PIT, POND, SHALLOW, STAIRS_DOWN, STAIRS_UP,
                    TORCH, TOWER_WALL, WALL)

DIRS4 = ((0, -1), (1, 0), (0, 1), (-1, 0))
Point = tuple[int, int]


@dataclass
class GeneratedLevel:
    tiles: np.ndarray  # uint8 [x, y]
    up: Point
    up_front: Point    # floor cell in front of the up staircase
    down: Point
    down_front: Point
    vault: np.ndarray | None = None   # the floor of the locked room, if there is one
    lock: Point | None = None         # its door
    torches: tuple = ()               # (torch, the floor cell in front of it)
    lair: Point | None = None         # the last floor has no way down, and this instead
    side_rooms: tuple = ()            # and these: each one a list of its floor tiles
    hidden: np.ndarray | None = None  # the floor of a room behind a cracked wall, if there is one
    cracks: tuple = ()                # the cracked stretch of its wall, 1 to 3 tiles
    cave: np.ndarray | None = None    # the big cave the level grew from, if it did: where spiders nest


# --------------------------------------------------------------- helpers

def _shift(a: np.ndarray, dx: int, dy: int, fill: bool) -> np.ndarray:
    """b[x, y] = a[x + dx, y + dy]; cells that fall off the array get `fill`."""
    w, h = a.shape
    b = np.full_like(a, fill)
    b[max(0, -dx):w - max(0, dx), max(0, -dy):h - max(0, dy)] = \
        a[max(0, dx):w - max(0, -dx), max(0, dy):h - max(0, -dy)]
    return b


def _dilate(m: np.ndarray) -> np.ndarray:
    """Grow a mask by one cell in all 8 directions. Result is 1 cell larger on every side."""
    p = np.pad(m, 1)
    out = p.copy()
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            out |= _shift(p, dx, dy, False)
    return out


def _neighbors8(m: np.ndarray) -> np.ndarray:
    w, h = m.shape
    p = np.pad(m.astype(np.int8), 1)
    n = np.zeros((w, h), np.int8)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if dx or dy:
                n += p[1 + dx:1 + dx + w, 1 + dy:1 + dy + h]
    return n


def _largest_component(m: np.ndarray) -> np.ndarray:
    w, h = m.shape
    seen = np.zeros_like(m, dtype=bool)
    best: list[Point] = []
    for x in range(w):
        for y in range(h):
            if m[x, y] and not seen[x, y]:
                comp, queue = [], deque([(x, y)])
                seen[x, y] = True
                while queue:
                    cx, cy = queue.popleft()
                    comp.append((cx, cy))
                    for dx, dy in DIRS4:
                        nx, ny = cx + dx, cy + dy
                        if 0 <= nx < w and 0 <= ny < h and m[nx, ny] and not seen[nx, ny]:
                            seen[nx, ny] = True
                            queue.append((nx, ny))
                if len(comp) > len(best):
                    best = comp
    out = np.zeros_like(m, dtype=bool)
    for x, y in best:
        out[x, y] = True
    return out


def _cell(p: Point) -> np.ndarray:
    m = np.zeros((MAP_W, MAP_H), bool)
    m[p] = True
    return m


def _crop(m: np.ndarray) -> np.ndarray:
    xs = np.flatnonzero(m.any(axis=1))
    ys = np.flatnonzero(m.any(axis=0))
    return m[xs[0]:xs[-1] + 1, ys[0]:ys[-1] + 1]


def _bfs(fl: np.ndarray, start: Point) -> np.ndarray:
    w, h = fl.shape
    dist = np.full((w, h), -1, dtype=np.int32)
    dist[start] = 0
    queue = deque([start])
    while queue:
        x, y = queue.popleft()
        for dx, dy in DIRS4:
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h and fl[nx, ny] and dist[nx, ny] < 0:
                dist[nx, ny] = dist[x, y] + 1
                queue.append((nx, ny))
    return dist


def _steps(fl: np.ndarray, a: Point, b: Point, limit: int) -> int:
    """Walking distance from a to b, or limit + 1 if it's further than limit."""
    w, h = fl.shape
    queue = deque([(a, 0)])
    seen = {a}
    while queue:
        (x, y), d = queue.popleft()
        if (x, y) == b:
            return d
        if d >= limit:
            continue
        for dx, dy in DIRS4:
            n = (x + dx, y + dy)
            if 0 <= n[0] < w and 0 <= n[1] < h and fl[n] and n not in seen:
                seen.add(n)
                queue.append((n, d + 1))
    return limit + 1


# ------------------------------------------------------------ room shapes

def _room_small(rng: random.Random) -> np.ndarray:
    return np.ones((rng.randint(3, 6), rng.randint(2, 4)), bool)


def _room_large(rng: random.Random) -> np.ndarray:
    return np.ones((rng.randint(6, 12), rng.randint(4, 7)), bool)


def _room_cross(rng: random.Random) -> np.ndarray:
    w1, h1 = rng.randint(6, 12), rng.randint(3, 5)
    w2 = rng.randint(3, max(3, w1 - 3))
    h2 = rng.randint(h1 + 2, h1 + 6)
    m = np.zeros((w1, h2), bool)
    y1 = rng.randint(1, h2 - h1 - 1)
    m[:, y1:y1 + h1] = True
    x2 = rng.randint(0, w1 - w2)
    m[x2:x2 + w2, :] = True
    return m


def _room_circle(rng: random.Random) -> np.ndarray:
    r = rng.randint(2, 4)
    xs, ys = np.ogrid[-r:r + 1, -r:r + 1]
    return (xs * xs + ys * ys) <= r * r + r


def _room_cave(rng: random.Random, w: int, h: int) -> np.ndarray:
    for _ in range(30):
        m = np.array([[rng.random() < 0.55 for _ in range(h)] for _ in range(w)], dtype=bool)
        for _ in range(5):
            n = _neighbors8(m)
            m = np.where(m, n >= 4, n >= 5)
            m[0, :] = m[-1, :] = False
            m[:, 0] = m[:, -1] = False
        m = _largest_component(m)
        if m.sum() >= w * h * 0.3:
            return _crop(m)
    return np.ones((max(3, w // 2), max(2, h // 2)), bool)


def _room_small_cave(rng: random.Random) -> np.ndarray:
    return _room_cave(rng, rng.randint(10, 16), rng.randint(7, 10))


def _room_big_circle(rng: random.Random) -> np.ndarray:
    r = rng.randint(4, 6)
    xs, ys = np.ogrid[-r:r + 1, -r:r + 1]
    return (xs * xs + ys * ys) <= r * r + r


ROOM_DESIGNS = (
    (_room_small, 4),
    (_room_large, 3),
    (_room_cross, 3),
    (_room_circle, 2),
    (_room_small_cave, 2),
)

CAVE_FLOORS = 9       # from here, levels are mostly caves
ROUND_FLOORS = 15     # from here, round rooms come back
MIRROR_FLOORS = 41    # from here, rooms tend to come in mirrored pairs
ODD_FLOORS = (50, 59)  # these start from one of ODD_LAYOUTS, in turn


@dataclass(frozen=True)
class Style:
    """How a level grows: the room shapes and how often each comes up, the chance the first
    room is a cave, of a door in each doorway (with and without a hallway), of a hallway, and of
    a room getting a mirrored twin across the middle."""
    designs: tuple = ROOM_DESIGNS
    cave_first: float = 0.5
    door: float = 0.7
    hall_door: float = 0.5
    hallway: float = 0.3
    mirror: float = 0.0


CAVES = ((_room_small, 1), (_room_large, 1), (_room_circle, 1), (_room_small_cave, 7))
ROUNDS = ((_room_small, 2), (_room_large, 2), (_room_cross, 1), (_room_circle, 5), (_room_big_circle, 3),
          (_room_small_cave, 4))


def _style(depth: int) -> Style:
    if depth < CAVE_FLOORS:
        return Style()
    if depth < ROUND_FLOORS:
        return Style(CAVES, cave_first=1.0, door=0.25, hall_door=0.15, hallway=0.15)
    if depth < MIRROR_FLOORS:
        return Style(ROUNDS, cave_first=0.6, door=0.5, hall_door=0.35, hallway=0.25)
    return Style(ROUNDS, cave_first=0.6, door=0.5, hall_door=0.35, hallway=0.25, mirror=0.6)


# ----------------------------------------------------------- attachment

def _make_piece(rng: random.Random, room: np.ndarray, d: Point, hallway: int):
    """Return (mask, site): the room (plus optional hallway) and the doorway
    cell it must line up with. `d` points from the existing map into the room."""
    dx, dy = d
    pad = hallway + 1
    m = np.pad(room, pad)
    cells = np.argwhere(m)
    proj = cells[:, 0] * dx + cells[:, 1] * dy
    edge = cells[proj == proj.min()]
    ex, ey = (int(v) for v in edge[rng.randrange(len(edge))])
    sx, sy = ex - dx, ey - dy
    for _ in range(hallway):
        m[sx, sy] = True
        sx, sy = sx - dx, sy - dy
    xs = np.flatnonzero(m.any(axis=1))
    ys = np.flatnonzero(m.any(axis=0))
    x0, y0 = int(xs[0]), int(ys[0])
    return m[x0:xs[-1] + 1, y0:ys[-1] + 1], (sx - x0, sy - y0)


def _try_attach(rng: random.Random, fl: np.ndarray, piece: np.ndarray, site: Point, d: Point,
                tries: int = 40) -> Point | None:
    dx, dy = d
    w, h = fl.shape
    pw, ph = piece.shape
    interior = np.zeros_like(fl)
    interior[1:-1, 1:-1] = True
    # A doorway: a wall cell with floor behind it and more wall in front of it.
    cand = (~fl) & interior & _shift(fl, -dx, -dy, False) & _shift(~fl, dx, dy, False)
    pts = np.argwhere(cand)
    if len(pts) == 0:
        return None
    dil = _dilate(piece)
    order = list(range(len(pts)))
    rng.shuffle(order)
    for i in order[:tries]:
        cx, cy = (int(v) for v in pts[i])
        ox, oy = cx - site[0], cy - site[1]
        if ox < 1 or oy < 1 or ox + pw > w - 1 or oy + ph > h - 1:
            continue
        # The new room (grown by 1, so a wall stays between rooms) may not touch floor.
        if (fl[ox - 1:ox + pw + 1, oy - 1:oy + ph + 1] & dil).any():
            continue
        fl[ox:ox + pw, oy:oy + ph] |= piece
        return cx, cy
    return None


def _attach_mirror(fl: np.ndarray, doors: set, piece: np.ndarray, origin: Point, door: Point, d: Point,
                   has_door: bool) -> None:
    """The room just attached, again on the other side of the middle, if it fits there the same way."""
    w, h = fl.shape
    pw, ph = piece.shape
    ox, oy = origin
    mx = w - ox - pw
    mdoor = (w - 1 - door[0], door[1])
    back = (mdoor[0] + d[0], mdoor[1] - d[1])  # where the map is, behind the mirrored doorway
    if mx < 1 or mx + pw > w - 1 or mdoor == door or fl[mdoor] or not fl[back]:
        return
    twin = piece[::-1, :]
    if (fl[mx - 1:mx + pw + 1, oy - 1:oy + ph + 1] & _dilate(twin)).any():
        return
    fl[mx:mx + pw, oy:oy + ph] |= twin
    fl[mdoor] = True
    if has_door:
        doors.add(mdoor)


def _accrete(rng: random.Random, fl: np.ndarray, doors: set, style: Style, rooms: int = 150) -> None:
    """Grows the level a room at a time, each fitted against a wall of what's there."""
    designs = [d for d, _ in style.designs]
    weights = [wt for _, wt in style.designs]
    for _ in range(rooms):
        room = rng.choices(designs, weights)[0](rng)
        d = rng.choice(DIRS4)
        hallway = rng.randint(2, 7) if rng.random() < style.hallway else 0
        piece, site = _make_piece(rng, room, d, hallway)
        door = _try_attach(rng, fl, piece, site, d)
        if door:
            fl[door] = True
            if rng.random() < (style.hall_door if hallway else style.door):
                doors.add(door)
            if style.mirror and rng.random() < style.mirror:
                origin = (door[0] - site[0], door[1] - site[1])
                _attach_mirror(fl, doors, piece, origin, door, d, door in doors)


# ------------------------------------------------------- floors 50 to 59

def _odd_maze(rng: random.Random, style: Style):
    """Twisting passages, a tile wide, with a few chambers knocked through them."""
    w, h = MAP_W, MAP_H
    fl = np.zeros((w, h), bool)
    cols, rows = (w - 1) // 2, (h - 1) // 2
    seen = np.zeros((cols, rows), bool)
    start = (rng.randrange(cols), rng.randrange(rows))
    seen[start] = True
    fl[1 + 2 * start[0], 1 + 2 * start[1]] = True
    stack = [start]
    while stack:
        cx, cy = stack[-1]
        nexts = [(cx + dx, cy + dy) for dx, dy in DIRS4
                 if 0 <= cx + dx < cols and 0 <= cy + dy < rows and not seen[cx + dx, cy + dy]]
        if not nexts:
            stack.pop()
            continue
        nx, ny = rng.choice(nexts)
        seen[nx, ny] = True
        fl[1 + 2 * nx, 1 + 2 * ny] = fl[1 + cx + nx, 1 + cy + ny] = True
        stack.append((nx, ny))
    for x in range(1, w - 1, 2):  # open up some dead ends, so it isn't all doubling back
        for y in range(1, h - 1, 2):
            walls = [(dx, dy) for dx, dy in DIRS4 if 1 <= x + 2 * dx < w - 1 and 1 <= y + 2 * dy < h - 1
                     and not fl[x + dx, y + dy]]
            if len(walls) == 3 and rng.random() < 0.5:
                dx, dy = rng.choice(walls)
                fl[x + dx, y + dy] = True
    for _ in range(rng.randint(5, 7)):
        rw, rh = rng.randint(3, 4), rng.randint(1, 2)
        x, y = 1 + 2 * rng.randrange(cols - rw), 1 + 2 * rng.randrange(rows - rh)
        _rect(fl, x, y, x + 2 * rw, y + 2 * rh)
    return fl, set(), None, False


def _odd_rings(rng: random.Random, style: Style):
    """Rings around a round hall in the middle, joined by a few passages each."""
    fl = np.zeros((MAP_W, MAP_H), bool)
    radii = [(37, 13), (29, 10), (21, 7), (13, 4)]
    bands = []
    for rx, ry in radii:
        band = _ellipse(MIDDLE_X, MIDDLE_Y, rx, ry) & ~_ellipse(MIDDLE_X, MIDDLE_Y, rx - 2.4, ry - 1.2)
        bands.append(band)
        fl |= band
    hub = _ellipse(MIDDLE_X, MIDDLE_Y, 6, 2.2)
    bands.append(hub)
    fl |= hub
    for outer in range(len(bands) - 1):
        start = rng.random() * 2 * math.pi
        ways = rng.randint(2, 3)
        for i in range(ways):
            angle = start + 2 * math.pi * i / ways + rng.uniform(-0.4, 0.4)
            _spoke(fl, bands, outer, angle)
    return fl, set(), None, False


def _spoke(fl: np.ndarray, bands: list, outer: int, angle: float) -> None:
    """A passage straight out from the middle, from ring `outer + 1` to ring `outer`."""
    last = len(bands) - 1  # the hub
    cells = []
    for i in range(400):
        t = i * 0.1
        c = (int(round(MIDDLE_X + math.cos(angle) * t * 2.8)), int(round(MIDDLE_Y + math.sin(angle) * t)))
        if not (0 < c[0] < MAP_W - 1 and 0 < c[1] < MAP_H - 1):
            break
        if not cells or cells[-1] != c:
            cells.append(c)
    on = None
    for c in cells:
        here = next((k for k in range(last, -1, -1) if bands[k][c]), None)
        if here is not None:
            on = here
            if here == outer:
                return
            continue
        if on == outer + 1:
            fl[c] = True


def _odd_grid(rng: random.Random, style: Style):
    """Rooms laid out in rows and columns, with passages between neighbors."""
    fl = np.zeros((MAP_W, MAP_H), bool)
    cols, rows = 4, 3
    cw, ch = (MAP_W - 2) // cols, (MAP_H - 2) // rows
    centers = {}
    for i in range(cols):
        for j in range(rows):
            rw, rh = rng.randint(5, cw - 4), rng.randint(3, ch - 3)
            x0 = 1 + i * cw + rng.randint(1, cw - rw - 2)
            y0 = 1 + j * ch + rng.randint(1, ch - rh - 2)
            _rect(fl, x0, y0, x0 + rw - 1, y0 + rh - 1)
            centers[i, j] = (x0 + rw // 2, y0 + rh // 2)
    links = set()
    seen, stack = {(0, 0)}, [(0, 0)]
    while stack:  # every room joined up, then a few more passages for loops
        here = stack[-1]
        nexts = [(here[0] + dx, here[1] + dy) for dx, dy in DIRS4 if (here[0] + dx, here[1] + dy) in centers
                 and (here[0] + dx, here[1] + dy) not in seen]
        if not nexts:
            stack.pop()
            continue
        there = rng.choice(nexts)
        links.add((here, there))
        seen.add(there)
        stack.append(there)
    for a in centers:
        for dx, dy in ((1, 0), (0, 1)):
            b = (a[0] + dx, a[1] + dy)
            if b in centers and rng.random() < 0.3:
                links.add((a, b))
    for a, b in links:
        (ax, ay), (bx, by) = centers[a], centers[b]
        if rng.random() < 0.5:
            _rect(fl, min(ax, bx), ay, max(ax, bx), ay)
            _rect(fl, bx, min(ay, by), bx, max(ay, by))
        else:
            _rect(fl, ax, min(ay, by), ax, max(ay, by))
            _rect(fl, min(ax, bx), by, max(ax, bx), by)
    return fl, set(), None, False


def _odd_hall(rng: random.Random, style: Style):
    """A great hall held up by rows of pillars, with rooms grown around it."""
    fl = np.zeros((MAP_W, MAP_H), bool)
    hw, hh = rng.randint(17, 24), rng.randint(5, 7)
    _rect(fl, MIDDLE_X - hw, MIDDLE_Y - hh, MIDDLE_X + hw, MIDDLE_Y + hh)
    step = rng.choice((3, 4))
    for x in range(MIDDLE_X - hw + 2, MIDDLE_X + hw - 1, step):
        for y in range(MIDDLE_Y - hh + 2, MIDDLE_Y + hh - 1, 3):
            fl[x, y] = fl[MAP_W - 1 - x, y] = False
    return fl, set(), None, True


def _odd_cavern(rng: random.Random, style: Style):
    """One cavern filling most of the floor, and a few smaller caves off it."""
    fl = np.zeros((MAP_W, MAP_H), bool)
    first = _room_cave(rng, 72, 26)
    pw, ph = first.shape
    ox, oy = (MAP_W - pw) // 2, (MAP_H - ph) // 2
    fl[ox:ox + pw, oy:oy + ph] = first
    return fl, set(), fl.copy(), True


ODD_LAYOUTS = (_odd_maze, _odd_rings, _odd_grid, _odd_hall, _odd_cavern)


# --------------------------------------------------------- finishing passes

def _add_loops(rng: random.Random, fl: np.ndarray, doors: set, min_steps: int = 20) -> None:
    w, h = fl.shape
    cells = [(x, y) for x in range(1, w - 1) for y in range(1, h - 1)]
    rng.shuffle(cells)
    for x, y in cells:
        if fl[x, y]:
            continue
        if fl[x - 1, y] and fl[x + 1, y] and not fl[x, y - 1] and not fl[x, y + 1]:
            a, b = (x - 1, y), (x + 1, y)
        elif fl[x, y - 1] and fl[x, y + 1] and not fl[x - 1, y] and not fl[x + 1, y]:
            a, b = (x, y - 1), (x, y + 1)
        else:
            continue
        if _steps(fl, a, b, min_steps) > min_steps:
            fl[x, y] = True
            if rng.random() < 0.5:
                doors.add((x, y))


def _fix_diagonals(rng: random.Random, fl: np.ndarray) -> None:
    """Brogue forbids squeezing diagonally between two walls, so make sure no
    two floor cells are connected *only* diagonally."""
    w, h = fl.shape
    changed = True
    while changed:
        changed = False
        for x in range(w - 1):
            for y in range(h - 1):
                a, b, c, d = fl[x, y], fl[x + 1, y], fl[x, y + 1], fl[x + 1, y + 1]
                if a and d and not b and not c:
                    fl[rng.choice(((x + 1, y), (x, y + 1)))] = True
                    changed = True
                elif b and c and not a and not d:
                    fl[rng.choice(((x, y), (x + 1, y + 1)))] = True
                    changed = True


def _clean_doors(fl: np.ndarray, doors: set) -> None:
    for x, y in list(doors):
        ew = fl[x - 1, y] and fl[x + 1, y] and not fl[x, y - 1] and not fl[x, y + 1]
        ns = fl[x, y - 1] and fl[x, y + 1] and not fl[x - 1, y] and not fl[x + 1, y]
        if not (ew or ns):
            doors.discard((x, y))


def _stair_sites(fl: np.ndarray, doors: set) -> list[tuple[Point, Point]]:
    """Wall cells with exactly one floor neighbor (an alcove in a straight wall)."""
    w, h = fl.shape
    sites = []
    for x in range(w):
        for y in range(h):
            if fl[x, y]:
                continue
            fronts = [(x + dx, y + dy) for dx, dy in DIRS4
                      if 0 <= x + dx < w and 0 <= y + dy < h and fl[x + dx, y + dy]]
            if len(fronts) == 1 and fronts[0] not in doors:
                sites.append(((x, y), fronts[0]))
    return sites


# ---------------------------------------------------------------- locked room

def _add_vault(rng: random.Random, fl: np.ndarray) -> tuple[np.ndarray, Point] | None:
    """Fits a dead-end room into the rock. `_try_attach` leaves a wall all round it, so the
    door is the only way in. Returns its floor and its door."""
    before = fl.copy()
    for size in (rng.randint(4, 6), rng.randint(3, 4)), (rng.randint(3, 4), rng.randint(2, 3)), (3, 2):
        dirs = list(DIRS4)
        rng.shuffle(dirs)
        for d in dirs:
            piece, site = _make_piece(rng, np.ones(size, bool), d, 0)
            door = _try_attach(rng, fl, piece, site, d, tries=400)
            if door:
                vault = fl & ~before
                fl[door] = True
                return vault, door
    return None


def _widen_crack(rng: random.Random, fl: np.ndarray, room: np.ndarray, crack: Point) -> tuple:
    """A stretch of 1 to 3 tiles of the hidden room's wall, along it and taking in `crack`,
    each with the room right behind it. Marks them all in `fl`, as `_add_vault` marked `crack`."""
    w, h = fl.shape
    into = next((dx, dy) for dx, dy in DIRS4 if room[crack[0] + dx, crack[1] + dy])
    along = (into[1], into[0])

    def fits(k: int) -> bool:
        x, y = crack[0] + along[0] * k, crack[1] + along[1] * k
        return (1 <= x < w - 1 and 1 <= y < h - 1 and not fl[x, y]
                and room[x + into[0], y + into[1]] and not room[x - into[0], y - into[1]])

    low = high = 0
    while low > -2 and fits(low - 1):
        low -= 1
    while high < 2 and fits(high + 1):
        high += 1
    width = min(rng.randint(1, 3), high - low + 1)
    start = rng.randint(max(low, 1 - width), min(0, high - width + 1))
    cracks = tuple((crack[0] + along[0] * k, crack[1] + along[1] * k) for k in range(start, start + width))
    for c in cracks:
        fl[c] = True
    return cracks


# ---------------------------------------------------------- water and pits

def _lake(rng: random.Random) -> np.ndarray:
    blob = _room_cave(rng, rng.randint(14, 28), rng.randint(8, 14))
    m = np.zeros((MAP_W, MAP_H), bool)
    pw, ph = blob.shape
    ox, oy = rng.randint(1, MAP_W - pw - 1), rng.randint(1, MAP_H - ph - 1)
    m[ox:ox + pw, oy:oy + ph] = blob
    return m


def _river(rng: random.Random) -> np.ndarray:
    """A band that wanders from one side of the map to the other."""
    m = np.zeros((MAP_W, MAP_H), bool)
    across = rng.random() < 0.6
    length, span = (MAP_W, MAP_H) if across else (MAP_H, MAP_W)
    middle = rng.randint(span // 4, span * 3 // 4)
    width = rng.randint(1, 2)
    for along in range(1, length - 1):
        middle = min(max(2, middle + rng.choice((-1, 0, 0, 1))), span - 4)
        cells = range(middle, middle + width + 1)
        if across:
            m[along, cells] = True
        else:
            m[cells, along] = True
    return m


def _stamp(rng: random.Random, m: np.ndarray, hole: np.ndarray) -> None:
    pw, ph = hole.shape
    ox, oy = rng.randint(1, MAP_W - pw - 1), rng.randint(1, MAP_H - ph - 1)
    m[ox:ox + pw, oy:oy + ph] |= hole


def _pits(rng: random.Random) -> np.ndarray:
    m = np.zeros((MAP_W, MAP_H), bool)
    for _ in range(rng.randint(*PIT_COUNT)):
        _stamp(rng, m, _room_circle(rng) if rng.random() < 0.3
               else np.ones((rng.randint(1, 3), rng.randint(1, 3)), bool))
    return m


def _lava(rng: random.Random) -> np.ndarray:
    m = np.zeros((MAP_W, MAP_H), bool)
    for _ in range(rng.randint(*LAVA_POOLS)):
        _stamp(rng, m, _room_circle(rng))
    return m


def _rejoin(ground: np.ndarray, wanted: np.ndarray, cuts: np.ndarray, start: Point) -> set:
    """The `cuts` cells to clear so one more `wanted` cell can be reached from `start` over
    `ground`, or nothing if they all can. It's the shortest crossing, so a river gets a
    narrow ford."""
    reached = _bfs(ground, start) >= 0
    missing = wanted & ~reached
    if not missing.any():
        return set()
    w, h = ground.shape
    came: dict[Point, Point | None] = {(int(x), int(y)): None for x, y in np.argwhere(reached)}
    queue = deque(came)
    while queue:
        x, y = queue.popleft()
        for dx, dy in DIRS4:
            n = (x + dx, y + dy)
            if not (0 <= n[0] < w and 0 <= n[1] < h) or n in came:
                continue
            if missing[n]:  # walk back, noting what was crossed
                path, at = set(), (x, y)
                while at is not None:
                    if cuts[at]:
                        path.add(at)
                    at = came[at]
                return path
            if cuts[n] or ground[n]:
                came[n] = (x, y)
                queue.append(n)
    raise AssertionError("cut-off ground with no way across")


def _corners(ground: np.ndarray, cuts: np.ndarray, keep: np.ndarray) -> set | None:
    """A cell to clear so no two tiles of ground touch only diagonally: water or a pit if it
    can be, or else rock beside a ford. None if neither can be cleared."""
    a, b, c, d = ground[:-1, :-1], ground[1:, :-1], ground[:-1, 1:], ground[1:, 1:]
    touching = np.argwhere(a & d & ~b & ~c | b & c & ~a & ~d)
    if len(touching) == 0:
        return set()
    x, y = (int(v) for v in touching[0])
    pair = ((x + 1, y), (x, y + 1)) if ground[x, y] else ((x, y), (x + 1, y + 1))
    free = sorted((p for p in pair if not keep[p]), key=lambda p: not cuts[p])
    return set(free[:1]) or None


def _add_terrain(rng: random.Random, fl: np.ndarray, doors: set, keep: np.ndarray, start: Point,
                 goals: tuple, depth: int):
    """Returns the deep, shallow, pit and lava masks, or None if this level can't be made to
    work. Nothing is put on the `keep` cells, and `goals` can be walked to from `start`."""
    deep = np.zeros_like(fl)
    if rng.random() < LAKE_CHANCE:
        deep |= _lake(rng)
    if rng.random() < RIVER_CHANCE:
        deep |= _river(rng)
    deep &= ~keep
    pits = np.zeros_like(fl)
    if rng.random() < PIT_CHANCE:
        pits = _pits(rng) & fl & ~keep & ~deep
    lava = np.zeros_like(fl)
    if depth >= LAVA_FIRST and rng.random() < LAVA_CHANCE:
        # Kept two tiles clear of deep water, so the shallows around it never touch lava either.
        wet = _dilate(_dilate(deep)[1:-1, 1:-1])[1:-1, 1:-1]
        lava = _lava(rng) & fl & ~keep & ~wet & ~pits
    for x, y in doors:
        pits[x, y] = lava[x, y] = False
    doors -= {p for p in doors if deep[p]}
    _clean_doors(fl | deep, doors)
    goal_cells = np.zeros_like(fl)
    for goal in goals:
        goal_cells[goal] = True

    while True:
        ground = fl & ~deep & ~pits & ~lava
        cuts = deep | pits | lava
        clear = (_rejoin(ground, goal_cells, cuts, start)                  # the way to the stairs
                 or _rejoin(ground | deep, ground, pits | lava, start)     # only water makes an island
                 or _corners(ground, cuts, keep))
        if clear is None:
            return None
        if not clear:
            break
        for p in clear:
            deep[p] = pits[p] = lava[p] = False
            fl[p] = True
    _clean_doors(ground, doors)  # a door opening onto water is just a gap in the wall
    shallow = _dilate(deep)[1:-1, 1:-1] & fl & ~deep & ~pits & ~lava & ~keep
    return deep, shallow, pits, lava


# ------------------------------------------------------------------- plants

def _add_plants(rng: random.Random, tiles: np.ndarray, keep: np.ndarray) -> None:
    """Patches of tall grass with thicker foliage in them, on bare floor only."""
    if rng.random() >= PLANT_CHANCE:
        return
    grass, thick = np.zeros((MAP_W, MAP_H), bool), np.zeros((MAP_W, MAP_H), bool)
    for _ in range(rng.randint(*PLANT_PATCHES)):
        _stamp(rng, grass, _room_small_cave(rng))
        _stamp(rng, thick, _room_circle(rng))
    bare = (tiles == FLOOR) & ~keep
    tiles[grass & bare] = GRASS
    tiles[grass & thick & bare] = FOLIAGE


def _add_pond(rng: random.Random, tiles: np.ndarray, keep: np.ndarray) -> None:
    """A small pool of healing water, sometimes."""
    if rng.random() >= POND_CHANCE:
        return
    pond = np.zeros((MAP_W, MAP_H), bool)
    _stamp(rng, pond, _room_circle(rng) if rng.random() < 0.5 else np.ones((3, 2), bool))
    hot = _dilate(tiles == LAVA)[1:-1, 1:-1]  # no water right beside lava
    tiles[pond & (tiles == FLOOR) & ~keep & ~hot] = POND


# ------------------------------------------------------------------ torches

def _add_torches(rng: random.Random, tiles: np.ndarray, vault, stairs: tuple) -> list[tuple[Point, Point]]:
    """Picks wall cells beside bare floor, far from the stairs and from each other."""
    w, h = tiles.shape
    spots = []
    for x in range(1, w - 1):
        for y in range(1, h - 1):
            fronts = [(x + dx, y + dy) for dx, dy in DIRS4 if tiles[x + dx, y + dy] == FLOOR]
            if tiles[x, y] == WALL and len(fronts) == 1 and (vault is None or not vault[fronts[0]]):
                spots.append(((x, y), fronts[0]))
    rng.shuffle(spots)
    torches: list[tuple[Point, Point]] = []
    wanted = rng.randint(*TORCH_COUNT)

    def apart(a: Point, b: Point, gap: int) -> bool:
        return max(abs(a[0] - b[0]), abs(a[1] - b[1])) > gap

    for torch, front in spots:
        if len(torches) < wanted and all(apart(torch, s, TORCH_RADIUS) for s in stairs) \
                and all(apart(torch, t, TORCH_SPACING) for t, _ in torches):
            torches.append((torch, front))
    return torches


# ----------------------------------------------------------- the buried tower

MIDDLE_X, MIDDLE_Y = (MAP_W - 1) // 2, (MAP_H - 1) // 2


def _ellipse(cx: int, cy: int, rx: float, ry: float) -> np.ndarray:
    xs, ys = np.ogrid[0:MAP_W, 0:MAP_H]
    m = ((xs - cx) / rx) ** 2 + ((ys - cy) / ry) ** 2 <= 1
    m[0, :] = m[-1, :] = False
    m[:, 0] = m[:, -1] = False
    return m


def _rect(fl: np.ndarray, x0: int, y0: int, x1: int, y1: int) -> None:
    fl[x0:x1 + 1, y0:y1 + 1] = True


def _pillars(fl: np.ndarray, cx: int, cy: int, rx: float, ry: float, count: int) -> None:
    """Stone columns, evenly spaced around an ellipse."""
    for i in range(count):
        angle = 2 * np.pi * (i + 0.5) / count
        fl[int(round(cx + rx * np.cos(angle))), int(round(cy + ry * np.sin(angle)))] = False


def _built(fl: np.ndarray, doors: set, stone: np.ndarray, up: Point, up_front: Point, down=None, down_front=None,
           lair=None, rng=None) -> GeneratedLevel | None:
    """Turns a hand-made plan into a level, or None if it doesn't all join up."""
    _clean_doors(fl, doors)
    if (_bfs(fl, up_front)[fl] < 0).any():
        return None
    tiles = np.full(fl.shape, WALL, np.uint8)
    tiles[stone] = TOWER_WALL
    tiles[fl] = FLOOR
    for p in doors:
        tiles[p] = DOOR
    tiles[up] = STAIRS_UP
    if down:
        tiles[down] = STAIRS_DOWN
    torches = []
    if rng is not None:
        torches = _add_torches(rng, tiles, None, (up, down))
        for torch, _ in torches:
            tiles[torch] = TORCH
    return GeneratedLevel(tiles, up, up_front, down, down_front, None, None, tuple(torches), lair)


def _mirror(half: np.ndarray) -> np.ndarray:
    return half | half[::-1, :]


def _tower(rng: random.Random) -> GeneratedLevel | None:
    """One floor of the tower: a round footprint, a central hall and a shaft through it, and
    the same rooms down each side."""
    half = np.zeros((MAP_W, MAP_H), bool)
    doors: set[Point] = set()
    _rect(half, MIDDLE_X - 1, 3, MIDDLE_X, MAP_H - 4)
    half |= _ellipse(MIDDLE_X, MIDDLE_Y, rng.randint(6, 9), rng.randint(4, 6))
    for row in (6, MIDDLE_Y, MAP_H - 7):
        high = rng.randint(1, 2)
        left, right = rng.randint(22, 26), rng.randint(29, 32)
        _rect(half, left, row - high, right, row + high)
        _rect(half, right + 1, row, MIDDLE_X, row)
        doors.add((right + 1, row))
        if rng.random() < 0.8:     # and sometimes another room further out
            outer = rng.randint(16, 18)
            _rect(half, outer - rng.randint(4, 6), row - high, outer, row + high)
            _rect(half, outer + 1, row, left - 1, row)
            doors.add((left - 1, row))
    stone = _ellipse(MIDDLE_X, MIDDLE_Y, 37, 13.6)
    fl = _mirror(half) & stone
    doors |= {(MAP_W - 1 - x, y) for x, y in doors}
    top, bottom = (MIDDLE_X, 2), (MIDDLE_X, MAP_H - 3)
    return _built(fl, doors, stone, top, (MIDDLE_X, 3), bottom, (MIDDLE_X, MAP_H - 4))


def _lair(rng: random.Random) -> GeneratedLevel | None:
    """The last floor: a great round room with pillars, and a few smaller ones off it."""
    half = _ellipse(MIDDLE_X, 15, 17, 10)
    doors: set[Point] = set()
    _pillars(half, MIDDLE_X, 15, 11, 6.5, 8)
    _pillars(half, MIDDLE_X, 15, 5.5, 3.2, 4)
    _rect(half, MIDDLE_X - 1, 3, MIDDLE_X, 6)
    rooms = []
    for row in (8, 21):
        top = row - rng.randint(1, 2)
        _rect(half, 9, top, 17, row + 2)
        rooms.append((top, row + 2))
        _rect(half, 18, row, 28, row)
        doors.add((18, row))
    stone = _ellipse(MIDDLE_X, MIDDLE_Y, 37, 13.6)
    fl = _mirror(half) & stone
    doors |= {(MAP_W - 1 - x, y) for x, y in doors}
    level = _built(fl, doors, stone, (MIDDLE_X, 2), (MIDDLE_X, 3), lair=(MIDDLE_X, 15))
    if level is not None:
        left = [[(x, y) for x in range(9, 18) for y in range(top, bottom + 1) if fl[x, y]] for top, bottom in rooms]
        level.side_rooms = tuple(left) + tuple([(MAP_W - 1 - x, y) for x, y in room] for room in left)
    return level


def _atrium(rng: random.Random) -> GeneratedLevel | None:
    """A long pillared hall opening into a round atrium, with the way into the tower beyond."""
    fl = np.zeros((MAP_W, MAP_H), bool)
    _rect(fl, 6, MIDDLE_Y - 2, 50, MIDDLE_Y + 2)
    for x in range(10, 48, 6):
        fl[x, MIDDLE_Y - 2] = fl[x, MIDDLE_Y + 2] = False
    fl |= _ellipse(62, MIDDLE_Y, 13, 10)
    _pillars(fl, 62, MIDDLE_Y, 8, 5.5, 8)
    return _built(fl, set(), _ellipse(62, MIDDLE_Y, 15.5, 12.5), (5, MIDDLE_Y), (6, MIDDLE_Y),
                  (76, MIDDLE_Y), (75, MIDDLE_Y), rng=rng)


# ------------------------------------------------------------------ main

def _try_generate(rng: random.Random, depth: int, lock_tile: int | None = None,
                  hidden_room: bool = False) -> GeneratedLevel | None:
    w, h = MAP_W, MAP_H
    style = _style(depth)
    if ODD_FLOORS[0] <= depth <= ODD_FLOORS[1]:
        layout = ODD_LAYOUTS[(depth - ODD_FLOORS[0]) % len(ODD_LAYOUTS)]
        fl, doors, cave, grow = layout(rng, style)
        _fix_diagonals(rng, fl)  # so it all joins up tile to tile
        if grow:
            _accrete(rng, fl, doors, style, 100)
        fl &= _largest_component(fl)
        _add_loops(rng, fl, doors, 60 if layout is _odd_maze else 20)
    else:
        fl = np.zeros((w, h), bool)
        doors = set()
        is_cave = rng.random() < style.cave_first
        first = _room_cave(rng, rng.randint(24, 34), rng.randint(12, 18)) if is_cave else _room_cross(rng)
        pw, ph = first.shape
        if style.mirror:  # in the middle, and the same both sides
            ox = (w - pw) // 2
        else:
            ox = min(max(1, (w - pw) // 2 + rng.randint(-12, 12)), w - pw - 1)
        oy = min(max(1, (h - ph) // 2 + rng.randint(-3, 3)), h - ph - 1)
        fl[ox:ox + pw, oy:oy + ph] = first
        if style.mirror:
            fl = _largest_component(fl | fl[::-1, :])
        cave = fl.copy() if is_cave else None
        _accrete(rng, fl, doors, style)
        _add_loops(rng, fl, doors)
    _fix_diagonals(rng, fl)
    _clean_doors(fl, doors)

    vault, lock = None, None
    if lock_tile is not None:
        found = _add_vault(rng, fl)
        if found is None:
            return None
        vault, lock = found
    hidden, crack, cracks = None, None, ()
    if hidden_room:  # built just like a locked room, but its way in is a wall to blow open
        found = _add_vault(rng, fl)
        if found is not None:
            hidden, crack = found
            cracks = _widen_crack(rng, fl, hidden, crack)
    shut = np.zeros((w, h), bool)  # the rooms that start closed off
    for room in (vault, hidden):
        if room is not None:
            shut |= room

    taken = doors | {p for p in (lock, *cracks) if p}
    sites = [s for s in _stair_sites(fl, taken) if not shut[s[1]]]
    if len(sites) < 2:
        return None
    up, up_front = rng.choice(sites)
    dist = _bfs(fl, up_front)
    far = sorted((s for s in sites if s[0] != up and dist[s[1]] > 0), key=lambda s: dist[s[1]])
    if not far:
        return None
    down, down_front = rng.choice(far[len(far) * 3 // 4:])

    # The stairs and the locked room keep their surroundings, so nothing floods them.
    keep = np.zeros((w, h), bool)
    for x, y in (up, up_front, down, down_front):
        keep[max(0, x - 1):x + 2, max(0, y - 1):y + 2] = True
    for room, ways in ((vault, (lock,)), (hidden, cracks)):
        if room is not None:
            for way in ways:
                keep |= _dilate(room | _cell(way))[1:-1, 1:-1]
    sealed = fl.copy()  # the level without its closed rooms, which get no water or pits
    for room, ways in ((vault, (lock,)), (hidden, cracks)):
        if room is not None:
            sealed[room] = False
            for way in ways:
                sealed[way] = False
    goals = [down_front]
    for way in (lock, crack):
        if way:
            goals += [(way[0] + dx, way[1] + dy) for dx, dy in DIRS4 if sealed[way[0] + dx, way[1] + dy]]
    terrain = _add_terrain(rng, sealed, doors, keep, up_front, tuple(goals), depth)
    if terrain is None:
        return None
    deep, shallow, pits, lava = terrain

    tiles = np.full((w, h), WALL, np.uint8)
    tiles[fl | sealed] = FLOOR
    tiles[shallow] = SHALLOW
    tiles[deep] = DEEP
    tiles[pits] = PIT
    tiles[lava] = LAVA
    for p in doors:
        tiles[p] = DOOR
    tiles[up] = STAIRS_UP
    tiles[down] = STAIRS_DOWN
    if lock:
        tiles[lock] = lock_tile
    for c in cracks:
        tiles[c] = CRACKED
    torches = _add_torches(rng, tiles, shut if shut.any() else None, (up, down))
    for torch, front in torches:
        tiles[torch] = TORCH
        keep[front] = True
    _add_plants(rng, tiles, keep)
    _add_pond(rng, tiles, keep)
    return GeneratedLevel(tiles, up, up_front, down, down_front, vault, lock, tuple(torches),
                          hidden=hidden, cracks=cracks, cave=cave)


def generate(seed: int, depth: int, lock_tile: int | None = None, hidden_room: bool = False) -> GeneratedLevel:
    """Same seed and depth always give the same level. `lock_tile` adds a locked room, and
    `hidden_room` one behind a cracked wall, if it fits."""
    rng = random.Random(f"{seed}:{depth}")
    for _ in range(50):
        if depth == ATRIUM_FLOOR:
            level = _atrium(rng)
        elif depth == LAST_FLOOR:
            level = _lair(rng)
        elif depth >= TOWER_FIRST:
            level = _tower(rng)
        else:
            level = _try_generate(rng, depth, lock_tile, hidden_room)
        if level is not None:
            return level
    raise RuntimeError("level generation failed")
