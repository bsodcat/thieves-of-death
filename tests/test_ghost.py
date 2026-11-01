"""Ghosts, which follow an altar's use, and enhanced weapons against the undead."""
import unittest

import numpy as np

from game import commands
from game.constants import CRIT_DAMAGE, GHOST_DISTANCE, GHOST_FLOORS, MAP_H, MAP_W, SNEAK_DAMAGE, UNDEAD_BONUS
from game.entities import MONSTERS, UNDEAD, make_monster
from game.items import make_item
from game.tiles import ALTAR, STAIRS_DOWN, STAIRS_UP, WALL
from game.world import World


def at_altar():
    """A player beside an altar, with a sword, and nothing else on the floor."""
    w = World(1)
    p = w.join("A")
    p.can_command = True
    commands.run(w, p, "goto 4")
    lvl = w.levels[4]
    for m in list(lvl.monsters):
        lvl.remove(m)
    lvl.monsters.clear()
    commands.run(w, p, "spawn cult")
    x, y = (int(v) for v in np.argwhere(lvl.tiles == ALTAR)[0])
    for m in list(lvl.monsters):
        lvl.remove(m)
    lvl.monsters.clear()
    lvl.move(p, x - 1, y)
    p.pack.append(make_item("sword"))
    w._use(p, 0)
    w.drain_outbox()
    return w, lvl, p, (x, y)


def enhance(w, p, altar):
    w.advance(300)
    w.submit(p, {"a": "enhance", "x": altar[0], "y": altar[1]})


def ghosts(lvl):
    return [m for m in lvl.monsters if m.kind == "ghost"]


class SpawningTests(unittest.TestCase):
    def test_nothing_until_you_use_an_altar(self):
        w, lvl, p, altar = at_altar()
        w.warp(p, 9)
        w.advance(100)
        self.assertEqual(ghosts(w.levels[9]), [])
        self.assertEqual(p.haunts, [])

    def test_not_right_away(self):
        w, lvl, p, altar = at_altar()
        enhance(w, p, altar)
        self.assertEqual(p.haunts, [4])
        w.advance(100)
        self.assertEqual(ghosts(lvl), [])

    def test_not_one_floor_away(self):
        w, lvl, p, altar = at_altar()
        enhance(w, p, altar)
        w.warp(p, 5)
        w.advance(100)
        self.assertEqual(ghosts(w.levels[5]), [])

    def test_it_comes_a_couple_of_floors_away(self):
        for depth in (4 + GHOST_FLOORS, 4 - GHOST_FLOORS):
            w, lvl, p, altar = at_altar()
            enhance(w, p, altar)
            w.drain_outbox()
            w.warp(p, depth)
            w.advance(10)
            self.assertEqual(len(ghosts(w.levels[depth])), 1, depth)
            self.assertIn("A chill runs through you", str(w.drain_outbox()))

    def test_only_one_for_each_altar(self):
        w, lvl, p, altar = at_altar()
        enhance(w, p, altar)
        w.warp(p, 8)
        for _ in range(30):
            w.advance(50)
        self.assertEqual(len(ghosts(w.levels[8])), 1)
        self.assertEqual(p.haunts, [])

    def test_two_altars_mean_two_ghosts(self):
        w, lvl, p, altar = at_altar()
        p.haunts = [4, 4]
        w.warp(p, 8)
        w.advance(10)
        self.assertEqual(len(ghosts(w.levels[8])), 2)

    def test_it_only_comes_for_who_used_the_altar(self):
        w, lvl, p, altar = at_altar()
        q = w.join("B")
        enhance(w, p, altar)
        self.assertEqual(q.haunts, [])

    def test_it_appears_out_of_sight_at_a_distance(self):
        for seed in range(6):
            w = World(seed)
            p = w.join("A")
            w._raise_ghost(p, w.levels[1])
            g = ghosts(w.levels[1])[0]
            self.assertFalse(w.fov(p)[g.x, g.y])
            self.assertTrue(GHOST_DISTANCE[0] <= max(abs(g.x - p.x), abs(g.y - p.y)) <= GHOST_DISTANCE[1])

    def test_it_never_turns_up_by_chance(self):
        self.assertFalse(any(m.kind == "ghost" for seed in range(10) for d in (5, 40, 95)
                             for m in World(seed).level(d).monsters))

    def test_a_new_run_clears_the_debt(self):
        w, lvl, p, altar = at_altar()
        enhance(w, p, altar)
        w.reset_run()
        self.assertEqual(p.haunts, [])

    def test_dead_players_arent_haunted_until_theyre_back(self):
        w, lvl, p, altar = at_altar()
        p.haunts = [40]
        w.join("B")
        w._kill(p, None)
        w.advance(10)
        self.assertEqual(ghosts(w.levels[p.depth]), [])


