"""Field of view and Dijkstra maps.

Uses libtcod (python-tcod) when it is installed, which is fast C code.
If tcod is missing or fails its self-test, a pure-Python version is used so
the server can still run (slower, but fine for a few players).

All arrays are indexed [x, y] with shape (width, height).
"""
from __future__ import annotations

import heapq
import math
import warnings
from fractions import Fraction

import numpy as np

INF = int(np.iinfo(np.int32).max)
CARDINAL_COST, DIAGONAL_COST = 2, 3  # ~1 : 1.41, keeps paths natural-looking


def _fov_python(transparent: np.ndarray, x: int, y: int, radius: int = 0) -> np.ndarray:
    """Symmetric shadowcasting (Albert Ford's algorithm)."""
    w, h = transparent.shape
    out = np.zeros((w, h), dtype=bool)
    out[x, y] = True
    r2 = radius * radius if radius > 0 else None
    half = Fraction(1, 2)

    def blocking(tx: int, ty: int) -> bool:
        return not (0 <= tx < w and 0 <= ty < h) or not transparent[tx, ty]

    for quadrant in range(4):
        def transform(row: int, col: int, q: int = quadrant) -> tuple[int, int]:
            if q == 0:
                return x + col, y - row
            if q == 1:
                return x + row, y + col
            if q == 2:
                return x + col, y + row
            return x - row, y + col

        stack = [(1, Fraction(-1), Fraction(1))]
        while stack:
            depth, start, end = stack.pop()
            if r2 is not None and depth > radius:
                continue
            prev = None
            for col in range(math.floor(depth * start + half), math.ceil(depth * end - half) + 1):
                tx, ty = transform(depth, col)
                wall = blocking(tx, ty)
                if wall or depth * start <= col <= depth * end:
                    if 0 <= tx < w and 0 <= ty < h and (r2 is None or (tx - x) ** 2 + (ty - y) ** 2 <= r2):
                        out[tx, ty] = True
                if prev is True and not wall:
                    start = Fraction(2 * col - 1, 2 * depth)
                if prev is False and wall:
                    stack.append((depth + 1, start, Fraction(2 * col - 1, 2 * depth)))
                prev = wall
            if prev is False:
                stack.append((depth + 1, start, end))
    return out


def _dijkstra_python(walkable: np.ndarray, goals: list[tuple[int, int]]) -> np.ndarray:
    w, h = walkable.shape
    walk = walkable.tolist()
    dist = np.full((w, h), INF, dtype=np.int32)
    best = {}
    heap = []
    for gx, gy in goals:
        best[(gx, gy)] = 0
        heap.append((0, gx, gy))
    heapq.heapify(heap)
    while heap:
        d, x, y = heapq.heappop(heap)
        if d > best.get((x, y), INF):
            continue
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if not (dx or dy):
                    continue
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h and walk[nx][ny]:
                    nd = d + (DIAGONAL_COST if dx and dy else CARDINAL_COST)
                    if nd < best.get((nx, ny), INF):
                        best[(nx, ny)] = nd
                        heapq.heappush(heap, (nd, nx, ny))
    for (x, y), d in best.items():
        dist[x, y] = d
    return dist


compute_fov = _fov_python
dijkstra = _dijkstra_python
BACKEND = "python"

try:
    import tcod.map
    import tcod.path

    try:
        import tcod.constants as _tc
    except ImportError:  # very old tcod
        import tcod as _tc
    _FOV_ALGO = getattr(_tc, "FOV_SYMMETRIC_SHADOWCAST", None)
    if _FOV_ALGO is None:
        _FOV_ALGO = getattr(_tc, "FOV_RESTRICTIVE", 0)

    def _fov_tcod(transparent: np.ndarray, x: int, y: int, radius: int = 0) -> np.ndarray:
        return tcod.map.compute_fov(transparent, (x, y), radius, light_walls=True, algorithm=_FOV_ALGO)

    def _dijkstra_tcod(walkable: np.ndarray, goals: list[tuple[int, int]]) -> np.ndarray:
        dist = np.full(walkable.shape, INF, dtype=np.int32)
        for gx, gy in goals:
            dist[gx, gy] = 0
        cost = walkable.astype(np.int32)
        try:
            tcod.path.dijkstra2d(dist, cost, CARDINAL_COST, DIAGONAL_COST, out=dist)
        except TypeError:  # older tcod without `out=`: modifies in place
            tcod.path.dijkstra2d(dist, cost, CARDINAL_COST, DIAGONAL_COST)
        return dist

    # Self-test so a broken or unexpected tcod version can't take the server down.
    _t = np.ones((5, 5), dtype=bool)
    _t[2, 1] = False
    _v = _fov_tcod(_t, 2, 2)
    _d = _dijkstra_tcod(_t, [(0, 0)])
    if _v.shape != (5, 5) or not _v[2, 2] or _d[0, 0] != 0 or _d[1, 1] != DIAGONAL_COST:
        raise RuntimeError("unexpected results")
    compute_fov, dijkstra, BACKEND = _fov_tcod, _dijkstra_tcod, "tcod"
except ImportError:
    pass
except Exception as exc:  # pragma: no cover - depends on the installed tcod
    warnings.warn(f"tcod failed its self-test ({exc!r}); using the pure-Python fallback")
