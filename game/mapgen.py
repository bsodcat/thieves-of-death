"""Brogue-style level generation.

Brogue doesn't use "rooms and corridors". It grows a level by accretion:
start with one big room, then repeatedly generate a random room shape
(sometimes with a hallway sticking out of it) and try to fit it against a
wall of what already exists, connected by a single doorway. Afterwards it
adds loops by knocking through walls that separate two areas which are
far apart by foot. This module follows that recipe.

Water and pits go in last, over the finished level. Lakes and rivers run through
rock as well as rooms, so they can cut the level in two; wherever they do, a ford
is left across. The stairs and every walkable tile stay reachable on foot.
"""
from __future__ import annotations

import random
from collections import deque
from dataclasses import dataclass

import numpy as np

from .constants import LAKE_CHANCE, MAP_H, MAP_W, PIT_CHANCE, PIT_COUNT, RIVER_CHANCE
from .tiles import DEEP, DOOR, FLOOR, PIT, SHALLOW, STAIRS_DOWN, STAIRS_UP, WALL

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


ROOM_DESIGNS = (
    (_room_small, 4),
    (_room_large, 3),
    (_room_cross, 3),
    (_room_circle, 2),
    (_room_small_cave, 2),
)


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
    """Wall cells with exactly one floor neighbour (an alcove in a straight wall)."""
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


def _pits(rng: random.Random) -> np.ndarray:
    m = np.zeros((MAP_W, MAP_H), bool)
    for _ in range(rng.randint(*PIT_COUNT)):
        hole = _room_circle(rng) if rng.random() < 0.3 else np.ones((rng.randint(1, 3), rng.randint(1, 3)), bool)
        pw, ph = hole.shape
        ox, oy = rng.randint(1, MAP_W - pw - 1), rng.randint(1, MAP_H - ph - 1)
        m[ox:ox + pw, oy:oy + ph] |= hole
    return m


def _rejoin(ground: np.ndarray, cuts: np.ndarray, start: Point) -> set:
    """The cells to clear to link one cut-off patch of ground back to `start`, or nothing if
    all of it is connected. It's the shortest crossing, so a river gets a narrow ford."""
    reached = _bfs(ground, start) >= 0
    if not (ground & ~reached).any():
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
            if ground[n]:  # reached the cut-off patch: walk back over what was crossed
                path, at = set(), (x, y)
                while at is not None and cuts[at]:
                    path.add(at)
                    at = came[at]
                return path
            if cuts[n]:
                came[n] = (x, y)
                queue.append(n)
    raise AssertionError("cut-off ground with no way across")


def _corners(ground: np.ndarray, cuts: np.ndarray, keep: np.ndarray) -> set | None:
    """A cell to clear so no two tiles of ground touch only diagonally: water or a pit if it
    can be, or else rock beside a ford. None if neither can be cleared."""
    w, h = ground.shape
    for x in range(w - 1):
        for y in range(h - 1):
            a, b, c, d = ground[x, y], ground[x + 1, y], ground[x, y + 1], ground[x + 1, y + 1]
            if (a and d and not b and not c) or (b and c and not a and not d):
                pair = ((x + 1, y), (x, y + 1)) if a and d else ((x, y), (x + 1, y + 1))
                free = sorted((p for p in pair if not keep[p]), key=lambda p: not cuts[p])
                return set(free[:1]) or None
    return set()


def _add_terrain(rng: random.Random, fl: np.ndarray, doors: set, keep: np.ndarray, start: Point):
    """Returns the deep, shallow and pit masks, or None if this level can't be made whole.
    Nothing is put on the `keep` cells."""
    deep = np.zeros_like(fl)
    if rng.random() < LAKE_CHANCE:
        deep |= _lake(rng)
    if rng.random() < RIVER_CHANCE:
        deep |= _river(rng)
    deep &= ~keep
    pits = _pits(rng) & fl & ~keep & ~deep if rng.random() < PIT_CHANCE else np.zeros_like(fl)
    for x, y in doors:
        pits[x, y] = False
    doors -= {p for p in doors if deep[p]}
    _clean_doors(fl | deep, doors)

    while True:
        ground = fl & ~deep & ~pits
        clear = _rejoin(ground, deep | pits, start) or _corners(ground, deep | pits, keep)
        if clear is None:
            return None
        if not clear:
            break
        for p in clear:
            deep[p] = pits[p] = False
            fl[p] = True
    _clean_doors(ground, doors)  # a door opening onto water is just a gap in the wall
    shallow = _dilate(deep)[1:-1, 1:-1] & fl & ~deep & ~pits & ~keep
    return deep, shallow, pits


# ------------------------------------------------------------------ main

def _try_generate(rng: random.Random, lock_tile: int | None = None) -> GeneratedLevel | None:
    w, h = MAP_W, MAP_H
    fl = np.zeros((w, h), bool)
    doors: set[Point] = set()

    first = _room_cave(rng, rng.randint(24, 34), rng.randint(12, 18)) if rng.random() < 0.5 else _room_cross(rng)
    pw, ph = first.shape
    ox = min(max(1, (w - pw) // 2 + rng.randint(-12, 12)), w - pw - 1)
    oy = min(max(1, (h - ph) // 2 + rng.randint(-3, 3)), h - ph - 1)
    fl[ox:ox + pw, oy:oy + ph] = first

    designs = [d for d, _ in ROOM_DESIGNS]
    weights = [wt for _, wt in ROOM_DESIGNS]
    for _ in range(150):
        room = rng.choices(designs, weights)[0](rng)
        d = rng.choice(DIRS4)
        hallway = rng.randint(2, 7) if rng.random() < 0.3 else 0
        piece, site = _make_piece(rng, room, d, hallway)
        door = _try_attach(rng, fl, piece, site, d)
        if door:
            fl[door] = True
            if rng.random() < (0.5 if hallway else 0.7):
                doors.add(door)

    _add_loops(rng, fl, doors)
    _fix_diagonals(rng, fl)
    _clean_doors(fl, doors)

    vault, lock = None, None
    if lock_tile is not None:
        found = _add_vault(rng, fl)
        if found is None:
            return None
        vault, lock = found

    taken = doors | ({lock} if lock else set())
    sites = [s for s in _stair_sites(fl, taken) if vault is None or not vault[s[1]]]
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
    if vault is not None:
        keep |= _dilate(vault | _cell(lock))[1:-1, 1:-1]
    sealed = fl.copy()  # the level without the locked room, which gets no water or pits
    if vault is not None:
        sealed[vault], sealed[lock] = False, False
    terrain = _add_terrain(rng, sealed, doors, keep, up_front)
    if terrain is None:
        return None
    deep, shallow, pits = terrain

    tiles = np.full((w, h), WALL, np.uint8)
    tiles[fl | sealed] = FLOOR
    tiles[shallow] = SHALLOW
    tiles[deep] = DEEP
    tiles[pits] = PIT
    for p in doors:
        tiles[p] = DOOR
    tiles[up] = STAIRS_UP
    tiles[down] = STAIRS_DOWN
    if lock:
        tiles[lock] = lock_tile
    return GeneratedLevel(tiles, up, up_front, down, down_front, vault, lock)


def generate(seed: int, depth: int, lock_tile: int | None = None) -> GeneratedLevel:
    """Same seed and depth always give the same level. `lock_tile` adds a locked room."""
    rng = random.Random(f"{seed}:{depth}")
    for _ in range(50):
        level = _try_generate(rng, lock_tile)
        if level is not None:
            return level
    raise RuntimeError("level generation failed")
