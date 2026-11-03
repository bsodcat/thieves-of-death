"""Cloaks, critical hits on sleepers, and the shortcuts that keep the game quick."""
import unittest
from unittest import mock

from game import algo, pathing
from game.constants import (CLOAK_FLOORS, CRIT_DAMAGE, CRIT_STEALTH, NOTICE_RANGE_AWAKE, SCREEN_H, SNEAK_DAMAGE,
                            STEALTH_MAX)
from game.entities import make_monster
from game.items import make_cloak, make_item
from game.render import HELP_TIPS, ClientView
from game.world import World


def cloaks_on(w, depths=range(1, 60)):
    return [(d, c, i) for d in depths for c, i in w.level(d).items.items() if i.category == "cloak"]


def bare_world():
    w = World(3)
    lvl = w.level(1)
    for m in list(lvl.monsters):
        lvl.remove(m)
    lvl.monsters.clear()
    lvl.items.clear()
    return w, lvl, w.join("A")


class SpawnTests(unittest.TestCase):
    def test_one_per_player(self):
        for players in (1, 2, 5):
            w = World(players)
            for i in range(players):
                w.join(f"P{i}")
            self.assertEqual(len(cloaks_on(w, range(1, CLOAK_FLOORS + 1))), players)

    def test_floors_vary_with_the_run(self):
        floors = set()
        for seed in range(30):
            w = World(seed)
            w.join("A")
            floors |= {d for d, _, _ in cloaks_on(w, range(1, CLOAK_FLOORS + 1))}
        self.assertEqual(floors, set(range(1, CLOAK_FLOORS + 1)))

    def test_a_late_arrival_adds_one_near_the_party(self):
        w = World(5)
        a = w.join("A")
        w.level(9)
        w.levels[a.depth].remove(a)
        w.levels[9].place(a, *w.levels[9].free_near(*w.levels[9].up_front))
        before = len(cloaks_on(w, range(1, 14)))
        w.join("B")
        found = cloaks_on(w, range(1, 14))
        self.assertEqual(len(found), before + 1)
        self.assertTrue(any(9 <= d < 9 + CLOAK_FLOORS for d, _, _ in found))

    def test_rejoining_doesnt_add_another(self):
        w = World(5)
        a = w.join("A")
        w.leave(a)
        w.join("A")
        self.assertEqual(len(cloaks_on(w, range(1, CLOAK_FLOORS + 1))), 1)

    def test_a_new_run_has_one_per_player(self):
        w = World(6)
        for name in "ABC":
            w.join(name)
        w.reset_run()
        self.assertEqual(len(cloaks_on(w, range(1, CLOAK_FLOORS + 1))), 3)

    def test_never_on_a_merchant_or_in_a_shop(self):
        for seed in range(40):
            w = World(seed)
            lvl = w.level(5)
            if lvl.merchant:
                self.assertFalse(any(i.category == "cloak" for i in lvl.merchant.stock.values()))

    def test_only_ever_placed_on_reachable_floor(self):
        for seed in range(10):
            w = World(seed)
            w.join("A")
            for d, spot, _ in cloaks_on(w, range(1, CLOAK_FLOORS + 1)):
                self.assertIn(spot, w.levels[d].floor_cells)

    def test_it_waits_for_g(self):
        w, lvl, p = bare_world()
        lvl.items[(p.x, p.y)] = make_cloak()
        w._step_onto(p, lvl)
        self.assertEqual(p.pack, [])


class WearingTests(unittest.TestCase):
    def wear(self, *extra):
        w, lvl, p = bare_world()
        p.pack.extend([make_cloak(), *extra])
        for slot in range(len(p.pack)):
            w.submit(p, {"a": "use", "slot": slot})
            w.advance(200)
        return w, lvl, p

    def test_narrows_detection(self):
        w, lvl, p = bare_world()
        w.level(1).light[:] = 0
        plain = w._notice_range(p, NOTICE_RANGE_AWAKE)
        p.pack.append(make_cloak())
        w.submit(p, {"a": "use", "slot": 0})
        w.advance(200)
        p.stealth = 0
        self.assertIs(p.cloak, p.pack[0])
        self.assertAlmostEqual(w._notice_range(p, NOTICE_RANGE_AWAKE), plain * 0.5)

    def test_takes_noise_off_your_gear(self):
        w, lvl, p = self.wear(make_item("mace"), make_item("plate"))
        self.assertEqual(p.stealth_cap, 85)

    def test_the_cap_never_passes_full(self):
        w, lvl, p = self.wear()
        self.assertEqual(p.stealth_cap, STEALTH_MAX)

    def test_worn_with_weapon_and_armor(self):
        w, lvl, p = self.wear(make_item("sword"), make_item("leather"))
        self.assertTrue(p.cloak and p.weapon and p.armor)
        self.assertEqual(sum(i["eq"] for i in w.pack_msg(p)["pack"]), 3)

    def test_taking_it_off_ends_the_bonus(self):
        w, lvl, p = self.wear(make_item("mace"))
        self.assertEqual(p.stealth_cap, 100)
        w.submit(p, {"a": "use", "slot": 0})
        w.advance(200)
        self.assertIsNone(p.cloak)
        self.assertEqual(p.stealth_cap, 80)

    def test_dropping_it_ends_the_bonus(self):
        w, lvl, p = self.wear()
        w.submit(p, {"a": "drop", "slot": 0})
        w.advance(200)
        self.assertIsNone(p.cloak)
        self.assertEqual(p.pack, [])

    def test_a_classic_death_leaves_it_behind(self):
        w, lvl, p = self.wear()
        w.revive_seconds = None  # the fallen stay down, as on Hard
        w._kill(p, None)
        self.assertIsNone(p.cloak)
        self.assertTrue(any(i.category == "cloak" for i in lvl.items.values()))

    def test_a_new_run_takes_it_off(self):
        w, lvl, p = self.wear()
        w.reset_run()
        self.assertIsNone(p.cloak)

    def test_shown_in_the_pack(self):
        self.assertEqual(make_cloak().info, "detection -50%, noise -45")
        self.assertEqual(make_cloak().glyph, "¶")


