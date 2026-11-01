"""The buried tower and its atrium, ponds of healing, the dragon, gas and living water."""
import unittest
from unittest import mock

import numpy as np

from game import mapgen
from game.constants import (ATRIUM_FLOOR, BREATH_DAMAGE, DRAGON_FLOOR, GAS_REACH, GAS_SECONDS, LAST_FLOOR,
                            REFLECT_SECONDS, TICKS_PER_SECOND, TOWER_FIRST)
from game.entities import make_monster
from game.items import ITEMS, make_item
from game.render import ClientView
from game.tiles import DEEP, DOOR, GLYPH, LAVA, POND, SHALLOW, STAIRS_DOWN, STAIRS_UP, TOWER_WALL, WALKABLE
from game.world import World, appears_on

TOWER = range(TOWER_FIRST, LAST_FLOOR + 1)


def view_of(w, p):
    v = ClientView()
    v.apply({"t": "welcome", "id": p.id, "name": p.name})
    v.apply(w.level_msg(p.depth))
    v.apply(w.pack_msg(p))
    v.apply(w.state_for(p))
    return v


def reachable(walk, start):
    return mapgen._bfs(walk, start) >= 0


def on_floor(depth, seed=1):
    w = World(seed)
    p = w.join("A")
    w.warp(p, depth)
    return w, w.levels[depth], p


class TowerTests(unittest.TestCase):
    def test_every_floor_is_a_mirror_image(self):
        for depth in TOWER:
            for seed in range(4):
                tiles = mapgen.generate(seed, depth).tiles
                self.assertTrue((tiles == tiles[::-1, :]).all(), (seed, depth))

    def test_the_walls_are_green_and_buried_in_rock(self):
        for depth in TOWER:
            tiles = mapgen.generate(1, depth).tiles
            self.assertGreater(int((tiles == TOWER_WALL).sum()), 300, depth)
            self.assertEqual(tiles[0, 0], 0)
            self.assertEqual(tiles[1, 1], 0)

    def test_several_rooms_joined_by_doors(self):
        for seed in range(5):
            self.assertGreaterEqual(int((mapgen.generate(seed, 95).tiles == DOOR).sum()), 6)

    def test_every_floor_differs(self):
        self.assertFalse((mapgen.generate(1, 92).tiles == mapgen.generate(1, 93).tiles).all())

    def test_everything_joins_up_and_the_stairs_work(self):
        for seed in range(30):
            for depth in range(TOWER_FIRST, LAST_FLOOR):
                g = mapgen.generate(seed, depth)
                walk = WALKABLE[g.tiles]
                self.assertTrue(reachable(walk, g.up_front)[walk].all(), (seed, depth))
                self.assertEqual(g.tiles[g.up], STAIRS_UP)
                self.assertEqual(g.tiles[g.down], STAIRS_DOWN)

    def test_doors_sit_between_walls(self):
        for seed in range(6):
            g = mapgen.generate(seed, 94)
            walk = WALKABLE[g.tiles]
            for x, y in np.argwhere(g.tiles == DOOR):
                self.assertTrue((walk[x - 1, y] and walk[x + 1, y] and not walk[x, y - 1] and not walk[x, y + 1])
                                or (walk[x, y - 1] and walk[x, y + 1] and not walk[x - 1, y] and not walk[x + 1, y]))

    def test_you_can_climb_the_whole_tower(self):
        w = World(2)
        p = w.join("A")
        w.warp(p, LAST_FLOOR)
        for depth in range(LAST_FLOOR, ATRIUM_FLOOR - 1, -1):
            lvl = w.levels[depth]
            lvl.move(p, *lvl.free_near(*lvl.up_front))
            lvl.remove(p)
            lvl.place(p, *lvl.up_front)
            w._take_stairs(p, -1)
            self.assertEqual(p.depth, depth - 1)

    def test_its_walls_stay_lit_in_memory_of_the_glow(self):
        w, lvl, p = on_floor(95)
        v = view_of(w, p)
        spot = next((x, y) for x, y in np.argwhere(lvl.tiles == TOWER_WALL) if v.visible[x, y])
        colors = set()
        for t in (0.0, 1.0, 2.0):
            with mock.patch("game.render.time.monotonic", return_value=t):
                frame = v.draw()
            colors.add(tuple(int(c) for c in frame["fg"][21 + spot[0], 3 + spot[1]]))
        self.assertGreater(len(colors), 1)
        r, g, b = colors.pop()
        self.assertGreater(g, r * 1.5)
        self.assertGreater(g, b * 1.2)


