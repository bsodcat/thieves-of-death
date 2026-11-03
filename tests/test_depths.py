"""Lava, the walking potions, cultists and the wand of fire."""
import unittest

import numpy as np

from game import mapgen
from game.constants import (CULT_FIRST, CULT_SIZE, FALL_DAMAGE, LAVA_DAMAGE, LAVA_FIRST, MAP_H, MAP_W, SCREEN_H,
                            TICKS_PER_SECOND, WAND_BURN_TURNS, WAND_CHARGES, WAND_DAMAGE, WAND_RANGE)
from game.entities import make_monster
from game.items import ITEMS, make_item, make_wand
from game.render import ClientView
from game.tiles import BG, DEEP, DESCRIPTIONS, FG, GLYPH, HOVER, LAVA, NAMES, TRANSPARENT, WALKABLE
from game.world import World, appears_on, line_between

DIRS4 = ((1, 0), (-1, 0), (0, 1), (0, -1))


def reachable(walk, start):
    seen, stack = {start}, [start]
    while stack:
        x, y = stack.pop()
        for dx, dy in DIRS4:
            n = (x + dx, y + dy)
            if 0 <= n[0] < MAP_W and 0 <= n[1] < MAP_H and walk[n] and n not in seen:
                seen.add(n)
                stack.append(n)
    return seen


def rows_of(frame):
    return "\n".join("".join(chr(c) for c in frame["ch"][:, y]) for y in range(SCREEN_H))


def clear(lvl):
    for m in list(lvl.monsters):
        lvl.remove(m)
    lvl.monsters.clear()
    if lvl.merchant:
        lvl.remove(lvl.merchant)
        lvl.merchant = None
    lvl.items.clear()


def put(w, depth, name="A"):
    """A player alone on a floor."""
    p = w.join(name)
    w.levels[p.depth].remove(p)
    lvl = w.level(depth)
    clear(lvl)
    lvl.place(p, *lvl.free_near(*lvl.up_front))
    return p, lvl


def lava_floor(depth=LAVA_FIRST):
    for seed in range(200):
        w = World(seed)
        lvl = w.level(depth)
        if lvl.lava_cells:
            return w, lvl
    raise AssertionError("no lava")


def beside_lava(lvl):
    for x, y in lvl.lava_cells:
        for dx, dy in DIRS4:
            if lvl.walkable[x + dx, y + dy]:
                return (x + dx, y + dy), (-dx, -dy)
    raise AssertionError("no shore")


def step(w, p, dx, dy):
    w.advance(200)
    w.submit(p, {"a": "move", "dx": dx, "dy": dy})
    w.advance(1)


