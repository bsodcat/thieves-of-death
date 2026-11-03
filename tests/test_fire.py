"""The wand of fire's burning ground and grass, monsters running from it, and the stains monsters leave."""
import unittest

import numpy as np

from game.constants import FIRE_SECONDS, GRASS_FIRE_SECONDS, MAP_X, MAP_Y, TICKS_PER_TURN
from game.items import make_wand
from game.render import STAIN_LOOKS
from game.tiles import ASH, GRASS, LAVA, DEEP, SHALLOW, POND
from game.world import World, cheb
from helpers_210 import add, deliver, empty_world, open_spot, put, seconds, view_of


class FireTests(unittest.TestCase):
    def setUp(self):
        self.w, self.lvl, self.p = empty_world()
        self.x, self.y = open_spot(self.lvl, 4)
        put(self.lvl, self.p, self.x, self.y)

    def zap(self, m):
        self.w._stash(self.p, make_wand())
        self.w.submit(self.p, {"a": "use", "slot": 0})

    def test_the_ground_around_the_target_burns_then_goes_out(self):
        m = add(self.w, self.lvl, "ogre", self.x + 3, self.y, state="wandering")
        self.zap(m)
        self.assertIn((m.x, m.y), self.lvl.fire)
        self.assertEqual(len(self.lvl.fire), 9)
        self.assertIn([m.x, m.y], self.w.state_for(self.p)["fire"])
        self.w.advance(seconds(FIRE_SECONDS[1]) + 10)
        self.assertEqual(self.lvl.fire, {})

    def test_grass_burns_away_to_ash_and_spreads(self):
        for dx in range(-4, 5):
            for dy in range(-4, 5):
                self.lvl._set_tile(self.x + dx, self.y + dy, GRASS)
        self.p.god = True
        self.w._start_fire(self.lvl, self.x + 3, self.y, self.p)
        for _ in range(40):
            self.w.advance(seconds(0.5))
        burned = sum(self.lvl.tiles[self.x + dx, self.y + dy] == ASH for dx in range(-4, 5) for dy in range(-4, 5))
        self.assertGreater(burned, 30)  # far more than the nine it started on
        self.assertEqual(self.lvl.fire, {})  # and it all burned out

    def test_monsters_in_it_catch_fire_and_players_get_burned(self):
        m = add(self.w, self.lvl, "ogre", self.x + 2, self.y, state="wandering")
        m.frozen_until = 10 ** 9  # so it stays in the flames
        self.w._start_fire(self.lvl, self.x + 1, self.y, self.p)
        self.w.advance(seconds(1.1))
        self.assertTrue(m.burning)
        self.assertLess(self.p.hp, self.p.max_hp)

    def test_burning_and_badly_hurt_monsters_run(self):
        m = add(self.w, self.lvl, "goblin", self.x + 2, self.y, target=self.p)
        m.burning, m.hp = 3, 3
        self.w._monster_turn(m, self.lvl)
        self.assertEqual(cheb(m, self.p), 3)

    def test_but_not_while_theyre_healthy(self):
        m = add(self.w, self.lvl, "goblin", self.x + 2, self.y, target=self.p)
        m.burning = 3
        self.w._monster_turn(m, self.lvl)
        self.assertEqual(cheb(m, self.p), 1)


class StainTests(unittest.TestCase):
    def setUp(self):
        self.w, self.lvl, self.p = empty_world()
        self.x, self.y = open_spot(self.lvl)
        put(self.lvl, self.p, self.x, self.y)

    def stain_of(self, kind):
        m = add(self.w, self.lvl, kind, self.x + 2, self.y)
        self.w._kill(m, self.p)
        return self.lvl.stains.get((self.x + 2, self.y))

    def test_each_leaves_its_own(self):
        self.assertEqual(self.stain_of("rat"), "blood")
        self.assertEqual(self.stain_of("slime"), "goo")
        self.assertEqual(self.stain_of("skeleton_warrior"), "bones")
        self.assertEqual(self.stain_of("zombie"), "rot")

    def test_ghosts_leave_nothing(self):
        self.assertIsNone(self.stain_of("ghost"))

    def test_players_see_them_and_remember_them(self):
        v = view_of(self.w, self.p)
        self.stain_of("rat")
        deliver(self.w, v, self.p.id)
        self.assertEqual(v.stains[1][(self.x + 2, self.y)], "blood")
        frame = v.draw()
        self.assertEqual(tuple(frame["bg"][MAP_X + self.x + 2, MAP_Y + self.y]), STAIN_LOOKS["blood"][0])
        fresh = view_of(self.w, self.p)  # someone arriving later still sees it
        self.assertEqual(fresh.stains[1][(self.x + 2, self.y)], "blood")


class LavaTests(unittest.TestCase):
    def test_lava_never_touches_water(self):
        lava_seen = 0
        for seed in range(4):
            w = World(seed)
            for depth in range(51, 64):
                tiles = w.level(depth).tiles
                wet = np.isin(tiles, (DEEP, SHALLOW, POND))
                for x, y in np.argwhere(tiles == LAVA):
                    lava_seen += 1
                    self.assertFalse(wet[x - 1:x + 2, y - 1:y + 2].any(), (seed, depth, x, y))
        self.assertGreater(lava_seen, 0)


if __name__ == "__main__":
    unittest.main()
