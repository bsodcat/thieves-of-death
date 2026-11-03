"""Lakes, rivers, pits and locked rooms."""
import random
import unittest

import numpy as np

from game import mapgen
from game.constants import FALL_DAMAGE, KEY_DISTANCE, LOCKED_ROOM_FLOORS, MAP_H, MAP_W
from game.items import make_key
from game.pathing import next_step
from game.render import ClientView
from game.tiles import (DEEP, DESCRIPTIONS, DOOR, FG, FLOOR, GLYPH, HOVER, LOCK_COLORS, LOCKED, NAMES, PIT, SHALLOW,
                        WALKABLE, BG, TRANSPARENT)
from game.world import Level, LockedRoom, World, plan_locked_rooms

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


def world_with(*tiles, seed=1):
    """A world whose first floor has these (x offset, tile) next to the start, and a player."""
    w = World(seed)
    gen = mapgen.generate(seed, 1)
    gen.tiles[gen.tiles > 2] = np.where(gen.tiles[gen.tiles > 2] >= 5, FLOOR, gen.tiles[gen.tiles > 2])
    lvl = w.levels[1] = Level(1, gen)
    p = w.join("A")
    for m in list(lvl.occupant.values()):
        if m is not p:
            lvl.remove(m)
    lvl.monsters.clear()
    lvl.items.clear()
    # somewhere with a clear row to the right
    x, y = next((x, y) for x, y in lvl.floor_cells
                if all(lvl.tiles[x + i, y] == FLOOR and lvl.tiles[x + i, y + 1] == FLOOR for i in range(6)))
    lvl.move(p, x, y)
    for offset, tile in tiles:
        gen.tiles[x + offset, y] = tile
    lvl.walkable, lvl.hover = WALKABLE[gen.tiles], HOVER[gen.tiles]
    lvl.mainland = lvl.mainland & lvl.walkable
    lvl._base_transparent = TRANSPARENT[gen.tiles]
    lvl.door_version += 1
    return w, lvl, p


def step(w, p, dx=1, dy=0):
    w.advance(100)
    w.submit(p, {"a": "move", "dx": dx, "dy": dy})
    w.advance(100)


class TileTableTests(unittest.TestCase):
    def test_tables_match(self):
        n = len(NAMES)
        for table in (DESCRIPTIONS, WALKABLE, HOVER, TRANSPARENT, GLYPH, FG, BG):
            self.assertEqual(len(table), n)

    def test_new_glyphs_are_in_the_game_font(self):
        import tcod.tileset
        for code in GLYPH.tolist() + [0x2640]:
            self.assertIn(code, tcod.tileset.CHARMAP_CP437)


class GenerationTests(unittest.TestCase):
    def sound(self, g):
        walk = WALKABLE[g.tiles].copy()
        if g.lock:
            walk[g.vault] = False
        on_foot = reachable(walk, g.up_front)
        self.assertIn(g.down_front, on_foot)
        if g.lock:
            self.assertTrue(any((g.lock[0] + dx, g.lock[1] + dy) in on_foot for dx, dy in DIRS4))
        cells = {(int(x), int(y)) for x, y in np.argwhere(walk)}
        self.assertEqual(cells - reachable(walk | (g.tiles == DEEP), g.up_front), set())

    def test_stairs_stay_reachable_on_foot(self):
        for seed in range(150):
            self.sound(mapgen.generate(seed, 1 + seed % 26))

    def test_stairs_survive_with_a_locked_room_too(self):
        for seed in range(100):
            g = mapgen.generate(seed, 6, LOCKED["red"])
            self.sound(g)
            self.assertEqual(g.tiles[g.lock], LOCKED["red"])

    def test_every_kind_of_terrain_turns_up(self):
        found = np.concatenate([mapgen.generate(seed, 2).tiles.ravel() for seed in range(60)])
        for tile in (SHALLOW, DEEP, PIT):
            self.assertTrue((found == tile).any(), NAMES[tile])

    def test_water_goes_through_rock(self):
        for seed in range(40):
            river = mapgen._river(random.Random(seed))
            across = river[1:-1].any(axis=1).all()
            down = river[:, 1:-1].any(axis=0).all()
            self.assertTrue(across or down, seed)   # edge to edge, whatever's in the way

    def test_a_locked_room_is_only_reached_through_its_door(self):
        for seed in range(100):
            g = mapgen.generate(seed, 8, LOCKED["blue"])
            self.assertGreaterEqual(int(g.vault.sum()), 6)
            inside = {(int(x), int(y)) for x, y in np.argwhere(g.vault)}
            for x, y in inside:
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        n = (x + dx, y + dy)
                        if n not in inside and n != g.lock:
                            self.assertFalse(TRANSPARENT[g.tiles[n]] or WALKABLE[g.tiles[n]], (seed, n))

    def test_levels_stay_deterministic(self):
        a, b = mapgen.generate(9, 7, LOCKED["green"]), mapgen.generate(9, 7, LOCKED["green"])
        self.assertTrue(np.array_equal(a.tiles, b.tiles))


