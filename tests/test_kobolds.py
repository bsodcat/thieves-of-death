"""Kobolds and their leaders and scouts, the cult leader and mage, and the skeleton war bands."""
import unittest
from unittest import mock

from game.constants import (KOBOLD_LEADER_FLOORS, KOBOLD_SCOUT_FLOORS, KOBOLD_SCOUT_MOST, SKELETON_EVERY,
                            SKELETON_FLOORS, SKELETON_MOST, TICKS_PER_SECOND)
from game.entities import MONSTERS
from game.items import make_item
from game.world import World, cheb
from helpers_210 import add, empty_world, logged, open_spot, put, said


def count(lvl, kind):
    return sum(m.kind == kind for m in lvl.monsters)


class WhereTheyLiveTests(unittest.TestCase):
    def test_leaders_two_at_most_and_only_on_their_floors(self):
        seen = 0
        for seed in range(6):
            w = World(seed)
            for depth in range(1, 32):
                n = count(w.level(depth), "kobold_leader")
                self.assertLessEqual(n, 2)
                if not KOBOLD_LEADER_FLOORS[0] <= depth <= KOBOLD_LEADER_FLOORS[1]:
                    self.assertEqual(n, 0, depth)
                seen += n
        self.assertGreater(seen, 0)

    def test_scouts_three_at_most_and_only_on_their_floors(self):
        seen = 0
        for seed in range(10):
            w = World(seed)
            for depth in range(8, 18):
                n = count(w.level(depth), "kobold_scout")
                self.assertLessEqual(n, KOBOLD_SCOUT_MOST)
                if not KOBOLD_SCOUT_FLOORS[0] <= depth <= KOBOLD_SCOUT_FLOORS[1]:
                    self.assertEqual(n, 0, depth)
                seen += n
        self.assertGreater(seen, 0)

    def test_the_looks_asked_for(self):
        self.assertEqual(MONSTERS["kobold_leader"]["glyph"], "K")
        self.assertEqual(MONSTERS["kobold_scout"]["glyph"], "k")
        r, g, b = MONSTERS["kobold_leader"]["color"]
        self.assertTrue(b > r and b > g)  # blue
        r, g, b = MONSTERS["kobold_scout"]["color"]
        self.assertTrue(r > g and r > b)  # red
        r, g, b = MONSTERS["kobold"]["color"]
        self.assertTrue(g > r and g > b)  # green

    def test_skeleton_bands_every_third_floor_from_50_to_70(self):
        w = World(3)
        low, high = SKELETON_FLOORS
        for depth in range(low, high + 1):
            n = count(w.level(depth), "skeleton_warrior")
            self.assertLessEqual(n, SKELETON_MOST)
            if (depth - low) % SKELETON_EVERY:
                self.assertEqual(n, 0, depth)
            else:
                self.assertGreaterEqual(n, 3, depth)

    def test_a_mage_is_always_a_floor_from_a_cult(self):
        found = 0
        for seed in range(5):
            w = World(seed)
            for depth in range(9, 60):
                if count(w.level(depth), "cult_mage"):
                    found += 1
                    self.assertTrue(w._cult_planned(depth - 1) or w._cult_planned(depth + 1), (seed, depth))
        self.assertGreater(found, 0)