class LairTests(unittest.TestCase):
    def test_a_big_round_room_with_pillars_and_smaller_rooms(self):
        for seed in range(8):
            g = mapgen.generate(seed, LAST_FLOOR)
            x, y = g.lair
            self.assertTrue((g.tiles == g.tiles[::-1, :]).all())
            circle = mapgen._ellipse(x, y, 17, 10)
            self.assertGreater(int((WALKABLE[g.tiles] & circle).sum()), 400)
            self.assertGreaterEqual(int((g.tiles[circle] == TOWER_WALL).sum()), 8)   # the pillars
            self.assertGreaterEqual(int((g.tiles == DOOR).sum()), 4)                 # the side rooms

    def test_the_necromancer_is_alone(self):
        for seed in range(12):
            w, lvl, p = on_floor(LAST_FLOOR, seed)
            self.assertEqual([m.kind for m in lvl.monsters], ["necromancer"])

    def test_no_way_down(self):
        g = mapgen.generate(3, LAST_FLOOR)
        self.assertIsNone(g.down)
        self.assertFalse((g.tiles == STAIRS_DOWN).any())

    def test_the_necromancer_is_at_the_centre_and_all_of_it_joins_up(self):
        for seed in range(10):
            w, lvl, p = on_floor(LAST_FLOOR, seed)
            n = w.necromancer
            self.assertTrue(abs(n.x - lvl.lair[0]) <= 2 and abs(n.y - lvl.lair[1]) <= 2)
            walk = lvl.walkable
            self.assertTrue(reachable(walk, lvl.up_front)[walk].all())

    def test_the_amulet_is_across_the_room(self):
        for seed in range(25):
            w, lvl, p = on_floor(LAST_FLOOR, seed)
            n = w.necromancer
            spot = next(c for c, i in lvl.items.items() if i.category == "amulet")
            self.assertTrue(7 <= max(abs(spot[0] - n.x), abs(spot[1] - n.y)) <= 9, seed)
            self.assertLessEqual(lvl.distances_to(n.x, n.y)[spot] // 2, 13, seed)


class AtriumTests(unittest.TestCase):
    def test_no_monsters_at_all(self):
        for seed in range(12):
            w, lvl, p = on_floor(ATRIUM_FLOOR, seed)
            self.assertEqual(lvl.monsters, [])

    def test_a_hall_into_a_round_atrium_with_a_way_down(self):
        g = mapgen.generate(1, ATRIUM_FLOOR)
        walk = WALKABLE[g.tiles]
        self.assertTrue(reachable(walk, g.up_front)[g.down_front])
        self.assertTrue(walk[6:50, 14].all())                       # the long hall
        self.assertGreater(int(mapgen._ellipse(62, 14, 13, 10).sum()), 300)
        self.assertTrue((g.tiles == TOWER_WALL).any())

    def test_the_floors_either_side_are_normal(self):
        w, lvl, p = on_floor(ATRIUM_FLOOR - 1)
        self.assertTrue(lvl.monsters)


class PondTests(unittest.TestCase):
    def pond_floor(self):
        for seed in range(300):
            w = World(seed)
            lvl = w.level(3)
            cells = [(int(x), int(y)) for x, y in np.argwhere(lvl.tiles == POND)]
            if len(cells) >= 2 and lvl.mainland[cells[0]]:
                p = w.join("A")
                w.levels[p.depth].remove(p)
                for m in list(lvl.monsters):
                    lvl.remove(m)
                lvl.monsters.clear()
                lvl.place(p, *lvl.up_front)
                return w, lvl, p, cells
        raise AssertionError("no pond")

    def test_some_floors_have_one(self):
        found = sum((mapgen.generate(seed, 3).tiles == POND).any() for seed in range(200))
        self.assertTrue(8 < found < 60, found)

    def test_stepping_in_heals_wards_and_spends_it(self):
        w, lvl, p, cells = self.pond_floor()
        p.hp = 3
        lvl.move(p, *cells[0])
        w._step_onto(p, lvl)
        self.assertEqual(p.hp, p.max_hp)
        self.assertTrue(w._reflecting(p))
        self.assertEqual(lvl.tiles[cells[0]], SHALLOW)
        self.assertFalse(any(lvl.tiles[x + dx, y + dy] == POND for x, y in [cells[0]]
                             for dx in (-1, 0, 1) for dy in (-1, 0, 1)))

    def test_the_ward_wears_off(self):
        w, lvl, p, cells = self.pond_floor()
        lvl.move(p, *cells[0])
        w._step_onto(p, lvl)
        w.advance(int((REFLECT_SECONDS + 1) * TICKS_PER_SECOND))
        self.assertFalse(w._reflecting(p))

    def test_levitating_over_it_does_nothing(self):
        w, lvl, p, cells = self.pond_floor()
        p.levitate_until = w.clock + 10 ** 6
        p.hp = 3
        lvl.move(p, *cells[0])
        w._step_onto(p, lvl)
        self.assertEqual(p.hp, 3)

    def test_it_sparkles_and_the_map_updates(self):
        w, lvl, p, cells = self.pond_floor()
        v = view_of(w, p)
        w.drain_outbox()
        lvl.move(p, *cells[0])
        w._step_onto(p, lvl)
        for _, m in w.drain_outbox():
            v.apply(m)
        self.assertTrue(v.bolts)
        self.assertEqual(v.levels[3][cells[0]], SHALLOW)
        e = next(e for e in w.state_for(p)["ents"] if e["id"] == p.id)
        self.assertTrue(e["ward"])
        v.apply(w.state_for(p))
        self.assertIn("Reflecting magic", str(v._describe_actor(e)))
        stars = 0
        for t in range(8):
            with mock.patch("game.render.time.monotonic", return_value=t / 7):
                frame = v.draw()
            stars += int((frame["ch"] == ord("*")).sum())
        self.assertGreater(stars, 0)

    def test_it_is_bright_teal(self):
        from game.tiles import BG, FG
        r, g, b = BG[POND]
        self.assertTrue(g > 100 and b > 100 and r < 40)
        self.assertGreater(FG[POND][1], 200)


class MagicArmorTests(unittest.TestCase):
    def test_only_floors_60_to_70(self):
        t = ITEMS["magic"]
        self.assertEqual(t["depths"], (60, 70))
        self.assertTrue(all(appears_on(t, d) for d in range(60, 71)))
        self.assertFalse(appears_on(t, 59) or appears_on(t, 71) or appears_on(t, 95))

    def test_it_really_turns_up(self):
        found = any(i.kind == "magic" for seed in range(60) for i in World(seed).level(65).items.values())
        self.assertTrue(found)

    def test_wearing_it_wards_you_and_taking_it_off_doesnt(self):
        w = World(1)
        p = w.join("A")
        p.pack.append(make_item("magic"))
        w._use(p, 0)
        self.assertTrue(w._reflecting(p))
        w._use(p, 0)
        self.assertFalse(w._reflecting(p))

    def test_it_says_so(self):
        self.assertIn("warded", make_item("magic").info)


class DragonTests(unittest.TestCase):
    def setUp(self):
        self.w, self.lvl, self.p = on_floor(DRAGON_FLOOR)
        self.d = next(m for m in self.lvl.monsters if m.kind == "dragon")

    def in_line(self):
        for m in list(self.lvl.monsters):
            if m is not self.d:
                self.lvl.remove(m)
                self.lvl.monsters.remove(m)
        spot = next(c for c in self.lvl.land_cells if 3 <= max(abs(c[0] - self.d.x), abs(c[1] - self.d.y)) <= 6
                    and c not in self.lvl.occupant and algo_sees(self.lvl, c, self.d))
        self.lvl.move(self.p, *spot)
        self.d.state = "hunting"

    def test_only_on_floor_80(self):
        self.assertEqual(sum(m.kind == "dragon" for m in self.lvl.monsters), 1)
        for depth in (79, 81):
            self.assertFalse(any(m.kind == "dragon" for m in World(1).level(depth).monsters))

    def test_it_sleeps_far_from_the_stairs(self):
        self.assertEqual(self.d.state, "sleeping")
        self.assertGreater(self.lvl.distances_to(*self.lvl.up_front)[self.d.x, self.d.y], 60)

    def test_it_breathes_fire_along_a_line(self):
        self.in_line()
        hp = self.p.hp
        self.w.drain_outbox()
        self.w._monster_turn(self.d, self.lvl)
        self.assertLessEqual(hp - self.p.hp, BREATH_DAMAGE[1])
        self.assertGreaterEqual(hp - self.p.hp, BREATH_DAMAGE[0])
        text = str(self.w.drain_outbox())
        self.assertIn("breathes fire", text)
        self.assertIn("'kind': 'fire'", text)

    def test_it_has_to_recover(self):
        self.in_line()
        self.w._monster_turn(self.d, self.lvl)
        hp = self.p.hp
        self.w._monster_turn(self.d, self.lvl)
        self.assertEqual(self.p.hp, hp)

    def test_a_ward_sends_it_back(self):
        self.in_line()
        self.p.reflect_until = self.w.clock + 10 ** 6
        hp, dragon = self.p.hp, self.d.hp
        self.w.drain_outbox()
        self.w._monster_turn(self.d, self.lvl)
        self.assertEqual(self.p.hp, hp)
        self.assertLess(self.d.hp, dragon)
        self.assertIn("rebound", str(self.w.drain_outbox()))

    def test_magic_armor_does_the_same(self):
        self.in_line()
        self.p.armor = make_item("magic")
        hp, dragon = self.p.hp, self.d.hp
        self.w._monster_turn(self.d, self.lvl)
        self.assertEqual(self.p.hp, hp)
        self.assertLess(self.d.hp, dragon)

    def test_its_own_fire_can_finish_it(self):
        self.in_line()
        self.p.reflect_until = self.w.clock + 10 ** 6
        self.d.hp = 1
        self.w._monster_turn(self.d, self.lvl)
        self.assertNotIn(self.d, self.lvl.monsters)
        self.assertEqual(self.p.kills, 1)

    def test_fire_can_kill_you(self):
        self.in_line()
        self.p.hp = 1
        self.w._monster_turn(self.d, self.lvl)
        self.assertFalse(self.p.alive)
        self.assertIn("skeletal dragon", self.p.death)

    def test_god_mode_ignores_it(self):
        self.in_line()
        self.p.god = True
        self.w._monster_turn(self.d, self.lvl)
        self.assertEqual(self.p.hp, self.p.max_hp)


def algo_sees(lvl, cell, m):
    from game import algo
    return algo.compute_fov(lvl._base_transparent, m.x, m.y, 0)[cell]


class GasTests(unittest.TestCase):
    def room(self):
        w = World(3)
        lvl = w.level(1)
        for m in list(lvl.monsters):
            lvl.remove(m)
        lvl.monsters.clear()
        p = w.join("A")
        m = make_monster("mushroom", 900)
        m.state = "wandering"
        spot = max(lvl.land_cells[::5], key=lambda c: len(lvl.room_around(*c)))
        lvl.move(p, *lvl.free_near(spot[0] + 2, spot[1]))
        lvl.place(m, *spot)
        lvl.monsters.append(m)
        return w, lvl, p, m

    def test_it_spreads_as_far_as_it_may_and_no_further(self):
        w, lvl, p, m = self.room()
        w._monster_turn(m, lvl)
        far = max(max(abs(c[0] - m.x), abs(c[1] - m.y)) for c in lvl.gas)
        self.assertEqual(far, GAS_REACH)
        self.assertGreater(len(lvl.gas), 25)

    def test_never_further_anywhere(self):
        for seed in range(12):
            w = World(seed)
            lvl = w.level(4)
            for x, y in lvl.land_cells[::9]:
                room = lvl.room_around(x, y)
                self.assertLessEqual(max(max(abs(c[0] - x), abs(c[1] - y)) for c in room), GAS_REACH)
                self.assertLessEqual(len(room), (2 * GAS_REACH + 1) ** 2)

    def test_doors_and_walls_hold_it(self):
        w, lvl, p, m = self.room()
        w._monster_turn(m, lvl)
        self.assertTrue(all(lvl.hover[c] for c in lvl.gas))
        self.assertFalse(any(lvl.is_door[c] for c in lvl.gas if c != (m.x, m.y)))

    def test_the_edges_clear_first_and_then_its_gone(self):
        w, lvl, p, m = self.room()
        p.god = True
        w._monster_turn(m, lvl)
        m.ready_at = 10 ** 9
        counts = []
        for _ in range(int(GAS_SECONDS)):
            counts.append(len(lvl.gas))
            w.advance(int(TICKS_PER_SECOND))
        self.assertEqual(counts, sorted(counts, reverse=True))
        self.assertGreater(len(set(counts)), 3)
        self.assertLess(counts[len(counts) * 3 // 4], counts[0])
        w.advance(int(2 * TICKS_PER_SECOND))
        self.assertEqual(lvl.gas, {})

    def test_it_looks_thinner_as_it_goes(self):
        w, lvl, p, m = self.room()
        p.god = True
        w._monster_turn(m, lvl)
        m.ready_at = 10 ** 9
        fresh = w.state_for(p)["gas"]
        w.advance(int(5 * TICKS_PER_SECOND))
        later = w.state_for(p)["gas"]
        self.assertLess(max(g[2] for g in later), max(g[2] for g in fresh))


class RippleTests(unittest.TestCase):
    def frames(self, tile):
        for seed in range(100):
            w = World(seed)
            depth = 52 if tile == LAVA else 3
            p = w.join("A")
            w.warp(p, depth)
            lvl = w.levels[depth]
            v = view_of(w, p)
            v.visible[:] = True
            v.seen[depth][:] = True
            cells = np.argwhere(lvl.tiles == tile)
            if len(cells) > 8:
                x, y = cells[0]
                seen = set()
                for t in np.arange(0, 3, 0.2):
                    with mock.patch("game.render.time.monotonic", return_value=float(t)):
                        f = v.draw()
                    seen.add(int(f["ch"][21 + x, 3 + y]))
                return seen, f, cells
        raise AssertionError("none")

    def test_water_ripples_with_similar_glyphs(self):
        seen, _, _ = self.frames(DEEP)
        self.assertGreater(len(seen), 1)
        self.assertLessEqual(seen, {0x2248, ord("~")})

    def test_lava_ripples_too(self):
        seen, _, _ = self.frames(LAVA)
        self.assertGreater(len(seen), 1)

    def test_neighbors_are_out_of_step(self):
        _, f, cells = self.frames(DEEP)
        glyphs = {int(f["ch"][21 + x, 3 + y]) for x, y in cells[:40]}
        self.assertGreater(len(glyphs), 1)

    def test_all_the_glyphs_are_in_the_font(self):
        import tcod.tileset
        from game.render import RIPPLES
        for _, glyphs, _ in RIPPLES:
            for code in glyphs:
                self.assertIn(code, tcod.tileset.CHARMAP_CP437)
        for code in GLYPH.tolist() + [0x2592]:
            self.assertIn(code, tcod.tileset.CHARMAP_CP437)

    def test_drawing_stays_quick(self):
        import time
        w, lvl, p = on_floor(52, 2)
        v = view_of(w, p)
        v.seen[52][:] = True
        v.visible[:] = True
        start = time.perf_counter()
        for _ in range(30):
            v.draw()
        self.assertLess((time.perf_counter() - start) / 30, 0.05)


if __name__ == "__main__":
    unittest.main()
