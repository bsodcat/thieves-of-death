"""Run with:  python -m pytest -q   (or  python -m unittest discover tests)"""
import unittest

import numpy as np

from game import mapgen
from game.constants import MAP_H, MAP_W, MONSTER_SWING, MONSTER_TIME, REGEN_TURNS, TICKS_PER_TURN
from game.entities import make_monster
from game.tiles import DEEP, DOOR, FLOOR, STAIRS_DOWN, STAIRS_UP, WALKABLE
from game.world import World


def empty_world(seed=1):
    """A world whose depth-1 level has no monsters."""
    w = World(seed)
    lvl = w.level(1)
    for m in list(lvl.monsters):
        lvl.remove(m)
    lvl.monsters.clear()
    return w, lvl


def add_monster(w, lvl, kind, near, state="wandering", mid=900):
    m = make_monster(kind, mid)
    m.state = state
    lvl.place(m, *lvl.free_near(near.x, near.y))
    lvl.monsters.append(m)
    return m


def open_step(lvl, p):
    """A direction this player can walk in right now."""
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        n = (p.x + dx, p.y + dy)
        if lvl.walkable[n] and n not in lvl.occupant:
            return {"a": "move", "dx": dx, "dy": dy}
    raise AssertionError("boxed in")


class MapGenTests(unittest.TestCase):
    def test_levels_are_sound(self):
        for seed in range(25):
            for depth in (1, 2):
                g = mapgen.generate(seed, depth)
                walk = WALKABLE[g.tiles]
                self.assertGreaterEqual(mapgen._bfs(walk, g.up_front)[g.down_front], 0, (seed, depth))
                swim = mapgen._bfs(walk | (g.tiles == DEEP), g.up_front)
                self.assertTrue((swim[walk] >= 0).all(), (seed, depth))  # only water makes islands
                self.assertEqual(g.tiles[g.up], STAIRS_UP)
                self.assertEqual(g.tiles[g.down], STAIRS_DOWN)
                self.assertEqual(g.tiles[g.up_front], FLOOR)
                self.assertEqual(g.tiles[g.down_front], FLOOR)
                # no floor connected only diagonally
                for x in range(MAP_W - 1):
                    for y in range(MAP_H - 1):
                        a, b, c, d = walk[x, y], walk[x + 1, y], walk[x, y + 1], walk[x + 1, y + 1]
                        self.assertFalse(a and d and not b and not c)
                        self.assertFalse(b and c and not a and not d)
                # doors sit between two walls
                for x, y in np.argwhere(g.tiles == DOOR):
                    ew = walk[x - 1, y] and walk[x + 1, y] and not walk[x, y - 1] and not walk[x, y + 1]
                    ns = walk[x, y - 1] and walk[x, y + 1] and not walk[x - 1, y] and not walk[x + 1, y]
                    self.assertTrue(ew or ns)

    def test_floors_past_the_end_of_the_monster_lists(self):
        w = World(1)
        for depth in (26, 27, 28, 40, 99):
            lvl = w.level(depth)
            self.assertTrue(lvl.monsters)
            self.assertTrue(lvl.items)

    def test_deterministic(self):
        self.assertTrue(np.array_equal(mapgen.generate(7, 3).tiles, mapgen.generate(7, 3).tiles))