class KoboldTests(unittest.TestCase):
    def setUp(self):
        self.w, self.lvl, self.p = empty_world()
        self.x, self.y = open_spot(self.lvl)
        put(self.lvl, self.p, self.x, self.y)

    def test_a_kobold_sometimes_kills_a_rat_beside_it(self):
        k = add(self.w, self.lvl, "kobold", self.x + 3, self.y, state="wandering")
        rat = add(self.w, self.lvl, "rat", self.x + 3, self.y + 1, state="wandering")
        with mock.patch.object(self.w.rng, "random", return_value=0.01):
            self.w._monster_turn(k, self.lvl)
        self.assertNotIn(rat, self.lvl.monsters)
        self.assertIn(k, self.lvl.monsters)

    def test_but_rarely(self):
        k = add(self.w, self.lvl, "kobold", self.x + 3, self.y, state="wandering")
        rat = add(self.w, self.lvl, "rat", self.x + 3, self.y + 1, state="wandering")
        with mock.patch.object(self.w.rng, "random", return_value=0.5):
            self.assertFalse(self.w._turn_on_rat(k, self.lvl))
        self.assertIn(rat, self.lvl.monsters)

    def test_a_lone_kobold_runs(self):
        k = add(self.w, self.lvl, "kobold", self.x + 2, self.y, target=self.p)
        self.w._monster_turn(k, self.lvl)
        self.assertEqual(cheb(k, self.p), 3)

    def test_with_friends_near_it_fights(self):
        k = add(self.w, self.lvl, "kobold", self.x + 2, self.y, target=self.p)
        add(self.w, self.lvl, "kobold", self.x + 3, self.y + 2, target=self.p)
        self.w._monster_turn(k, self.lvl)
        self.assertEqual(cheb(k, self.p), 1)

    def test_a_hurt_kobold_throws_rocks_now_and_then(self):
        k = add(self.w, self.lvl, "kobold", self.x + 3, self.y, target=self.p)
        k.hp = 2
        with mock.patch.object(self.w.rng, "random", return_value=0.01):
            self.w._monster_turn(k, self.lvl)
        rocks = [m for _, m in self.w.drain_outbox() if m.get("kind") == "rock"]
        self.assertTrue(rocks)
        self.assertEqual(cheb(k, self.p), 3)  # it threw instead of running

    def test_the_leaders_spear_reaches_two_tiles(self):
        k = add(self.w, self.lvl, "kobold_leader", self.x + 2, self.y, target=self.p)
        self.w._monster_turn(k, self.lvl)
        self.assertEqual(cheb(k, self.p), 2)
        self.assertRegex(logged(self.w), r"kobold leader#\d+ (hit|missed) Alice")

    def test_the_leader_backs_off_to_keep_a_tile_between(self):
        k = add(self.w, self.lvl, "kobold_leader", self.x + 1, self.y, target=self.p)
        self.w._monster_turn(k, self.lvl)
        self.assertEqual(cheb(k, self.p), 2)

    def test_scouts_throw_fire_and_wards_stop_it(self):
        x, y = open_spot(self.lvl, 5)
        put(self.lvl, self.p, x, y)
        s = add(self.w, self.lvl, "kobold_scout", x + 5, y, target=self.p)
        self.p.reflect_until = 10 ** 9
        self.w._monster_turn(s, self.lvl)
        self.assertEqual(self.p.hp, self.p.max_hp)
        self.assertIn("ward", said(self.w))
        self.assertGreater(s.ready_at, self.w.clock)