class GhostMovementTests(unittest.TestCase):
    def setUp(self):
        self.w = World(3)
        self.lvl = self.w.level(1)
        for m in list(self.lvl.monsters):
            self.lvl.remove(m)
        self.lvl.monsters.clear()
        self.p = self.w.join("A")
        self.g = make_monster("ghost", 900)
        self.g.state, self.g.next_time = "hunting", 10 ** 9
        self.lvl.monsters.append(self.g)

    def put(self, x, y):
        self.lvl.place(self.g, x, y)

    def test_it_passes_through_walls(self):
        wall = next((x, y) for x in range(2, MAP_W - 2) for y in range(2, MAP_H - 2)
                    if self.lvl.tiles[x, y] == WALL and self.lvl.tiles[x + (self.p.x > x) * 2 - 1, y] == WALL
                    and abs(x - self.p.x) > 3)
        self.put(*wall)
        crossed = []
        for _ in range(40):
            self.w._monster_turn(self.g, self.lvl)
            crossed.append(self.lvl.tiles[self.g.x, self.g.y])
            if max(abs(self.g.x - self.p.x), abs(self.g.y - self.p.y)) <= 1:
                break
        self.assertLessEqual(max(abs(self.g.x - self.p.x), abs(self.g.y - self.p.y)), 1)
        self.assertIn(WALL, crossed)

    def test_it_comes_straight_for_you_from_anywhere(self):
        self.put(max(1, self.p.x - 12), max(1, self.p.y - 6))
        walked = 0
        while max(abs(self.g.x - self.p.x), abs(self.g.y - self.p.y)) > 1 and walked < 20:
            self.w._monster_turn(self.g, self.lvl)
            walked += 1
        self.assertLessEqual(walked, 12)

    def test_it_attacks_when_it_arrives(self):
        self.p.hp = self.p.max_hp = 100000
        self.p.defense = 0
        self.put(self.p.x + 1, self.p.y)
        for _ in range(30):
            self.w._monster_turn(self.g, self.lvl)
        self.assertLess(self.p.hp, self.p.max_hp)

    def test_it_stays_on_the_map_and_off_the_stairs(self):
        self.put(self.lvl.up_front[0], self.lvl.up_front[1] - 0)
        self.lvl.move(self.p, *self.lvl.free_near(*self.lvl.up_front))
        for _ in range(60):
            self.w._monster_turn(self.g, self.lvl)
            self.assertTrue(0 < self.g.x < MAP_W - 1 and 0 < self.g.y < MAP_H - 1)
            self.assertNotIn(self.lvl.tiles[self.g.x, self.g.y], (STAIRS_DOWN, STAIRS_UP))

    def test_it_can_be_hit_inside_a_wall(self):
        wall = next(((x + 1, y) for x, y in self.lvl.land_cells if self.lvl.tiles[x + 1, y] == WALL))
        self.lvl.move(self.p, wall[0] - 1, wall[1])
        self.put(*wall)
        hp = self.g.hp = self.g.max_hp = 100000
        self.p.accuracy = 100000
        self.w.advance(300)
        self.w.submit(self.p, {"a": "move", "dx": 1, "dy": 0})
        self.assertLess(self.g.hp, hp)

    def test_it_can_be_frozen(self):
        self.put(self.p.x + 3, self.p.y)
        self.g.frozen_until = self.w.clock + 10 ** 6
        self.g.next_time = 0
        spot = (self.g.x, self.g.y)
        self.w._monster_act(self.g)
        self.assertEqual((self.g.x, self.g.y), spot)

    def test_nothing_happens_with_nobody_there(self):
        self.put(5, 5)
        self.lvl.remove(self.p)
        self.w.levels[1].monsters = [self.g]
        self.w.warp(self.p, 2)
        self.assertTrue(self.w._haunt(self.g, self.lvl))


class UndeadBonusTests(unittest.TestCase):
    def setUp(self):
        self.w = World(3)
        self.p = self.w.join("A")
        self.sword = make_item("sword")
        self.sword.damage = (10, 10)
        self.p.pack.append(self.sword)
        self.w._use(self.p, 0)

    def hit(self, kind, state="hunting", stealth=0):
        m = make_monster(kind, 900)
        m.hp = m.max_hp = 100000
        m.defense, m.state = 0, state
        self.p.accuracy = 100000
        self.p.stealth = stealth
        self.w._attack(self.p, m)
        return m.max_hp - m.hp

    def test_a_plain_weapon_gets_no_bonus(self):
        self.assertEqual(self.hit("zombie"), 10)

    def test_an_enhanced_one_does(self):
        self.sword.enhanced = 1
        self.assertEqual(self.hit("zombie"), int(10 * UNDEAD_BONUS))

    def test_every_undead_kind_counts(self):
        self.sword.enhanced = 1
        for kind in UNDEAD:
            self.assertIn(kind, MONSTERS)
            self.assertEqual(self.hit(kind), 15, kind)

    def test_the_living_dont(self):
        self.sword.enhanced = 1
        for kind in ("rat", "ogre", "wolf", "cultist", "slime"):
            self.assertEqual(self.hit(kind), 10, kind)

    def test_it_stacks_with_sneak_attacks_and_crits(self):
        self.sword.enhanced = 1
        self.assertEqual(self.hit("zombie", "wandering"), int(10 * SNEAK_DAMAGE * UNDEAD_BONUS))
        self.assertEqual(self.hit("zombie", "sleeping", 100), int(10 * CRIT_DAMAGE * UNDEAD_BONUS))

    def test_it_says_so(self):
        self.assertNotIn("bane of undead", self.sword.info)
        self.sword.enhanced = 1
        self.assertIn("bane of undead", self.sword.info)

    def test_a_real_altar_gives_it(self):
        w, lvl, p, altar = at_altar()
        enhance(w, p, altar)
        self.assertEqual(p.weapon.enhanced, 1)
        self.assertIn("bane of undead", p.weapon.info)


if __name__ == "__main__":
    unittest.main()