class WaterTests(unittest.TestCase):
    def test_deep_water_stops_you_for_free(self):
        w, lvl, p = world_with((1, DEEP))
        before = (p.x, p.y)
        turns = p.turns
        step(w, p)
        self.assertEqual((p.x, p.y), before)
        self.assertEqual(p.turns, turns)
        self.assertIn("too deep", str(w.drain_outbox()))

    def test_shallow_water_is_just_ground(self):
        w, lvl, p = world_with((1, SHALLOW))
        x = p.x
        step(w, p)
        self.assertEqual(p.x, x + 1)

    def test_you_can_see_across_water(self):
        w, lvl, p = world_with((1, DEEP), (2, DEEP))
        self.assertTrue(w.fov(p)[p.x + 3, p.y])

    def test_monsters_never_enter(self):
        w = World(4)
        lvl = w.level(3)
        for m in lvl.monsters:
            self.assertTrue(lvl.walkable[m.x, m.y])
        self.assertTrue(all(lvl.walkable[c] for c in lvl.items))

    def test_levitation_crosses_water_diagonally_too(self):
        w, lvl, p = world_with((1, DEEP), (2, DEEP))
        lvl.tiles[p.x + 1, p.y + 1] = DEEP
        lvl.walkable[p.x + 1, p.y + 1] = False
        lvl.hover[p.x + 1, p.y + 1] = True
        p.levitate_until = w.clock + 100000
        x, y = p.x, p.y
        step(w, p, 1, 1)
        self.assertEqual((p.x, p.y), (x + 1, y + 1))

    def test_levitation_ending_over_water_puts_you_ashore(self):
        w, lvl, p = world_with((1, DEEP))
        p.levitate_until = w.clock + 100000
        step(w, p)
        self.assertEqual(lvl.tiles[p.x, p.y], DEEP)
        p.levitate_until = w.clock + 1
        w.advance(10)
        self.assertTrue(lvl.walkable[p.x, p.y])
        self.assertEqual(lvl.occupant[(p.x, p.y)], p)

    def test_drops_over_water_land_on_ground(self):
        w, lvl, p = world_with((1, DEEP))
        p.gold = 50
        p.levitate_until = w.clock + 100000
        step(w, p)
        w.submit(p, {"a": "dropgold"})
        w.advance(100)
        self.assertTrue(lvl.items)
        self.assertTrue(all(lvl.walkable[c] for c in lvl.items))

    def test_dying_over_water_leaves_bones_on_land(self):
        w, lvl, p = world_with((1, DEEP))
        w.mode = "Revive"
        p.levitate_until = w.clock + 100000
        step(w, p)
        w._kill(p, None)
        self.assertTrue(lvl.walkable[p.x, p.y])

    def test_cant_swap_an_ally_into_the_water(self):
        w, lvl, p = world_with((1, DEEP))
        q = w.join("B")
        lvl.move(q, p.x + 1, p.y)  # floating over the water
        q.levitate_until = w.clock + 100000
        here = (p.x, p.y)
        step(w, p)
        self.assertEqual((p.x, p.y), here)