class LavaTests(unittest.TestCase):
    def test_tile_tables_line_up(self):
        for table in (DESCRIPTIONS, WALKABLE, HOVER, TRANSPARENT, GLYPH, FG, BG):
            self.assertEqual(len(table), len(NAMES))

    def test_only_after_floor_50(self):
        for seed in range(25):
            for depth in (1, 30, LAVA_FIRST - 1):
                self.assertFalse((mapgen.generate(seed, depth).tiles == LAVA).any(), (seed, depth))

    def test_most_deep_floors_have_it(self):
        lit = sum((mapgen.generate(seed, LAVA_FIRST).tiles == LAVA).any() for seed in range(30))
        self.assertGreater(lit, 18)

    def test_stairs_stay_reachable_and_lava_never_cuts_anything_off(self):
        for seed in range(60):
            g = mapgen.generate(seed, LAVA_FIRST + seed % 30)
            walk = WALKABLE[g.tiles]
            self.assertIn(g.down_front, reachable(walk, g.up_front))
            self.assertEqual(int(walk.sum()), len(reachable(walk | (g.tiles == DEEP), g.up_front) & set(
                (int(x), int(y)) for x, y in np.argwhere(walk))))

    def test_walking_in_is_refused_for_free(self):
        w, lvl = lava_floor()
        p = w.join("A")
        w.levels[p.depth].remove(p)
        spot, (dx, dy) = beside_lava(lvl)
        clear(lvl)
        lvl.place(p, *spot)
        step(w, p, dx, dy)
        self.assertEqual((p.x, p.y), spot)
        self.assertEqual(p.hp, p.max_hp)
        self.assertIn("burn you alive", str(w.drain_outbox()))

    def test_monsters_stay_out(self):
        w, lvl = lava_floor()
        self.assertFalse(any(lvl.tiles[m.x, m.y] == LAVA for m in lvl.monsters))
        self.assertFalse(any(lvl.tiles[c] == LAVA for c in lvl.items))

    def fall_into_lava(self, hp, **effects):
        w, lower = lava_floor(LAVA_FIRST)
        w.levels.pop(LAVA_FIRST)
        lvl = w.level(LAVA_FIRST - 1)
        p = w.join("A")
        w.levels[p.depth].remove(p)
        lvl.place(p, *lvl.up_front)
        lower = w.level(LAVA_FIRST)
        clear(lower)
        p.hp = hp
        for name, value in effects.items():
            setattr(p, name, value)
        w._fall(p, lvl, lower.lava_cells[0])
        return w, lower, p

    def test_a_pit_above_can_drop_you_in_without_warning(self):
        w, lower, p = self.fall_into_lava(40)
        self.assertEqual(p.depth, LAVA_FIRST)
        self.assertTrue(p.alive)
        self.assertLessEqual(p.hp, 40 - LAVA_DAMAGE - FALL_DAMAGE[0])
        self.assertTrue(lower.walkable[p.x, p.y])
        self.assertIn("in lava", str(w.drain_outbox()))

    def test_it_can_kill(self):
        w, lower, p = self.fall_into_lava(20)
        self.assertFalse(p.alive)
        self.assertIn("lava", p.death)

    def test_bones_end_up_on_the_ground(self):
        w, lower, p = self.fall_into_lava(1)
        self.assertTrue(lower.walkable[p.x, p.y])

    def test_lava_walkers_land_safely(self):
        w, lower, p = self.fall_into_lava(40, lavawalk_until=10 ** 9)
        self.assertGreaterEqual(p.hp, 40 - FALL_DAMAGE[1])
        self.assertEqual(lower.tiles[p.x, p.y], LAVA)

    def test_falls_on_safe_ground_stay_safe(self):
        w, lower = lava_floor()
        spot, _ = beside_lava(lower)
        self.assertTrue(lower.walkable[lower.landing(*spot)])


