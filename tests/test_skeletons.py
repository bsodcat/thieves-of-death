"""Where ogres live, skeleton archers and warriors, slimes and toxin."""
import unittest
from collections import Counter

from game.constants import (ARCHER_RANGE, SLIME_COUNT, SLIME_FLOORS, SLOW_FACTOR, SLOW_SECONDS, TICKS_PER_SECOND,
                            TICKS_PER_TURN, TOXIN_DAMAGE, TOXIN_SECONDS)
from game.entities import MONSTERS, make_monster
from game.render import ClientView
from game.world import World, appears_on


def kinds_on(depth, seeds=25):
    return Counter(m.kind for seed in range(seeds) for m in World(seed).level(depth).monsters)


def cheb(a, b):
    return max(abs(a.x - b.x), abs(a.y - b.y))


def alone(kind="skeleton_archer", gap=7, seed=3, depth=1):
    """A player and one hunting monster that can see each other, `gap` tiles apart."""
    for s in range(seed, seed + 60):
        w = World(s)
        p = w.join("A")
        w.warp(p, depth)
        lvl = w.levels[depth]
        for m in list(lvl.monsters):
            lvl.remove(m)
        lvl.monsters.clear()
        sight = w.fov(p)
        spots = [c for c in lvl.land_cells if sight[c] and c not in lvl.occupant
                 and max(abs(c[0] - p.x), abs(c[1] - p.y)) == gap]
        if spots:
            m = make_monster(kind, 900)
            m.state, m.next_time = "hunting", 10 ** 9
            lvl.place(m, *spots[0])
            lvl.monsters.append(m)
            return w, lvl, p, m
    raise AssertionError("no spot")


class OgreTests(unittest.TestCase):
    def test_never_past_65(self):
        self.assertTrue(appears_on(MONSTERS["ogre"], 65))
        self.assertFalse(appears_on(MONSTERS["ogre"], 66))
        for depth in (66, 75):
            self.assertNotIn("ogre", kinds_on(depth, 12))

    def test_most_common_at_45_to_55(self):
        self.assertGreater(kinds_on(50)["ogre"], kinds_on(62)["ogre"] * 1.2)

    def test_they_keep_their_old_floors(self):
        self.assertIn("ogre", kinds_on(10, 12))


class SkeletonSpawnTests(unittest.TestCase):
    def test_archers_on_floors_70_to_90(self):
        self.assertIn("skeleton_archer", kinds_on(70, 15))
        self.assertIn("skeleton_archer", kinds_on(90, 15))
        self.assertNotIn("skeleton_archer", kinds_on(69, 12))
        self.assertNotIn("skeleton_archer", kinds_on(91, 12))

    def test_warriors_lead_floors_80_to_98(self):
        for depth in (80, 85, 92, 98):
            found = kinds_on(depth, 15)
            self.assertEqual(found.most_common(1)[0][0], "skeleton_warrior", depth)
        self.assertNotIn("skeleton_warrior", kinds_on(79, 12))

    def test_they_dont_reach_the_lair(self):
        self.assertEqual(set(kinds_on(99, 5)), {"necromancer"})

    def test_every_floor_still_has_something(self):
        for depth in (27, 45, 66, 69, 72, 86, 88):
            self.assertTrue(kinds_on(depth, 4), depth)