def island_world(depth=3, **kwargs):
    """A world with a player on the main part of a floor that has an island."""
    for seed in range(300):
        w = World(seed)
        lvl = w.level(depth)
        cut = np.argwhere(lvl.walkable & ~lvl.mainland)
        if len(cut) >= 4:
            p = w.join("A")
            w.levels[p.depth].remove(p)
            for m in list(lvl.monsters):
                lvl.remove(m)
            lvl.monsters.clear()
            lvl.place(p, *lvl.free_near(*lvl.up_front))
            return w, lvl, p, [(int(x), int(y)) for x, y in cut]
    raise AssertionError("no islands")


def shore_of(lvl, cells):
    """An island tile beside deep water, and the way into the water."""
    for x, y in cells:
        for dx, dy in DIRS4:
            if lvl.tiles[x + dx, y + dy] == DEEP:
                return (x, y), (dx, dy)
    raise AssertionError("no shore")


class IslandTests(unittest.TestCase):
    def test_a_good_share_of_floors_have_one(self):
        cut = 0
        for seed in range(80):
            g = mapgen.generate(seed, 3)
            walk = WALKABLE[g.tiles]
            cut += len(reachable(walk, g.up_front)) < int(walk.sum())
        self.assertGreater(cut, 20)

    def test_some_are_real_rooms(self):
        sizes = []
        for seed in range(80):
            g = mapgen.generate(seed, 3)
            walk = WALKABLE[g.tiles]
            sizes.append(int(walk.sum()) - len(reachable(walk, g.up_front)))
        self.assertGreater(max(sizes), 40)

    def test_stairs_are_never_cut_off(self):
        for seed in range(300):
            w = World(seed)
            lvl = w.level(1 + seed % 30)
            self.assertTrue(lvl.mainland[lvl.up_front] and lvl.mainland[lvl.down_front], seed)

    def test_everything_the_game_needs_is_on_the_mainland(self):
        for seed in range(40):
            w = World(seed)
            w.locked_rooms = {3: LockedRoom(3, 4, "red")}
            w.join("A")
            for depth in (3, 4, 5):
                lvl = w.level(depth)
                self.assertTrue(all(lvl.mainland[m.x, m.y] for m in lvl.monsters))
                if lvl.merchant:
                    self.assertTrue(lvl.mainland[lvl.merchant.x, lvl.merchant.y])
                for spot, item in lvl.items.items():
                    if item.category in ("key", "cloak"):
                        self.assertTrue(lvl.mainland[spot], (seed, depth, item.name))
                if lvl.lock:
                    self.assertTrue(any(lvl.mainland[lvl.lock[0] + dx, lvl.lock[1] + dy] for dx, dy in DIRS4))

    def test_loot_can_lie_on_islands(self):
        found = 0
        for seed in range(150):
            lvl = World(seed).level(3)
            found += any(not lvl.mainland[c] for c in lvl.items)
        self.assertGreater(found, 3)

    def test_you_never_fall_onto_one(self):
        w, lvl, p, cut = island_world()
        for x, y in cut:
            self.assertTrue(lvl.mainland[lvl.landing(x, y)])

    def test_you_never_teleport_onto_one(self):
        w, lvl, p, cut = island_world()
        for _ in range(100):
            w.teleport(p)
            self.assertTrue(lvl.mainland[p.x, p.y])

    def test_monsters_dont_try_to_wander_there(self):
        w, lvl, p, cut = island_world()
        self.assertEqual(set(cut) & set(lvl.land_cells), set())

    def test_you_cant_swim_out(self):
        w, lvl, p, cut = island_world()
        water = next((x, y) for x, y in map(tuple, np.argwhere(lvl.tiles == DEEP)) for dx, dy in DIRS4
                     if lvl.mainland[x + dx, y + dy])
        beside = next((int(water[0]) + dx, int(water[1]) + dy) for dx, dy in DIRS4
                      if lvl.mainland[int(water[0]) + dx, int(water[1]) + dy])
        lvl.move(p, *beside)
        step(w, p, int(water[0]) - beside[0], int(water[1]) - beside[1])
        self.assertEqual((p.x, p.y), beside)

    def test_you_can_swim_back_slowly(self):
        w, lvl, p, cut = island_world()
        spot, (dx, dy) = shore_of(lvl, cut)
        lvl.move(p, *spot)
        w.advance(300)
        w.submit(p, {"a": "move", "dx": dx, "dy": dy})
        self.assertEqual(p.next_time - w.clock, 2 * p.move_cost)
        self.assertEqual(lvl.tiles[p.x, p.y], DEEP)
        self.assertIn("swim for it", str(w.drain_outbox()))

    def test_a_stranded_player_can_always_get_home(self):
        for seed in range(150):
            w = World(seed)
            lvl = w.level(3)
            walk = lvl.walkable | (lvl.tiles == DEEP)
            hidden = lvl.hidden if lvl.hidden is not None else np.zeros_like(walk)  # bombed open, not swum to
            for x, y in map(tuple, np.argwhere(lvl.walkable & ~lvl.mainland & ~hidden)):
                self.assertIn(lvl.up_front, reachable(walk, (int(x), int(y))))

    def test_a_potion_gets_you_there_and_running_out_doesnt_strand_you(self):
        w, lvl, p, cut = island_world()
        spot, (dx, dy) = shore_of(lvl, cut)
        lvl.move(p, spot[0] + dx, spot[1] + dy)
        p.waterwalk_until = w.clock + 10 ** 6
        step(w, p, -dx, -dy)
        self.assertEqual((p.x, p.y), spot)
        self.assertFalse(lvl.mainland[p.x, p.y])
        p.waterwalk_until = w.clock + 1
        w.advance(50)
        self.assertEqual((p.x, p.y), spot)     # standing on ground, so it just wears off
        step(w, p, dx, dy)
        self.assertEqual(lvl.tiles[p.x, p.y], DEEP)

    def test_a_potion_running_out_in_the_water_puts_you_on_the_mainland(self):
        w, lvl, p, cut = island_world()
        spot, (dx, dy) = shore_of(lvl, cut)
        lvl.move(p, spot[0] + dx, spot[1] + dy)
        p.waterwalk_until = w.clock + 1
        w.advance(50)
        self.assertTrue(lvl.mainland[p.x, p.y])

    def test_bones_on_an_island_come_back_to_the_mainland(self):
        w, lvl, p, cut = island_world()
        w.mode = "Revive"
        w.join("B")
        lvl.move(p, *cut[0])
        w._kill(p, None)
        self.assertTrue(lvl.mainland[p.x, p.y])

    def test_rejoining_on_an_island_comes_back_to_the_mainland(self):
        w, lvl, p, cut = island_world()
        lvl.move(p, *cut[0])
        w.leave(p)
        back = w.join("A")
        self.assertTrue(lvl.mainland[back.x, back.y])

    def test_an_opened_locked_room_counts_as_mainland(self):
        w = World(4)
        w.locked_rooms = {2: LockedRoom(2, 4, "red")}
        lvl = w.level(2)
        lvl.unlock()
        self.assertTrue(lvl.mainland[lvl.vault].all())