class MageTests(unittest.TestCase):
    def setUp(self):
        self.w, self.lvl, self.p = empty_world()
        self.x, self.y = open_spot(self.lvl)
        put(self.lvl, self.p, self.x, self.y)
        self.m = add(self.w, self.lvl, "cult_mage", self.x + 3, self.y + 3, target=self.p)

    def test_it_rises_and_melee_cant_reach_it(self):
        self.m.ready_at = 10 ** 9
        self.w._monster_turn(self.m, self.lvl)
        self.assertTrue(self.w._floating(self.m))
        self.assertIn("glowing violet", said(self.w))
        self.lvl.move(self.m, self.x + 1, self.y)
        self.w.submit(self.p, {"a": "move", "dx": 1, "dy": 0})
        self.assertEqual(self.m.hp, self.m.max_hp)
        self.assertIn("out of reach", said(self.w))
        mage = next(e for e in self.w.state_for(self.p)["ents"] if e["id"] == self.m.id)
        self.assertTrue(mage["float"])

    def test_but_ranged_attacks_do(self):
        self.m.float_until = 10 ** 9
        self.m.state = "wandering"  # so the shot can't miss
        self.w._stash(self.p, make_item("bow"))
        arrows = make_item("arrows")
        arrows.count = 5
        self.w._stash(self.p, arrows)
        self.w.submit(self.p, {"a": "use", "slot": 0})
        self.assertLess(self.m.hp, self.m.max_hp)

    def test_its_lightning_hurts_unless_youre_warded(self):
        self.m.float_next = 10 ** 9
        self.w._monster_turn(self.m, self.lvl)
        self.assertLess(self.p.hp, self.p.max_hp)
        self.p.hp, self.m.ready_at = self.p.max_hp, 0
        self.p.reflect_until = 10 ** 9
        self.w._monster_turn(self.m, self.lvl)
        self.assertEqual(self.p.hp, self.p.max_hp)

    def test_it_drops_a_staff_that_never_runs_out(self):
        self.w._kill(self.m, self.p)
        staff = next(i for i in self.lvl.items.values() if i.kind == "lightning_staff")
        self.assertTrue(staff.unlimited)
        self.w._stash(self.p, staff)
        target = add(self.w, self.lvl, "ogre", self.x + 3, self.y, state="wandering")
        target.hp = target.max_hp = 10 ** 6
        for _ in range(15):
            self.p.next_time = self.w.clock
            self.w.submit(self.p, {"a": "use", "slot": 0})
        self.assertIn(staff, self.p.pack)
        self.assertLess(target.hp, 10 ** 6)

    def test_no_altar_takes_the_staff(self):
        from game.items import make_staff
        staff = make_staff()
        self.w._stash(self.p, staff)
        self.w.submit(self.p, {"a": "use", "slot": 0})  # nothing to aim at; it isn't wielded either
        self.assertIsNone(self.p.weapon)
        self.assertIn("no altar", staff.info)


class CultLeaderTests(unittest.TestCase):
    def setUp(self):
        self.w, self.lvl, self.p = empty_world()
        self.x, self.y = open_spot(self.lvl)
        put(self.lvl, self.p, self.x, self.y)
        self.p.hp = self.p.max_hp = 1000
        self.c = add(self.w, self.lvl, "cult_leader", self.x + 3, self.y, target=self.p)

    def turn(self):
        self.w.drain_outbox()
        cost = self.w._monster_turn(self.c, self.lvl)
        bolts = [m for _, m in self.w.drain_outbox() if m.get("t") == "fx" and m.get("kind") == "fire"]
        return cost, bolts

    def test_three_bolts_then_a_rest(self):
        from game.constants import LEADER_REST, LEADER_VOLLEY
        shots = 0
        for _ in range(LEADER_VOLLEY):
            _, bolts = self.turn()
            shots += len(bolts)
        self.assertEqual(shots, LEADER_VOLLEY)
        self.assertTrue(self.lvl.fire)  # the last one set the ground alight around you
        self.assertIn((self.p.x, self.p.y), self.lvl.fire)
        self.assertLess(self.p.hp, self.p.max_hp)
        self.assertEqual(self.c.ready_at, self.w.clock + int(LEADER_REST * TICKS_PER_SECOND))
        _, bolts = self.turn()
        self.assertEqual(bolts, [])  # resting
        self.w.clock = self.c.ready_at
        _, bolts = self.turn()
        self.assertEqual(len(bolts), 1)  # and the next volley begins

    def test_it_backs_off_when_you_close_in(self):
        self.lvl.move(self.c, self.x + 1, self.y)
        _, bolts = self.turn()
        self.assertEqual(bolts, [])
        self.assertGreater(cheb(self.c, self.p), 1)

    def test_a_ward_stops_the_bolts_and_the_fire(self):
        self.p.reflect_until = 10 ** 9
        for _ in range(3):
            self.turn()
        self.assertEqual(self.p.hp, self.p.max_hp)
        self.assertNotIn((self.p.x, self.p.y), self.lvl.fire)

    def test_tougher_than_before(self):
        self.assertGreaterEqual(MONSTERS["cult_leader"]["hp"], 75)
        self.assertGreaterEqual(MONSTERS["cult_mage"]["hp"], 65)


if __name__ == "__main__":
    unittest.main()