class CriticalTests(unittest.TestCase):
    def setUp(self):
        self.w, self.lvl, self.p = bare_world()
        self.p.damage = (10, 10)
        self.m = make_monster("ogre", 999)
        self.m.hp = self.m.max_hp = 100000
        self.m.next_time = 10 ** 9
        self.spot = next((self.p.x + dx, self.p.y) for dx in (1, -1) if self.lvl.walkable[self.p.x + dx, self.p.y])
        self.lvl.place(self.m, *self.spot)
        self.lvl.monsters.append(self.m)

    def hit(self, state, stealth):
        self.m.hp, self.m.state, self.p.stealth = self.m.max_hp, state, stealth
        self.w.drain_outbox()
        self.w._attack(self.p, self.m)
        return self.m.max_hp - self.m.hp, str(self.w.drain_outbox())

    def test_sleeping_and_stealthy_is_critical(self):
        damage, text = self.hit("sleeping", CRIT_STEALTH)
        self.assertEqual(damage, 10 * CRIT_DAMAGE)
        self.assertIn("critical hit", text)

    def test_too_little_stealth_is_only_a_sneak_attack(self):
        damage, text = self.hit("sleeping", CRIT_STEALTH - 1)
        self.assertEqual(damage, 10 * SNEAK_DAMAGE)
        self.assertIn("by surprise", text)

    def test_awake_monsters_arent_critical(self):
        damage, _ = self.hit("wandering", STEALTH_MAX)
        self.assertEqual(damage, 10 * SNEAK_DAMAGE)

    def test_stealth_still_empties(self):
        self.hit("sleeping", STEALTH_MAX)
        self.assertEqual(self.p.stealth, 0)

    def test_monsters_cant_crit_players(self):
        self.p.hp = self.p.max_hp = 100000
        self.p.defense = 0
        self.w._attack(self.m, self.p)
        self.assertGreater(self.p.hp, 100000 - self.m.damage[1] - 1)


class QuickerTests(unittest.TestCase):
    def test_monsters_share_route_maps(self):
        w = World(4)
        lvl = w.level(1)
        with mock.patch.object(algo, "dijkstra", wraps=algo.dijkstra) as dijkstra:
            for _ in range(5):
                lvl.distances_to(*lvl.up_front)
        self.assertEqual(dijkstra.call_count, 1)

    def test_kept_maps_are_limited(self):
        w = World(4)
        lvl = w.level(1)
        for c in lvl.floor_cells[:300]:
            lvl.distances_to(*c)
        self.assertLessEqual(len(lvl._paths), 256)

    def test_the_same_auto_walk_isnt_worked_out_twice(self):
        w = World(4)
        p = w.join("A")
        v = ClientView()
        v.apply({"t": "welcome", "id": p.id, "name": p.name})
        v.apply(w.level_msg(1))
        v.apply(w.state_for(p))
        goal = next(c for c in w.levels[1].floor_cells if c != (p.x, p.y) and v.seen[1][c])
        with mock.patch.object(pathing, "next_step", wraps=pathing.next_step) as route:
            first = v.walk_step(*goal)
            self.assertEqual(v.walk_step(*goal), first)
        self.assertEqual(route.call_count, 1)

    def test_rejoining_doesnt_keep_sprinting(self):
        w = World(4)
        p = w.join("A")
        w.submit(p, {"a": "sprint", "on": True})
        w.leave(p)
        self.assertFalse(w.join("A").sprinting)


class TipTests(unittest.TestCase):
    def test_new_tips_fit(self):
        for tip in HELP_TIPS:
            self.assertLessEqual(len(tip), 64, tip)

    def test_a_cloak_is_drawn(self):
        v = ClientView()
        v.pack = [dict(name="cloak", g="(", c=[1, 2, 3], info=make_cloak().info, eq=True)]
        v.show_pack = True
        text = "\n".join("".join(chr(c) for c in v.draw()["ch"][:, y]) for y in range(SCREEN_H))
        self.assertIn("detection -50%, noise -45 (on)", text)


if __name__ == "__main__":
    unittest.main()
