"""Torches and their light, stamina and sprinting, and the tips in the help."""
import unittest
from unittest import mock

import numpy as np

from game import mapgen
from game.constants import (ATTACK_STAMINA, MAP_H, MAP_W, NOTICE_RANGE_AWAKE, SCREEN_H, SPRINT_STAMINA,
                            STAMINA_MAX, TICKS_PER_SECOND, TICKS_PER_TURN, TORCH_COUNT, TORCH_NOTICE, TORCH_RADIUS,
                            TORCH_SPACING)
from game.entities import make_monster
from game.render import HELP_LINES, HELP_TIPS, ClientView
from game.tiles import FLOOR, TORCH, WALL
from game.world import Level, World


def rows_of(frame):
    return "\n".join("".join(chr(c) for c in frame["ch"][:, y]) for y in range(SCREEN_H))


def cheb(a, b):
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def torch_world(seed=2):
    """A world with its first floor swapped for one that certainly has a torch."""
    w = World(seed)
    for s in range(100):
        gen = mapgen.generate(s, 1)
        if gen.torches:
            w.levels[1] = Level(1, gen)
            return w, w.levels[1], gen.torches[0]
    raise AssertionError("no torches")


def clear_floor(w, lvl):
    for m in lvl.monsters:
        lvl.remove(m)
    lvl.monsters.clear()
    lvl.items.clear()


class TorchTests(unittest.TestCase):
    def test_torches_are_sparse_and_in_walls_beside_floor(self):
        for seed in range(60):
            g = mapgen.generate(seed, 1 + seed % 20)
            self.assertLessEqual(len(g.torches), TORCH_COUNT[1])
            self.assertEqual(len(g.torches), int((g.tiles == TORCH).sum()))
            for i, (torch, front) in enumerate(g.torches):
                self.assertEqual(g.tiles[torch], TORCH)
                self.assertEqual(g.tiles[front], FLOOR)
                self.assertEqual(cheb(torch, front), 1)
                self.assertGreater(cheb(torch, g.up), TORCH_RADIUS)
                self.assertGreater(cheb(torch, g.down), TORCH_RADIUS)
                for other, _ in g.torches[:i]:
                    self.assertGreater(cheb(torch, other), TORCH_SPACING)

    def test_most_floors_have_one(self):
        lit = sum(bool(mapgen.generate(seed, 3).torches) for seed in range(40))
        self.assertGreater(lit, 30)

    def test_light_fades_with_distance_and_stops_at_walls(self):
        w, lvl, (torch, front) = torch_world()
        self.assertGreater(lvl.light[front], 0.8)
        self.assertEqual(lvl.light[torch], 1.0)
        xs, ys = np.indices((MAP_W, MAP_H))
        glow = lvl.torch_light[0]
        self.assertFalse((glow[np.hypot(xs - torch[0], ys - torch[1]) >= TORCH_RADIUS] > 0).any())
        reach = glow > 0
        reach[torch] = False
        self.assertFalse((reach & ~lvl._base_transparent & ~_next_to(lvl._base_transparent & reach)).any())

    def test_torches_block_like_walls(self):
        w, lvl, (torch, front) = torch_world()
        self.assertFalse(lvl.walkable[torch])
        self.assertFalse(lvl.hover[torch])
        self.assertFalse(lvl._base_transparent[torch])

    def test_torchlight_makes_you_easier_to_notice(self):
        w, lvl, (torch, front) = torch_world()
        p = w.join("A")
        dark = next(c for c in lvl.floor_cells if lvl.light[c] == 0)
        lvl.move(p, *dark)
        unlit = w._notice_range(p, NOTICE_RANGE_AWAKE)
        self.assertEqual(unlit, NOTICE_RANGE_AWAKE)
        self.assertFalse(w.state_for(p)["lit"])
        lvl.move(p, *front)
        lit = w._notice_range(p, NOTICE_RANGE_AWAKE)
        self.assertAlmostEqual(lit, NOTICE_RANGE_AWAKE * (1 + TORCH_NOTICE * lvl.light[front]))
        self.assertGreater(lit, unlit * 1.5)
        state = w.state_for(p)
        self.assertTrue(state["lit"])
        self.assertEqual(state["detect"], round(lit))

    def test_stealth_still_helps_in_the_light(self):
        w, lvl, (torch, front) = torch_world()
        p = w.join("A")
        lvl.move(p, *front)
        loud = w._notice_range(p, NOTICE_RANGE_AWAKE)
        p.stealth = 100
        self.assertLess(w._notice_range(p, NOTICE_RANGE_AWAKE), loud)


