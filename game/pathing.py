"""Route finding for auto-walking. Runs on the client, over tiles the player has seen,
so it can never reveal anything about the map. No tcod here."""
from __future__ import annotations

from collections import deque

import numpy as np

# Straight steps first, so routes prefer them when a diagonal isn't any shorter.
DIRECTIONS = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))


def cheb(a: tuple[int, int], b: tuple[int, int]) -> int:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def next_step(walkable: np.ndarray, start: tuple[int, int], goal: tuple[int, int],
              blocked=(), enter_goal: bool = False) -> tuple[int, int] | None:
    """The first step of a shortest route from start to goal, or of the route to the closest
    place it can reach if there's no way through. None if it's already as close as it can get.

    `blocked` tiles are walked around. `enter_goal` allows the last step onto a goal that
    isn't walkable, for stairs set into a wall. Like the server, it won't cut wall corners.
    """
    w, h = walkable.shape
    blocked = set(blocked) - {goal}
    first: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
    queue = deque([start])
    best, best_dist = start, cheb(start, goal)
    while queue:
        x, y = queue.popleft()
        for dx, dy in DIRECTIONS:
            n = (x + dx, y + dy)
            if n in first or not (0 <= n[0] < w and 0 <= n[1] < h) or n in blocked:
                continue
            if dx and dy and not (walkable[n[0], y] and walkable[x, n[1]]):
                continue
            step = first[(x, y)] or (dx, dy)
            if n == goal and (walkable[n] or enter_goal):
                return step
            if not walkable[n]:
                continue
            first[n] = step
            queue.append(n)
            dist = cheb(n, goal)
            if dist < best_dist:
                best, best_dist = n, dist
    return first[best]
