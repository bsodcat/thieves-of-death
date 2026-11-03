"""Bombs, the cracked walls they break, the hidden rooms behind them and the fairies in those."""
import unittest

import numpy as np

from game.constants import BOMB_SECONDS, FAIRY_BOOST, HIDDEN_ROOM_CHANCE
from game.items import make_item
from game.tiles import ALTAR, CRACKED, FG, FLOOR, GLYPH, NAMES, DESCRIPTIONS, WALL
from game.world import DIRS8, World
from helpers_210 import add, empty_world, open_spot, put, said, seconds


def hidden_floor(seeds=range(40)):
    """A built floor with a hidden room, and its world."""
    for seed in seeds:
        w = World(seed)
        for depth in range(2, 12):
            lvl = w.level(depth)
            if lvl.hidden is not None:
                return w, lvl
    raise AssertionError("no hidden room anywhere")


def beside_crack(lvl):
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        n = (lvl.crack[0] + dx, lvl.crack[1] + dy)
        if lvl.mainland[n] and n not in lvl.occupant:
            return n
    raise AssertionError("can't reach the crack")


class HiddenRoomTests(unittest.TestCase):
    def test_never_with_a_locked_room_or_an_altar(self):
        for seed in range(12):
            w = World(seed)
            for depth in range(2, 30):
                lvl = w.level(depth)
                if lvl.hidden is not None:
                    self.assertNotIn(depth, w.locked_rooms)
                    self.assertFalse((lvl.tiles == ALTAR).any(), (seed, depth))

    def test_about_a_third_of_the_floors_that_can(self):
        tried = found = 0
        for seed in range(15):
            w = World(seed)
            for depth in range(2, 30):
                if depth not in w.locked_rooms and not w._cult_planned(depth):
                    tried += 1
                    found += w.level(depth).hidden is not None
        self.assertTrue(0.2 < found / tried <= HIDDEN_ROOM_CHANCE + 0.05, found / tried)

    def test_shut_off_until_the_wall_breaks(self):
        w, lvl = hidden_floor()
        self.assertEqual(lvl.tiles[lvl.crack], CRACKED)
        self.assertFalse(lvl.walkable[lvl.crack])
        self.assertFalse(lvl.mainland[lvl.hidden].any())
        self.assertFalse(any(lvl.hidden[c] for c in lvl.floor_cells))  # nothing spawns in there
        fairy = next(n for n in lvl.npcs if n.role == "fairy")
        self.assertTrue(lvl.hidden[fairy.x, fairy.y])

    def test_the_wall_is_only_a_shade_off(self):
        self.assertEqual(GLYPH[CRACKED], GLYPH[WALL])
        self.assertEqual(NAMES[CRACKED], NAMES[WALL])
        self.assertEqual(DESCRIPTIONS[CRACKED], DESCRIPTIONS[WALL])
        diff = np.abs(FG[CRACKED].astype(int) - FG[WALL].astype(int))
        self.assertTrue(0 < diff.max() <= 15, diff)


class BombTests(unittest.TestCase):
    def test_it_breaks_the_cracked_wall_open(self):
        w, lvl = hidden_floor()
        p = w.join("Alice")
        w.warp(p, lvl.depth)
        put(lvl, p, *beside_crack(lvl))
        p.god = True
        w._stash(p, make_item("bomb"))
        w.submit(p, {"a": "use", "slot": 0})
        self.assertEqual(len(lvl.bombs), 1)
        self.assertEqual(p.pack, [])
        w.advance(seconds(BOMB_SECONDS) - 10)
        self.assertEqual(lvl.tiles[lvl.crack], CRACKED)  # not yet
        w.advance(20)
        self.assertIsNone(lvl.crack)
        self.assertTrue(lvl.mainland[lvl.hidden].all())
        self.assertIn("room behind it", said(w))

    def test_it_hurts_whoever_is_too_close(self):
        w, lvl, p = empty_world()
        x, y = open_spot(lvl)
        put(lvl, p, x, y)
        near = add(w, lvl, "ogre", x + 1, y)
        far = add(w, lvl, "ogre", x + 3, y)
        near.frozen_until = far.frozen_until = 10 ** 9  # so neither walks in or out of the blast
        w._stash(p, make_item("bomb"))
        w.submit(p, {"a": "use", "slot": 0})
        w.advance(seconds(BOMB_SECONDS) + 5)
        self.assertLess(p.hp, p.max_hp)
        self.assertLess(near.hp, near.max_hp)
        self.assertEqual(far.hp, far.max_hp)

    def test_bombs_stack_and_merchants_never_run_out(self):
        from test_shop import with_merchant
        w, lvl, m, step, (a,) = with_merchant(kinds=("sword", "bomb"))
        a.gold = 1000
        for _ in range(3):
            w.submit(a, {"a": "buy", "id": 1})
            w.advance(200)
        self.assertIn(1, m.stock)
        bombs = [i for i in a.pack if i.kind == "bomb"]
        self.assertEqual(len(bombs), 1)
        self.assertEqual(bombs[0].count, 3)
        self.assertEqual(a.gold, 1000 - 3 * bombs[0].price)

    def test_every_merchant_sells_them(self):
        for seed in range(20):
            m = World(seed).level(5).merchant
            if m:
                self.assertIn("bomb", [i.kind for i in m.stock.values()])


class FairyTests(unittest.TestCase):
    def test_it_blesses_everyone_alive_and_goes(self):
        w, lvl = hidden_floor()
        a, b = w.join("Alice"), w.join("Bob")
        w.warp(a, lvl.depth)
        fairy = next(n for n in lvl.npcs if n.role == "fairy")
        lvl.open_crack()
        spot = next((fairy.x + dx, fairy.y + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                    if lvl.walkable[fairy.x + dx, fairy.y + dy] and (fairy.x + dx, fairy.y + dy) not in lvl.occupant)
        put(lvl, a, *spot)
        before = b.max_hp
        w.submit(a, {"a": "move", "dx": fairy.x - a.x, "dy": fairy.y - a.y})
        boost = round(before * FAIRY_BOOST)
        self.assertEqual(a.max_hp, before + boost)
        self.assertEqual(b.max_hp, before + boost)
        self.assertNotIn(fairy, lvl.npcs)
        self.assertNotIn((fairy.x, fairy.y), lvl.occupant)
        self.assertIn("fairy", said(w))


if __name__ == "__main__":
    unittest.main()