class ArcherTests(unittest.TestCase):
    def test_it_shoots_from_range(self):
        w, lvl, p, m = alone()
        hits = 0
        p.hp = p.max_hp = 100000
        p.defense = 0
        w.drain_outbox()
        for _ in range(12):
            m.ready_at = 0
            before = p.hp
            w._monster_turn(m, lvl)
            hits += p.hp < before
        self.assertGreater(hits, 3)
        self.assertEqual(cheb(m, p), 7)
        self.assertIn("'kind': 'bow'", str(w.drain_outbox()))

    def test_it_has_to_reload(self):
        w, lvl, p, m = alone()
        p.hp = p.max_hp = 100000
        p.defense = 0
        w._monster_turn(m, lvl)
        ready = m.ready_at
        self.assertGreater(ready, w.clock)
        w._monster_turn(m, lvl)
        self.assertEqual(m.ready_at, ready)

    def test_it_backs_away_when_you_get_close(self):
        w, lvl, p, m = alone(gap=2)
        before = lvl.distances_to(p.x, p.y)[m.x, m.y]
        w._monster_turn(m, lvl)
        self.assertGreater(lvl.distances_to(p.x, p.y)[m.x, m.y], before)
        self.assertEqual(m.ready_at, 0)

    def test_it_closes_in_when_you_are_far(self):
        for gap in (11, 12, 10):
            try:
                w, lvl, p, m = alone(gap=gap)
            except AssertionError:
                continue
            before = lvl.distances_to(p.x, p.y)[m.x, m.y]
            w._monster_turn(m, lvl)
            self.assertLess(lvl.distances_to(p.x, p.y)[m.x, m.y], before)
            return
        self.skipTest("no long enough view")

    def test_cornered_it_shoots_anyway(self):
        w, lvl, p, m = alone(gap=1)
        lvl.walkable = lvl.walkable.copy()
        lvl.walkable[:] = False
        lvl.walkable[m.x, m.y] = True
        lvl.walkable[p.x, p.y] = True
        lvl._paths.clear()
        w._monster_turn(m, lvl)
        self.assertGreater(m.ready_at, 0)

    def test_it_settles_inside_its_range(self):
        w, lvl, p, m = alone(gap=2)
        p.hp = p.max_hp = 100000
        for _ in range(12):
            w._monster_turn(m, lvl)
        self.assertLessEqual(cheb(m, p), ARCHER_RANGE[1])

    def test_an_arrow_can_kill(self):
        w, lvl, p, m = alone()
        p.hp, p.defense = 1, 0
        for _ in range(40):
            m.ready_at = 0
            if p.alive:
                w._monster_turn(m, lvl)
        self.assertFalse(p.alive)
        self.assertIn("skeleton archer", p.death)

    def test_god_mode_ignores_arrows(self):
        w, lvl, p, m = alone()
        p.god = True
        p.defense = 0
        for _ in range(20):
            m.ready_at = 0
            w._monster_turn(m, lvl)
        self.assertEqual(p.hp, p.max_hp)

    def test_it_doesnt_blink_like_a_melee_monster(self):
        w, lvl, p, m = alone(gap=1)
        e = next(e for e in w.state_for(p)["ents"] if e["id"] == m.id)
        self.assertNotIn("strike", e)

    def test_warriors_fight_normally(self):
        w, lvl, p, m = alone("skeleton_warrior", gap=1)
        e = next(e for e in w.state_for(p)["ents"] if e["id"] == m.id)
        self.assertIn("strike", e)


class SlimeSpawnTests(unittest.TestCase):
    def test_4_or_5_on_every_floor_in_range(self):
        for seed in range(8):
            w = World(seed)
            for depth in (SLIME_FLOORS[0], 50, SLIME_FLOORS[1]):
                count = sum(m.kind == "slime" for m in w.level(depth).monsters)
                self.assertTrue(SLIME_COUNT[0] <= count <= SLIME_COUNT[1], (seed, depth, count))

    def test_not_outside_it(self):
        for depth in (SLIME_FLOORS[0] - 1, SLIME_FLOORS[1] + 1):
            self.assertNotIn("slime", kinds_on(depth, 8))

    def test_slow_moving_and_weak(self):
        m = make_monster("slime", 1)
        self.assertGreater(m.move_cost, TICKS_PER_TURN)
        self.assertLessEqual(m.damage[1], 2)