def _next_to(mask):
    p = np.pad(mask, 1)
    out = np.zeros_like(mask)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            out |= p[1 + dx:1 + dx + MAP_W, 1 + dy:1 + dy + MAP_H]
    return out


class ClientLightTests(unittest.TestCase):
    def view(self):
        w, lvl, (torch, front) = torch_world()
        p = w.join("A")
        clear_floor(w, lvl)
        lvl.move(p, *front)
        v = ClientView()
        v.apply({"t": "welcome", "id": p.id, "name": p.name})
        v.apply(w.level_msg(1))
        v.apply(w.pack_msg(p))
        v.apply(w.state_for(p))
        return v, w, lvl, front

    def test_the_maps_arrive_intact(self):
        v, w, lvl, front = self.view()
        self.assertEqual(len(v.lights[1]), len(lvl.torch_light))
        self.assertAlmostEqual(float(v.lights[1][0][front]), float(lvl.torch_light[0][front]), places=2)

    def test_light_flickers(self):
        v, w, lvl, front = self.view()
        colors = set()
        for t in (0.0, 0.31, 0.77, 1.3):
            with mock.patch("game.render.time.monotonic", return_value=t):
                frame = v.draw()
            colors.add(tuple(int(c) for c in frame["bg"][21 + front[0], 3 + front[1]]))
        self.assertGreater(len(colors), 1)

    def test_lit_tiles_are_warmer_than_unlit_ones(self):
        v, w, lvl, front = self.view()
        lit = v.draw()["bg"][21 + front[0], 3 + front[1]].copy()
        with mock.patch.object(ClientView, "_torchlight", lambda self: None):
            dark = v.draw()["bg"][21 + front[0], 3 + front[1]]
        self.assertGreater(int(lit[0]), int(dark[0]))

    def test_light_is_only_drawn_where_you_can_see(self):
        v, w, lvl, front = self.view()
        v.visible[:] = False
        v.seen[1][:] = True
        lit = v.draw()["bg"][21 + front[0], 3 + front[1]].copy()
        with mock.patch.object(ClientView, "_torchlight", lambda self: None):
            dark = v.draw()["bg"][21 + front[0], 3 + front[1]]
        self.assertTrue((lit == dark).all())

    def test_a_new_run_forgets_the_light(self):
        v, w, lvl, front = self.view()
        v.apply({"t": "level", "depth": 2, "run": 99, "w": MAP_W, "h": MAP_H,
                 "tiles": w.level_msg(1)["tiles"], "lights": []})
        self.assertEqual(list(v.lights), [2])

    def test_sidebar_says_when_youre_lit(self):
        v, w, lvl, front = self.view()
        self.assertIn("Torchlit:", rows_of(v.draw()))
        v.lit = False
        self.assertIn("Detection", rows_of(v.draw()))


