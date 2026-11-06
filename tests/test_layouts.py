"""How levels are laid out by depth: caves, round rooms, mirrored rooms, and floors 50 to 59."""
import unittest

import numpy as np

from game import mapgen
from game.tiles import DEEP, WALKABLE, WALL


def open_floor(g):
    return g.tiles != WALL


def symmetry(depth, seeds=range(10)):
    shares = []
    for seed in seeds:
        f = open_floor(mapgen.generate(seed, depth))
        shares.append((f & f[::-1]).sum() / f.sum())
    return float(np.mean(shares))


class StyleTests(unittest.TestCase):
    def test_the_bands(self):
        self.assertEqual(mapgen._style(8), mapgen.Style())
        self.assertEqual(mapgen._style(9).designs, mapgen.CAVES)
        self.assertEqual(mapgen._style(14).cave_first, 1.0)
        self.assertEqual(mapgen._style(15).designs, mapgen.ROUNDS)
        self.assertEqual(mapgen._style(40).mirror, 0.0)
        self.assertGreater(mapgen._style(41).mirror, 0.0)

    def test_caves_after_floor_8(self):
        for seed in range(6):
            self.assertIsNotNone(mapgen.generate(seed, 10).cave, seed)

    def test_mirrored_floors_are_more_symmetrical(self):
        self.assertGreater(symmetry(45), symmetry(30) + 0.05)

    def test_every_new_layout_is_used_on_floors_50_to_59(self):
        used = {mapgen.ODD_LAYOUTS[(d - mapgen.ODD_FLOORS[0]) % len(mapgen.ODD_LAYOUTS)]
                for d in range(mapgen.ODD_FLOORS[0], mapgen.ODD_FLOORS[1] + 1)}
        self.assertEqual(used, set(mapgen.ODD_LAYOUTS))

    def test_stairs_join_up_on_every_kind_of_floor(self):
        for depth in (9, 12, 15, 30, 41, 45, *range(50, 60), 60, 88):
            for seed in range(3):
                g = mapgen.generate(seed, depth)
                walk = WALKABLE[g.tiles] | (g.tiles == DEEP)
                self.assertGreaterEqual(mapgen._bfs(walk, g.up_front)[g.down_front], 0, (seed, depth))

    def test_a_maze_is_mostly_narrow_passages(self):
        g = mapgen.generate(1, 50)
        f = open_floor(g)
        across = f[1:-1, 1:-1] & f[:-2, 1:-1] & f[2:, 1:-1] & f[1:-1, :-2] & f[1:-1, 2:]
        self.assertLess(across.sum() / f.sum(), 0.35)

    def test_the_same_seed_gives_the_same_new_floor(self):
        for depth in range(50, 55):
            self.assertTrue(np.array_equal(mapgen.generate(4, depth).tiles, mapgen.generate(4, depth).tiles))


if __name__ == "__main__":
    unittest.main()