class PitTests(unittest.TestCase):
    def test_walking_in_drops_you_a_floor(self):
        w, lvl, p = world_with((1, PIT))
        hp, x, y = p.hp, p.x, p.y
        step(w, p)
        self.assertEqual(p.depth, 2)
        self.assertTrue(w.levels[2].walkable[p.x, p.y])
        self.assertLessEqual(hp - p.hp, FALL_DAMAGE[1])
        self.assertGreaterEqual(hp - p.hp, FALL_DAMAGE[0] - 1)   # a little comes back by itself
        self.assertTrue(p.needs_level)
        self.assertNotIn(p, lvl.occupant.values())

    def test_a_fall_cant_kill(self):
        w, lvl, p = world_with((1, PIT))
        p.hp = 1
        step(w, p)
        self.assertTrue(p.alive)
        self.assertGreaterEqual(p.hp, 1)

    def test_a_held_direction_stops_after_the_fall(self):
        w, lvl, p = world_with((1, PIT))
        w.advance(100)
        w.submit(p, {"a": "hold", "dx": 1, "dy": 0, "press": True})
        w.advance(100)
        self.assertEqual(p.depth, 2)
        self.assertIsNone(p.hold)

    def test_you_land_near_where_you_fell(self):
        w = World(3)
        below = w.level(2)
        x, y = below.floor_cells[len(below.floor_cells) // 2]
        self.assertEqual(below.landing(x, y), (x, y))

    def test_you_never_land_in_a_locked_room(self):
        w = World(3)
        w.locked_rooms = {2: LockedRoom(2, 4, "red")}
        below = w.level(2)
        for x, y in np.argwhere(below.vault):
            spot = below.landing(int(x), int(y))
            self.assertFalse(below.vault[spot])

    def test_levitation_floats_over_until_it_ends(self):
        w, lvl, p = world_with((1, PIT))
        p.levitate_until = w.clock + 100000
        step(w, p)
        self.assertEqual(p.depth, 1)
        self.assertEqual(lvl.tiles[p.x, p.y], PIT)
        p.levitate_until = w.clock + 1
        w.advance(10)
        self.assertEqual(p.depth, 2)

    def test_auto_walk_goes_around(self):
        w, lvl, p = world_with((1, PIT))
        step_taken = next_step(WALKABLE[lvl.tiles], (p.x, p.y), (p.x + 2, p.y))
        self.assertNotEqual(step_taken, (1, 0))


class LockedRoomTests(unittest.TestCase):
    def locked_world(self, key_above=True):
        for seed in range(1, 400):
            w = World(seed)
            rooms = [r for r in w.locked_rooms.values() if (r.key_depth < r.depth) == key_above]
            if rooms:
                return w, rooms[0]
        raise AssertionError("no seed with a locked room")

    def test_the_plan_follows_the_rules(self):
        counts = []
        for seed in range(2000):
            rooms = plan_locked_rooms(seed)
            counts.append(len(rooms))
            self.assertEqual(len({r.color for r in rooms.values()}), len(rooms))
            for r in rooms.values():
                self.assertTrue(LOCKED_ROOM_FLOORS[0] <= r.depth <= LOCKED_ROOM_FLOORS[1])
                self.assertEqual(abs(r.key_depth - r.depth), KEY_DISTANCE)
        self.assertTrue(1.2 < sum(counts) / len(counts) < 2.1, sum(counts) / len(counts))
        self.assertIn(0, counts)
        self.assertGreater(max(counts), 1)

    def test_the_plan_comes_from_the_seed(self):
        self.assertEqual(plan_locked_rooms(77), plan_locked_rooms(77))

    def test_key_and_door_match(self):
        for key_above in (True, False):
            w, room = self.locked_world(key_above)
            door = w.level(room.depth)
            self.assertEqual(door.tiles[door.lock], LOCKED[room.color])
            keys = [i for i in w.level(room.key_depth).items.values() if i.category == "key" and i.opens == room.depth]
            self.assertEqual(len(keys), 1)
            self.assertEqual(keys[0].color, LOCK_COLORS[room.color])
            self.assertEqual(tuple(int(c) for c in FG[door.tiles[door.lock]]), keys[0].color)

    def test_nothing_spawns_or_wanders_inside_but_the_treasure(self):
        w, room = self.locked_world()
        lvl = w.level(room.depth)
        inside = [c for c in lvl.items if lvl.vault[c]]
        self.assertEqual(len(inside), 4)
        self.assertFalse(any(lvl.vault[m.x, m.y] for m in lvl.monsters))
        self.assertFalse(any(lvl.vault[c] for c in lvl.floor_cells))

    def next_to_lock(self):
        w, room = self.locked_world()
        lvl = w.level(room.depth)
        p = w.join("A")
        lvl1 = w.levels[p.depth]
        lvl1.remove(p)
        x, y = lvl.lock
        front = next((x + dx, y + dy) for dx, dy in DIRS4 if lvl.walkable[x + dx, y + dy]
                     and not lvl.vault[x + dx, y + dy])
        lvl.place(p, *lvl.free_near(*front))
        lvl.monsters.clear()
        for m in list(lvl.occupant.values()):
            if m is not p:
                lvl.remove(m)
        if (p.x, p.y) != front:
            lvl.move(p, *front)
        return w, room, lvl, p, (x - front[0], y - front[1])

    def test_no_key_no_entry(self):
        w, room, lvl, p, (dx, dy) = self.next_to_lock()
        here = (p.x, p.y)
        step(w, p, dx, dy)
        self.assertEqual((p.x, p.y), here)
        self.assertIsNotNone(lvl.lock)
        self.assertIn("2 floors away", str(w.drain_outbox()))

    def test_the_wrong_key_doesnt_fit(self):
        w, room, lvl, p, (dx, dy) = self.next_to_lock()
        p.pack.append(make_key(room.color, room.depth + 1))
        step(w, p, dx, dy)
        self.assertIsNotNone(lvl.lock)

    def test_the_key_opens_the_door_for_everyone(self):
        w, room, lvl, p, (dx, dy) = self.next_to_lock()
        spot = lvl.lock
        p.pack.append(make_key(room.color, room.depth))
        p.needs_level = False
        step(w, p, dx, dy)
        self.assertEqual(lvl.tiles[spot], DOOR)
        self.assertEqual(p.pack, [])
        self.assertTrue(p.needs_level)
        self.assertIsNone(lvl.lock)
        step(w, p, dx, dy)
        self.assertEqual((p.x, p.y), spot)
        step(w, p, dx, dy)
        self.assertTrue(lvl.vault[p.x, p.y])

    def test_keys_do_nothing_from_the_pack(self):
        w, room, lvl, p, _ = self.next_to_lock()
        p.pack.append(make_key(room.color, room.depth))
        w.submit(p, {"a": "use", "slot": 0})
        w.advance(100)
        self.assertEqual(len(p.pack), 1)

    def test_keys_are_picked_up_by_walking(self):
        w, room = self.locked_world()
        lvl = w.level(room.key_depth)
        spot, key = next((c, i) for c, i in lvl.items.items() if i.category == "key")
        p = w.join("A")
        w.levels[p.depth].remove(p)
        lvl.place(p, *spot)
        w._step_onto(p, lvl)
        self.assertEqual(p.pack, [key])
        self.assertNotIn(spot, lvl.items)

    def test_a_new_run_plans_new_rooms(self):
        w = World(5)
        w.join("A")
        seed = w.seed
        w.reset_run()
        self.assertNotEqual(seed, w.seed)
        self.assertEqual(w.locked_rooms, plan_locked_rooms(w.seed))

    def test_the_client_can_look_at_all_of_it(self):
        v = ClientView()
        tiles = np.zeros((MAP_W, MAP_H), np.uint8)
        for t in range(len(NAMES)):
            tiles[t, 0] = t
        v.levels[1], v.depth = tiles, 1
        v.seen[1] = np.ones((MAP_W, MAP_H), bool)
        v.visible = np.ones((MAP_W, MAP_H), bool)
        for t in range(len(NAMES)):
            self.assertEqual(v.describe(t, 0)[0][0], NAMES[t].capitalize())
        v.draw()


if __name__ == "__main__":
    unittest.main()