class StaminaTests(unittest.TestCase):
    def setUp(self):
        self.w, self.lvl, _ = torch_world()
        self.p = self.w.join("A")
        clear_floor(self.w, self.lvl)
        self.x, self.y = next(c for c in self.lvl.floor_cells if all(
            self.lvl.walkable[c[0] + i, c[1]] for i in range(8)))
        self.lvl.move(self.p, self.x, self.y)

    def move(self):
        self.w.advance(max(0, self.p.next_time - self.w.clock))
        self.w.submit(self.p, {"a": "move", "dx": 1, "dy": 0})
        return self.p.next_time - self.w.clock

    def sprint(self, on=True):
        self.w.submit(self.p, {"a": "sprint", "on": on})

    def test_starts_full(self):
        self.assertEqual(self.p.stamina, STAMINA_MAX)
        self.assertEqual(self.w.state_for(self.p)["stamina"], STAMINA_MAX)

    def test_walking_costs_nothing(self):
        self.assertEqual(self.move(), TICKS_PER_TURN)
        self.assertEqual(self.p.stamina, STAMINA_MAX)

    def test_sprinting_is_faster_and_costs_stamina(self):
        self.sprint()
        self.assertEqual(self.move(), 60)
        self.assertEqual(self.p.stamina, STAMINA_MAX - SPRINT_STAMINA)

    def test_sprinting_drains_stealth_faster(self):
        self.p.stealth = 100
        self.move()
        walked = self.p.stealth
        self.p.stealth = 100
        self.sprint()
        self.move()
        self.assertLess(self.p.stealth, walked)

    def test_out_of_stamina_you_walk(self):
        self.sprint()
        self.p.stamina = SPRINT_STAMINA - 1
        self.assertEqual(self.move(), TICKS_PER_TURN)

    def test_letting_go_of_shift_stops_it(self):
        self.sprint()
        self.sprint(False)
        self.assertEqual(self.move(), TICKS_PER_TURN)

    def test_bumping_a_wall_is_free(self):
        self.sprint()
        wall = next(c for c in self.lvl.floor_cells if not self.lvl.walkable[c[0] + 1, c[1]]
                    and self.lvl.tiles[c[0] + 1, c[1]] == WALL)
        self.lvl.move(self.p, *wall)
        self.move()
        self.assertEqual(self.p.stamina, STAMINA_MAX)

    def monster(self):
        m = make_monster("ogre", 999)
        m.hp = m.max_hp = 100000
        m.state, m.next_time = "sleeping", 10 ** 9
        self.lvl.place(m, self.p.x + 1, self.p.y)
        self.lvl.monsters.append(m)
        return m

    def test_attacks_cost_stamina(self):
        self.monster()
        self.assertEqual(self.move(), TICKS_PER_TURN)
        self.assertEqual(self.p.stamina, STAMINA_MAX - ATTACK_STAMINA)

    def test_tired_attacks_are_slow_but_still_land(self):
        self.monster()
        self.p.stamina = ATTACK_STAMINA - 1
        self.assertEqual(self.move(), 2 * TICKS_PER_TURN)
        self.assertEqual(self.p.stamina, 0)

    def test_it_refills_after_a_rest(self):
        self.p.stamina = 0
        self.w._spend_stamina(self.p, 0)
        self.w.advance(int(0.5 * TICKS_PER_SECOND))
        self.assertEqual(self.p.stamina, 0)
        self.w.advance(int(7 * TICKS_PER_SECOND))
        self.assertEqual(self.p.stamina, STAMINA_MAX)

    def test_shift_is_remembered_while_down(self):
        self.p.alive = False
        self.sprint()
        self.assertTrue(self.p.sprinting)

    def test_a_new_run_refills_it(self):
        self.p.stamina = 1
        self.w.reset_run()
        self.assertEqual(self.p.stamina, STAMINA_MAX)

    def test_the_bar_is_in_the_sidebar(self):
        v = ClientView()
        v.apply({"t": "welcome", "id": self.p.id, "name": self.p.name})
        v.apply(self.w.level_msg(1))
        self.p.stamina = 42
        v.apply(self.w.state_for(self.p))
        self.assertIn("Stamina 42%", rows_of(v.draw()))
        self.p.stamina = 3
        v.apply(self.w.state_for(self.p))
        self.assertIn("Stamina 3% Tired", rows_of(v.draw()))


class TipTests(unittest.TestCase):
    def test_every_tip_fits_the_panel(self):
        for tip in HELP_TIPS:
            self.assertLessEqual(len(tip), 64, tip)

    def test_no_tip_is_listed_twice(self):
        self.assertEqual(len(set(HELP_TIPS)), len(HELP_TIPS))

    def test_it_changes_every_time_the_help_opens(self):
        v = ClientView()
        last = v.tip
        for _ in range(200):
            v.toggle_help()
            self.assertTrue(v.show_help)
            self.assertNotEqual(v.tip, last)
            last = v.tip
            v.toggle_help()
            self.assertFalse(v.show_help)
            self.assertEqual(v.tip, last)

    def test_all_of_them_come_up_before_any_repeats(self):
        v = ClientView()
        shown = set()
        for _ in range(len(HELP_TIPS) - 1):
            v.toggle_help()
            v.toggle_help()
            shown.add(v.tip)
        self.assertEqual(len(shown), len(HELP_TIPS) - 1)

    def test_the_tip_is_drawn(self):
        v = ClientView()
        for _ in range(len(HELP_TIPS)):
            v.toggle_help()
            self.assertIn(v.tip, rows_of(v.draw()))
            v.toggle_help()

    def test_opening_it_closes_other_panels(self):
        v = ClientView()
        v.show_pack = v.show_tally = v.drop_mode = True
        v.toggle_help()
        self.assertFalse(v.show_pack or v.show_tally or v.drop_mode)

    def test_it_still_fits_half_the_map(self):
        self.assertLessEqual(len(HELP_LINES) + 2, 14)
        self.assertIn("Hold Shift", " ".join(k for k, _ in HELP_LINES))


class LookTests(unittest.TestCase):
    def test_the_new_tile_has_a_description(self):
        v = ClientView()
        tiles = np.zeros((MAP_W, MAP_H), np.uint8)
        tiles[3, 3] = TORCH
        v.levels[1], v.depth = tiles, 1
        v.seen[1] = np.ones((MAP_W, MAP_H), bool)
        v.visible = np.ones((MAP_W, MAP_H), bool)
        self.assertEqual(v.describe(3, 3)[0][0], "Torch")


if __name__ == "__main__":
    unittest.main()