class PotionTests(unittest.TestCase):
    def test_they_appear_in_and_around_20_to_40(self):
        for kind in ("waterwalking", "lavawalking"):
            t = ITEMS[kind]
            self.assertTrue(all(appears_on(t, d) for d in range(20, 41)))
            self.assertFalse(appears_on(t, 10))
            self.assertFalse(appears_on(t, 50))

    def test_they_really_turn_up(self):
        seen = set()
        for seed in range(40):
            w = World(seed)
            for depth in (20, 30, 40):
                seen |= {i.kind for i in w.level(depth).items.values()}
        self.assertLessEqual({"waterwalking", "lavawalking"}, seen)

    def test_the_old_lists_still_cover_deep_floors(self):
        self.assertTrue(appears_on(ITEMS["healing"], 90))
        self.assertFalse(appears_on(ITEMS["dagger"], 90))

    def drink(self, w, p, kind):
        p.pack.append(make_item(kind))
        w.submit(p, {"a": "use", "slot": len(p.pack) - 1})
        w.advance(1)

    def water_world(self):
        for seed in range(100):
            w = World(seed)
            p, lvl = put(w, 2)
            cells = [(int(x), int(y)) for x, y in np.argwhere(lvl.tiles == DEEP)]
            for x, y in cells:
                for dx, dy in DIRS4:
                    if lvl.walkable[x + dx, y + dy]:
                        lvl.move(p, x + dx, y + dy)
                        return w, lvl, p, (-dx, -dy)
        raise AssertionError("no water")

    def test_water_walking(self):
        w, lvl, p, (dx, dy) = self.water_world()
        spot = (p.x, p.y)
        step(w, p, dx, dy)
        self.assertEqual((p.x, p.y), spot)
        self.drink(w, p, "waterwalking")
        self.assertTrue(w.state_for(p)["waterwalk"])
        step(w, p, dx, dy)
        self.assertEqual(lvl.tiles[p.x, p.y], DEEP)

    def test_it_ending_on_the_water_puts_you_ashore(self):
        w, lvl, p, (dx, dy) = self.water_world()
        self.drink(w, p, "waterwalking")
        step(w, p, dx, dy)
        w.advance(int(61 * TICKS_PER_SECOND))
        self.assertTrue(lvl.walkable[p.x, p.y])
        self.assertTrue(p.alive)

    def test_lava_walking_crosses_lava_but_ending_there_burns(self):
        w, lvl = lava_floor()
        p = w.join("A")
        w.levels[p.depth].remove(p)
        spot, (dx, dy) = beside_lava(lvl)
        clear(lvl)
        lvl.place(p, *spot)
        self.drink(w, p, "lavawalking")
        step(w, p, dx, dy)
        self.assertEqual(lvl.tiles[p.x, p.y], LAVA)
        self.assertEqual(p.hp, p.max_hp)
        w.advance(int(61 * TICKS_PER_SECOND))
        self.assertLess(p.hp, p.max_hp)
        self.assertTrue(lvl.walkable[p.x, p.y])

    def test_water_walking_doesnt_help_on_lava(self):
        w, lvl = lava_floor()
        p = w.join("A")
        w.levels[p.depth].remove(p)
        spot, (dx, dy) = beside_lava(lvl)
        clear(lvl)
        lvl.place(p, *spot)
        self.drink(w, p, "waterwalking")
        step(w, p, dx, dy)
        self.assertEqual((p.x, p.y), spot)

    def test_shown_in_the_sidebar(self):
        w, lvl, p, _ = self.water_world()
        self.drink(w, p, "waterwalking")
        v = ClientView()
        v.apply({"t": "welcome", "id": p.id, "name": p.name})
        v.apply(w.level_msg(2))
        v.apply(w.state_for(p))
        self.assertIn("Players Water", rows_of(v.draw()))

    def test_a_new_run_clears_them(self):
        w, lvl, p, _ = self.water_world()
        self.drink(w, p, "waterwalking")
        w.reset_run()
        self.assertEqual(p.waterwalk_until, 0)


def cult_world():
    for seed in range(300):
        w = World(seed)
        for depth in range(CULT_FIRST, CULT_FIRST + 30):
            lvl = w.level(depth)
            cult = [m for m in lvl.monsters if m.kind in ("cultist", "cult_leader")]
            if cult:
                return w, lvl, cult
    raise AssertionError("no cult")