class SlimeTests(unittest.TestCase):
    def setUp(self):
        self.w, self.lvl, self.p, self.m = alone("slime", gap=1)
        self.p.defense = 0

    def run_for(self, seconds):
        """The clock in the small steps the server really takes."""
        for _ in range(int(seconds * 30)):
            self.w.advance(int(TICKS_PER_SECOND / 30))

    def on_trail(self):
        self.lvl.slime[(self.p.x, self.p.y)] = self.w.clock + 10 ** 6
        self.w._step_onto(self.p, self.lvl)

    def test_its_touch_poisons_and_slows(self):
        self.p.hp = self.p.max_hp = 1000
        self.m.state = "hunting"
        for _ in range(30):
            self.w._attack(self.m, self.p)
        self.assertGreater(self.p.toxin_until, self.w.clock)
        self.assertGreater(self.p.slow_until, self.w.clock)

    def test_it_never_hits_for_more_than_2(self):
        self.p.hp = self.p.max_hp = 1000
        for _ in range(100):
            before = self.p.hp
            self.w._attack(self.m, self.p)
            self.assertLessEqual(before - self.p.hp, 2)

    def test_it_leaves_a_trail_as_it_moves(self):
        lvl, m = self.lvl, self.m
        spot = (m.x, m.y)
        goal = next(c for c in lvl.land_cells if c != spot and c not in lvl.occupant
                    and 3 <= max(abs(c[0] - m.x), abs(c[1] - m.y)) <= 6)
        self.assertTrue(self.w._step_toward(m, lvl, *goal))
        self.assertIn(spot, lvl.slime)

    def test_the_trail_fades(self):
        self.lvl.slime[(5, 5)] = self.w.clock + 100
        self.w.advance(200)
        self.assertEqual(self.lvl.slime, {})

    def test_walking_on_it_poisons_and_slows(self):
        self.on_trail()
        self.assertGreater(self.p.toxin_until, self.w.clock)
        self.assertGreater(self.p.slow_until, self.w.clock)
        self.assertIn("Slime clings", str(self.w.drain_outbox()))

    def test_slowed_steps_take_longer(self):
        for tile in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (self.p.x + tile[0], self.p.y + tile[1])
            if self.lvl.walkable[n] and n not in self.lvl.occupant:
                break
        self.assertEqual(self.w._stride(self.p), self.p.move_cost)
        self.on_trail()
        self.assertEqual(self.w._stride(self.p), self.p.move_cost * SLOW_FACTOR)
        self.w.advance(int((SLOW_SECONDS + 0.5) * TICKS_PER_SECOND))
        self.assertEqual(self.w._stride(self.p), self.p.move_cost)

    def test_sprinting_still_helps_a_little(self):
        self.on_trail()
        self.p.sprinting = True
        self.assertEqual(self.w._stride(self.p), int(self.p.move_cost * SLOW_FACTOR * 0.6))

    def test_toxin_hurts_over_time_then_ends(self):
        self.lvl.remove(self.m)
        self.lvl.monsters.clear()
        self.on_trail()
        self.p.hp = self.p.max_hp = 100
        self.run_for(TOXIN_SECONDS - 0.5)
        lost = 100 - self.p.hp
        self.assertGreaterEqual(lost, (TOXIN_SECONDS - 1) * TOXIN_DAMAGE)
        self.assertLessEqual(lost, TOXIN_SECONDS * TOXIN_DAMAGE)
        self.run_for(1)
        self.assertFalse(self.w.state_for(self.p)["toxin"])

    def test_poison_stops_healing(self):
        self.lvl.remove(self.m)
        self.lvl.monsters.clear()
        self.p.hp, self.p.max_hp = 50, 100
        self.run_for(2)
        healed = self.p.hp
        self.assertGreater(healed, 50)
        self.on_trail()
        self.run_for(2)
        self.assertLess(self.p.hp, healed)

    def test_it_can_kill(self):
        self.lvl.remove(self.m)
        self.lvl.monsters.clear()
        self.on_trail()
        self.p.hp = 1
        self.run_for(2)
        self.assertFalse(self.p.alive)
        self.assertIn("slime", self.p.death)

    def test_levitating_or_god_mode_avoid_it(self):
        self.p.levitate_until = self.w.clock + 10 ** 6
        self.on_trail()
        self.assertEqual(self.p.toxin_until, 0)
        self.p.levitate_until = 0
        self.p.god = True
        self.on_trail()
        self.assertEqual(self.p.toxin_until, 0)

    def test_the_client_shows_all_of_it(self):
        self.lvl.remove(self.m)
        self.lvl.monsters.clear()
        self.on_trail()
        v = ClientView()
        v.apply({"t": "welcome", "id": self.p.id, "name": self.p.name})
        v.apply(self.w.level_msg(1))
        v.apply(self.w.state_for(self.p))
        self.assertTrue(v.slowed and v.toxin)
        self.assertIn([self.p.x, self.p.y], [list(c) for c in v.slime])
        frame = v.draw()
        text = "".join(chr(c) for c in frame["ch"][:20, 4])
        self.assertIn("Slowed", text)
        r, g, b = (int(c) for c in frame["bg"][10, 1])
        self.assertGreater(g, r)

    def test_a_new_run_clears_it(self):
        self.on_trail()
        self.w.reset_run()
        self.assertEqual((self.p.toxin_until, self.p.slow_until), (0, 0))


if __name__ == "__main__":
    unittest.main()