class RealTimeTests(unittest.TestCase):
    def setUp(self):
        self.w, self.lvl = empty_world()
        self.a, self.b = self.w.join("Alice"), self.w.join("Bob")

    def test_nobody_waits_for_a_teammate(self):
        self.assertEqual(max(abs(self.a.x - self.b.x), abs(self.a.y - self.b.y)), 1)
        for n in range(1, 6):
            self.w.submit(self.a, open_step(self.lvl, self.a))
            self.assertEqual(self.a.turns, n)  # ran at once, with Bob standing idle next to Alice
            self.w.advance(TICKS_PER_TURN)
        self.assertEqual(self.b.turns, 0)
        self.assertEqual(self.w.state_for(self.a)["status"][0], "go")

    def test_cooldown_queues_the_next_action(self):
        self.w.submit(self.a, open_step(self.lvl, self.a))
        self.w.submit(self.a, open_step(self.lvl, self.a))
        self.assertEqual(self.a.turns, 1)      # still cooling down: queued, not lost
        self.assertIsNotNone(self.a.pending)
        self.w.advance(TICKS_PER_TURN - 1)
        self.assertEqual(self.a.turns, 1)
        self.w.advance(1)
        self.assertEqual(self.a.turns, 2)
        self.assertIsNone(self.a.pending)

    def test_queued_action_is_replaced_by_the_latest(self):
        self.w.submit(self.a, open_step(self.lvl, self.a))
        self.w.submit(self.a, {"a": "move", "dx": 0, "dy": 1})
        step = {"a": "move", "dx": 1, "dy": 0}
        self.w.submit(self.a, step)
        self.assertEqual(self.a.pending, step)

    def test_walls_cost_no_time(self):
        lvl, a = self.lvl, self.a
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            if not lvl.walkable[a.x + dx, a.y + dy] and lvl.tiles[a.x + dx, a.y + dy] == 0:
                self.w.submit(a, {"a": "move", "dx": dx, "dy": dy})
                self.assertEqual(a.next_time, 0)
                return
        self.skipTest("no wall beside the start")

    def test_monsters_act_with_nobody_pressing_keys(self):
        rat = add_monster(self.w, self.lvl, "rat", self.a, "wandering")
        far = max(self.lvl.floor_cells, key=lambda c: abs(c[0] - self.a.x) + abs(c[1] - self.a.y))
        self.lvl.move(rat, *far)  # out of reach, so it wanders rather than bites
        start = (rat.x, rat.y)
        moved = False
        for _ in range(20):
            self.w.advance(TICKS_PER_TURN)
            moved = moved or (rat.x, rat.y) != start
        self.assertTrue(moved)
        self.assertEqual((self.a.turns, self.b.turns), (0, 0))

    def test_monsters_run_slower_than_players(self):
        rat = add_monster(self.w, self.lvl, "rat", self.a, "hunting")
        rat.target_id = self.a.id
        beside = next((self.a.x + dx, self.a.y + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                      if self.lvl.walkable[self.a.x + dx, self.a.y + dy]
                      and self.lvl.occupant.get((self.a.x + dx, self.a.y + dy)) in (None, rat))
        self.lvl.move(rat, *beside)  # straight beside her, so nothing stops it biting
        self.w.advance(rat.next_time)
        self.assertEqual(rat.next_time, self.w.clock + int(TICKS_PER_TURN * MONSTER_SWING * MONSTER_TIME))

    def test_hunter_attacks_an_idle_player(self):
        goblin = add_monster(self.w, self.lvl, "goblin", self.a, "hunting")
        goblin.accuracy = 10000
        self.w.advance(5 * TICKS_PER_TURN)
        self.assertLess(self.a.hp + self.b.hp, self.a.max_hp + self.b.max_hp)

    def test_empty_levels_stay_frozen(self):
        lvl2 = self.w.level(2)
        rat = make_monster("rat", 901)
        rat.state = "wandering"
        lvl2.place(rat, *lvl2.free_near(*lvl2.up_front))
        lvl2.monsters.append(rat)
        start = (rat.x, rat.y)
        for _ in range(20):
            self.w.advance(TICKS_PER_TURN)
        self.assertEqual((rat.x, rat.y), start)
        lvl2.place(self.a, *lvl2.free_near(*lvl2.down_front))  # someone arrives: it wakes
        self.lvl.occupant.pop((self.a.x, self.a.y), None)
        for _ in range(20):
            self.w.advance(TICKS_PER_TURN)
        self.assertNotEqual((rat.x, rat.y), start)

    def test_health_returns_over_time(self):
        self.w.regen = True  # only on Easy
        self.a.hp = 1
        self.w.advance(REGEN_TURNS * TICKS_PER_TURN // 4)
        self.assertGreater(self.a.hp, 1)
        self.assertLessEqual(self.a.hp, self.a.max_hp)


class CombatTests(unittest.TestCase):
    def test_kill_and_messages(self):
        w, lvl = empty_world()
        a = w.join("Alice")
        rat = make_monster("rat", 500)
        rat.hp = 1
        spot = next((a.x + dx, a.y) for dx in (1, -1) if lvl.walkable[a.x + dx, a.y]
                    and (a.x + dx, a.y) not in lvl.occupant)
        lvl.place(rat, *spot)
        lvl.monsters.append(rat)
        w.drain_outbox()
        w.submit(a, {"a": "move", "dx": spot[0] - a.x, "dy": 0})  # sleeping rat: sneak attack always hits
        self.assertNotIn(rat, lvl.monsters)
        texts = [m["text"] for _, m in w.drain_outbox() if m["t"] == "msg"]
        self.assertIn("You hit the rat by surprise!", texts)
        self.assertIn("You kill the rat.", texts)
        self.assertEqual(a.kills, 1)

    def test_party_wipe_resets_run(self):
        w, lvl = empty_world()
        a = w.join("Alice")
        w._kill(a, make_monster("ogre", 77))
        self.assertFalse(a.alive)
        self.assertIn("ogre", a.death)
        self.assertFalse(w.check_reset(w.reset_at - 0.1))
        self.assertTrue(w.check_reset(w.reset_at + 0.1))
        self.assertTrue(a.alive)
        self.assertEqual(w.run, 2)

    def test_stairs(self):
        w, lvl = empty_world()
        a = w.join("Alice")
        lvl.move(a, *lvl.down_front)
        dx, dy = lvl.down[0] - a.x, lvl.down[1] - a.y
        w.submit(a, {"a": "move", "dx": dx, "dy": dy})
        self.assertEqual(a.depth, 2)
        self.assertTrue(a.needs_level)


if __name__ == "__main__":
    unittest.main()