class CultTests(unittest.TestCase):
    def test_groups_are_6_to_12_with_one_leader(self):
        sizes = set()
        for seed in range(15):
            w = World(seed)
            for depth in range(CULT_FIRST, CULT_FIRST + 20):
                cult = [m for m in w.level(depth).monsters if m.kind in ("cultist", "cult_leader")]
                if cult:
                    sizes.add(len(cult))
                    self.assertTrue(CULT_SIZE[0] <= len(cult) <= CULT_SIZE[1], len(cult))
                    self.assertEqual(sum(m.kind == "cult_leader" for m in cult), 1)
        self.assertGreater(len(sizes), 2)

    def test_not_before_their_first_floor(self):
        for seed in range(25):
            w = World(seed)
            for depth in range(1, CULT_FIRST - 1):  # a cult's mage can wait the floor before its first
                self.assertFalse(any(m.kind.startswith("cult") for m in w.level(depth).monsters))
            self.assertFalse(any(m.kind in ("cultist", "cult_leader") for m in w.level(CULT_FIRST - 1).monsters))

    def test_they_never_turn_up_alone(self):
        for seed in range(10):
            w = World(seed)
            lvl = w.level(CULT_FIRST)
            cult = [m for m in lvl.monsters if m.kind in ("cultist", "cult_leader")]  # a mage lives apart
            self.assertIn(len(cult), (0, *range(CULT_SIZE[0], CULT_SIZE[1] + 1)))

    def test_they_start_close_together(self):
        w, lvl, cult = cult_world()
        leader = next(m for m in cult if m.kind == "cult_leader")
        self.assertLess(max(max(abs(m.x - leader.x), abs(m.y - leader.y)) for m in cult), 12)

    def test_one_notices_and_they_all_do(self):
        w, lvl, cult = cult_world()
        for m in cult:
            m.state = "sleeping"
        p = w.join("A")
        w.levels[p.depth].remove(p)
        lvl.place(p, *lvl.free_near(*lvl.up_front))
        w._hunt(cult[-1], p)
        self.assertTrue(all(m.state == "hunting" for m in cult))

    def test_followers_stay_with_their_leader(self):
        w, lvl, cult = cult_world()
        p = w.join("A")
        w.levels[p.depth].remove(p)
        lvl.place(p, *lvl.free_near(*lvl.up_front))
        for m in cult:
            m.state = "wandering"
        p.stealth = 100
        w.advance(int(10 * TICKS_PER_SECOND))
        leader = next(m for m in cult if m.kind == "cult_leader")
        far = max(max(abs(m.x - leader.x), abs(m.y - leader.y)) for m in cult)
        self.assertLess(far, 25)

    def test_the_leader_drops_a_wand(self):
        w, lvl, cult = cult_world()
        p = w.join("A")
        leader = next(m for m in cult if m.kind == "cult_leader")
        w._kill(leader, p)
        wands = [i for i in lvl.items.values() if i.category == "wand"]
        self.assertEqual(len(wands), 1)
        self.assertEqual(wands[0].charges, WAND_CHARGES)
        self.assertTrue(lvl.walkable[next(c for c, i in lvl.items.items() if i is wands[0])])

    def test_ordinary_cultists_dont(self):
        w, lvl, cult = cult_world()
        p = w.join("A")
        before = len(lvl.items)
        w._kill(next(m for m in cult if m.kind == "cultist"), p)
        self.assertEqual(len(lvl.items), before)


class WandTests(unittest.TestCase):
    def setUp(self):
        self.w = World(3)
        self.p, self.lvl = put(self.w, 1)
        self.p.pack.append(make_wand())
        self.wand = self.p.pack[0]
        self.lvl.light[:] = 0

    def monster(self, gap=1, hp=100000):
        vis = self.w.fov(self.p)
        spot = next(c for c in self.lvl.floor_cells if vis[c] and c not in self.lvl.occupant
                    and max(abs(c[0] - self.p.x), abs(c[1] - self.p.y)) == gap)
        m = make_monster("ogre", 900 + gap)
        m.hp = m.max_hp = hp
        m.state, m.next_time = "sleeping", 10 ** 9
        self.lvl.place(m, *spot)
        self.lvl.monsters.append(m)
        return m

    def zap(self):
        self.w.advance(200)
        self.w.submit(self.p, {"a": "use", "slot": 0})
        self.w.advance(1)

    def test_it_waits_for_g(self):
        self.lvl.items[(self.p.x, self.p.y)] = make_wand()
        self.w._step_onto(self.p, self.lvl)
        self.assertEqual(len(self.p.pack), 1)

    def test_burns_the_nearest_monster_and_uses_a_charge(self):
        far, near = self.monster(3), self.monster(1)
        self.zap()
        self.assertEqual(self.wand.charges, WAND_CHARGES - 1)
        self.assertLess(near.hp, near.max_hp)
        self.assertEqual(far.hp, far.max_hp)
        self.assertGreaterEqual(near.max_hp - near.hp, WAND_DAMAGE[0])
        self.assertEqual(near.state, "hunting")

    def test_sets_it_alight(self):
        m = self.monster()
        self.zap()
        self.assertEqual(m.burning, WAND_BURN_TURNS)
        hp = m.hp
        m.next_time = self.w.clock
        self.w.advance(1000)
        self.assertLess(hp - m.hp, 100)
        self.assertLess(m.burning, WAND_BURN_TURNS)
        self.assertTrue(self.w.state_for(self.p))

    def test_burning_to_death_counts_as_your_kill(self):
        m = self.monster()
        self.zap()
        m.hp = 1
        m.next_time = self.w.clock
        self.w.advance(1000)
        self.assertEqual(self.p.kills, 1)
        self.assertNotIn(m, self.lvl.monsters)

    def test_no_target_costs_nothing(self):
        self.zap()
        self.assertEqual(self.wand.charges, WAND_CHARGES)
        self.assertEqual(self.p.turns, 0)

    def test_out_of_range_costs_nothing(self):
        spots = [c for c in self.lvl.floor_cells if self.w.fov(self.p)[c]
                 and max(abs(c[0] - self.p.x), abs(c[1] - self.p.y)) > WAND_RANGE]
        if spots:
            m = make_monster("ogre", 901)
            m.next_time = 10 ** 9
            self.lvl.place(m, *spots[0])
            self.lvl.monsters.append(m)
            self.zap()
            self.assertEqual(self.wand.charges, WAND_CHARGES)

    def test_breaks_after_ten_uses(self):
        self.monster()
        for _ in range(WAND_CHARGES):
            self.assertEqual(self.p.pack, [self.wand])
            self.zap()
        self.assertEqual(self.p.pack, [])
        self.assertIn("crumbles to ash", str(self.w.drain_outbox()))
        self.assertTrue(self.p.pack_dirty)

    def test_a_dropped_wand_keeps_its_charges(self):
        self.monster()
        self.zap()
        self.w.advance(200)
        self.w.submit(self.p, {"a": "drop", "slot": 0})
        self.w.advance(1)
        self.assertEqual(next(iter(self.lvl.items.values())).charges, WAND_CHARGES - 1)

    def test_info_counts_down(self):
        self.assertEqual(make_wand().info, "fire, 10 uses left")
        self.wand.charges = 1
        self.assertEqual(self.wand.info, "fire, 1 use left")

    def test_the_bolt_reaches_the_client_and_fades(self):
        m = self.monster(3)
        self.w.drain_outbox()
        self.zap()
        fx = [msg for _, msg in self.w.drain_outbox() if msg["t"] == "fx"]
        self.assertEqual(len(fx), 1)
        self.assertEqual(tuple(fx[0]["cells"][-1]), (m.x, m.y))
        v = ClientView()
        v.apply({"t": "welcome", "id": self.p.id, "name": self.p.name})
        v.apply(self.w.level_msg(1))
        v.apply(self.w.state_for(self.p))
        v.apply(fx[0])
        self.assertEqual(len(v.bolts), 1)
        x, y = fx[0]["cells"][0]
        self.assertGreater(int(v.draw()["bg"][21 + x, 3 + y][0]), 150)
        v.bolts = [(v.bolts[0][0], v.bolts[0][1] - 5, v.bolts[0][2])]
        v.draw()
        self.assertEqual(v.bolts, [])

    def test_a_line_runs_end_to_end(self):
        path = line_between((0, 0), (4, 2))
        self.assertEqual(path[-1], (4, 2))
        self.assertEqual(len(path), 4)


if __name__ == "__main__":
    unittest.main()
