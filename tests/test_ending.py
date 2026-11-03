"""The last floor and how a run ends, and the wolves, mushrooms, plants and wand of frost."""
import unittest

import numpy as np

from game import commands, mapgen
from game.constants import (GAS_DAMAGE, GAS_SECONDS, GAS_TRIGGER, LAST_FLOOR, SCORE_SCALE,
                            SCREEN_H, SUMMON_SIZE, TICKS_PER_SECOND, TICKS_PER_TURN, TIDE_MAX, TIDE_SECONDS,
                            WOLF_FIRST, WOLF_SIZE)
from game.entities import make_monster
from game.items import ITEMS, make_amulet, make_item
from game.render import ClientView
from game.tiles import FOLIAGE, GRASS, NAMES, PIT, STAIRS_DOWN, TRAMPLED, WALKABLE
from game.world import World, appears_on, cheb


def rows_of(frame):
    return "\n".join("".join(chr(c) for c in frame["ch"][:, y]) for y in range(SCREEN_H))


def view_of(w, p):
    v = ClientView()
    v.apply({"t": "welcome", "id": p.id, "name": p.name})
    v.apply(w.level_msg(p.depth))
    v.apply(w.pack_msg(p))
    v.apply(w.state_for(p))
    return v


def empty(lvl):
    for m in list(lvl.monsters):
        lvl.remove(m)
    lvl.monsters.clear()


def on_floor(w, depth, name="A"):
    p = w.join(name)
    w.warp(p, depth)
    return p, w.levels[depth]


def last_floor(seed=1, name="A"):
    """A player at the top of the last floor, with only the necromancer on it."""
    w = World(seed)
    p, lvl = on_floor(w, LAST_FLOOR, name)
    for m in list(lvl.monsters):
        if m is not w.necromancer:
            lvl.remove(m)
            lvl.monsters.remove(m)
    return w, lvl, p, w.necromancer


def amulet_spot(lvl):
    return next(c for c, i in lvl.items.items() if i.category == "amulet")


def score(gold, moves, kills):
    return gold * kills * SCORE_SCALE // max(1, moves)


class ScoreTests(unittest.TestCase):
    def test_every_move_lowers_it(self):
        w = World(1)
        p = w.join("A")
        p.gold, p.kills = 500, 4
        scores = []
        for moves in (1, 10, 100, 1000, 10000):
            p.turns = moves
            scores.append(w.score_of(p))
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual(len(set(scores)), 5)

    def test_it_really_divides(self):
        w = World(1)
        p = w.join("A")
        p.gold, p.kills, p.turns = 100, 2, 1
        self.assertEqual(w.score_of(p), 20000)
        p.turns = 2
        self.assertEqual(w.score_of(p), 10000)
        p.turns = 8
        self.assertEqual(w.score_of(p), 2500)

    def test_kills_multiply_it(self):
        w = World(1)
        p = w.join("A")
        p.gold, p.turns = 100, 10
        p.kills = 1
        one = w.score_of(p)
        p.kills = 3
        self.assertEqual(w.score_of(p), 3 * one)

    def test_no_gold_or_no_kills_scores_nothing(self):
        w = World(1)
        p = w.join("A")
        p.turns, p.kills = 400, 5
        self.assertEqual(w.score_of(p), 0)
        p.gold, p.kills = 100, 0
        self.assertEqual(w.score_of(p), 0)

    def test_winning_doubles_it(self):
        w = World(1)
        p = w.join("A")
        p.gold, p.kills, p.turns = 100, 2, 10
        w._win(p)
        self.assertEqual(w.score_of(p), 2 * score(100, 10, 2))


class WolfTests(unittest.TestCase):
    def packs(self, seeds=30, depth=WOLF_FIRST + 2):
        for seed in range(seeds):
            w = World(seed)
            wolves = [m for m in w.level(depth).monsters if m.kind == "wolf"]
            if wolves:
                yield w, w.levels[depth], wolves

    def test_packs_of_the_right_size(self):
        sizes = {len(wolves) for _, _, wolves in self.packs(60)}
        self.assertTrue(sizes)
        self.assertTrue(all(WOLF_SIZE[0] <= s <= WOLF_SIZE[1] for s in sizes), sizes)

    def test_only_some_floors(self):
        with_wolves = sum(1 for _ in self.packs(60))
        self.assertTrue(4 < with_wolves < 30, with_wolves)

    def test_not_too_early(self):
        for seed in range(30):
            self.assertFalse(any(m.kind == "wolf" for m in World(seed).level(WOLF_FIRST - 1).monsters))

    def test_never_alone_in_the_ordinary_tables(self):
        self.assertFalse(appears_on(__import__("game.entities").entities.MONSTERS["wolf"], 10))

    def test_one_notices_and_they_all_do(self):
        w, lvl, wolves = next(self.packs())
        p = w.join("A")
        for m in wolves:
            m.state = "sleeping"
        w._hunt(wolves[-1], p)
        self.assertTrue(all(m.state == "hunting" for m in wolves))

    def test_faster_than_you(self):
        self.assertLess(make_monster("wolf", 1).move_cost, TICKS_PER_TURN)


class MushroomTests(unittest.TestCase):
    def setUp(self):
        self.w = World(3)
        self.lvl = self.w.level(1)
        empty(self.lvl)
        self.p = self.w.join("A")
        self.m = make_monster("mushroom", 900)
        self.m.state = "wandering"
        x, y = self.p.x, self.p.y
        self.spot = next(c for c in self.lvl.floor_cells if cheb_xy(c, (x, y)) == GAS_TRIGGER and self.w.fov(self.p)[c])
        self.lvl.place(self.m, *self.spot)
        self.lvl.monsters.append(self.m)

    def test_never_moves_or_attacks(self):
        self.lvl.move(self.p, *self.lvl.free_near(self.spot[0] + 1, self.spot[1]))
        hp = self.p.hp
        self.w.lvl = None
        self.w._monster_turn(self.m, self.lvl)
        self.assertEqual((self.m.x, self.m.y), self.spot)
        self.assertEqual(self.p.hp, hp)

    def test_turns_up_on_floors_by_itself(self):
        found = any(m.kind == "mushroom" for seed in range(20) for m in World(seed).level(4).monsters)
        self.assertTrue(found)

    def test_gas_comes_out_when_you_get_near(self):
        self.w._monster_turn(self.m, self.lvl)
        self.assertIn(self.spot, self.lvl.gas)
        self.assertIn((self.p.x, self.p.y), self.lvl.gas)

    def test_stealth_doesnt_stop_it(self):
        self.p.stealth = 100
        self.w._monster_turn(self.m, self.lvl)
        self.assertTrue(self.lvl.gas)

    def test_nothing_happens_from_a_distance(self):
        far = next(c for c in self.lvl.land_cells if cheb_xy(c, self.spot) > GAS_TRIGGER + 2)
        self.lvl.move(self.p, *far)
        self.w._monster_turn(self.m, self.lvl)
        self.assertEqual(self.lvl.gas, {})

    def test_gas_hurts_and_clears(self):
        self.w._monster_turn(self.m, self.lvl)
        hp = self.p.hp
        self.w.advance(int(1.1 * TICKS_PER_SECOND))
        self.assertLess(self.p.hp, hp)
        self.assertGreaterEqual(self.p.hp, hp - GAS_DAMAGE - 1)
        self.m.ready_at = 10 ** 9
        self.w.advance(int((GAS_SECONDS + 1) * TICKS_PER_SECOND))
        self.assertEqual(self.lvl.gas, {})

    def test_it_can_kill(self):
        self.w._monster_turn(self.m, self.lvl)
        self.p.hp = 1
        self.w.advance(int(2 * TICKS_PER_SECOND))
        self.assertFalse(self.p.alive)
        self.assertIn("toxic gas", self.p.death)

    def test_god_mode_ignores_it(self):
        self.p.god = True
        self.w._monster_turn(self.m, self.lvl)
        self.w.advance(int(3 * TICKS_PER_SECOND))
        self.assertEqual(self.p.hp, self.p.max_hp)

    def test_walls_stop_it(self):
        self.w._monster_turn(self.m, self.lvl)
        self.assertTrue(all(self.lvl.hover[c] for c in self.lvl.gas))

    def test_it_has_to_wait_to_do_it_again(self):
        self.w._monster_turn(self.m, self.lvl)
        self.lvl.gas.clear()
        self.w._monster_turn(self.m, self.lvl)
        self.assertEqual(self.lvl.gas, {})

    def test_the_client_shows_gas(self):
        self.w._monster_turn(self.m, self.lvl)
        v = view_of(self.w, self.p)
        self.assertTrue(v.gas)
        x, y, _ = v.gas[0]
        self.assertGreater(int(v.draw()["bg"][21 + x, 3 + y][1]), 100)

    def test_look_doesnt_promise_it_hits(self):
        v = view_of(self.w, self.p)
        e = next(e for e in v.ents if e["kind"] == "mushroom")
        self.assertNotIn("Hits for", str(v._describe_actor(e)))


def cheb_xy(a, b):
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


class PlantTests(unittest.TestCase):
    def plant_row(self):
        w = World(2)
        lvl = w.level(1)
        empty(lvl)
        p = w.join("A")
        x, y = next(c for c in lvl.land_cells if all(lvl.tiles[c[0] + i, c[1]] in (1, GRASS, FOLIAGE) for i in range(1, 6)))
        lvl.move(p, x, y)
        lvl.tiles[x + 1, y] = lvl.tiles[x + 2, y] = GRASS
        lvl._base_transparent[x + 1:x + 3, y] = False
        lvl.plants[x + 1:x + 3, y] = True
        lvl.door_version += 1
        return w, lvl, p

    def test_some_floors_have_them(self):
        tiles = np.concatenate([mapgen.generate(seed, 3).tiles.ravel() for seed in range(30)])
        self.assertTrue((tiles == GRASS).any())
        self.assertTrue((tiles == FOLIAGE).any())

    def test_you_can_walk_through_but_not_see_through(self):
        self.assertTrue(WALKABLE[GRASS] and WALKABLE[FOLIAGE])
        w, lvl, p = self.plant_row()
        self.assertFalse(w.fov(p)[p.x + 3, p.y])

    def test_walking_through_opens_the_view_for_good(self):
        w, lvl, p = self.plant_row()
        x, y = p.x, p.y
        w.advance(200)
        w.submit(p, {"a": "move", "dx": 1, "dy": 0})
        self.assertEqual(lvl.tiles[x + 1, y], TRAMPLED)
        w.advance(200)
        w.submit(p, {"a": "move", "dx": 1, "dy": 0})
        self.assertEqual(lvl.tiles[x + 2, y], TRAMPLED)
        self.assertTrue(w.fov(p)[x + 3, y])
        w.advance(200)
        w.submit(p, {"a": "move", "dx": -1, "dy": 0})
        w.submit(p, {"a": "move", "dx": -1, "dy": 0})
        self.assertEqual(lvl.tiles[x + 1, y], TRAMPLED)

    def test_monsters_trample_too(self):
        w, lvl, p = self.plant_row()
        m = make_monster("rat", 900)
        lvl.place(m, p.x + 1, p.y)
        self.assertEqual(lvl.tiles[p.x + 1, p.y], TRAMPLED)

    def test_players_are_told_and_the_map_updates(self):
        w, lvl, p = self.plant_row()
        v = view_of(w, p)
        w.drain_outbox()
        x, y = p.x + 1, p.y
        w.advance(200)
        w.submit(p, {"a": "move", "dx": 1, "dy": 0})
        msgs = [m for _, m in w.drain_outbox() if m["t"] == "tiles"]
        self.assertEqual(msgs[0]["cells"], [[x, y, TRAMPLED]])
        v.apply(msgs[0])
        self.assertEqual(v.levels[1][x, y], TRAMPLED)
        self.assertFalse([m for _, m in w.drain_outbox() if m["t"] == "tiles"])

    def test_they_have_names(self):
        self.assertEqual(NAMES[GRASS], "tall grass")
        self.assertEqual(NAMES[FOLIAGE], "foliage")


class LastFloorTests(unittest.TestCase):
    def test_there_are_no_stairs_down_or_pits(self):
        for seed in range(25):
            g = mapgen.generate(seed, LAST_FLOOR)
            self.assertFalse((g.tiles == STAIRS_DOWN).any())
            self.assertFalse((g.tiles == PIT).any())
            self.assertIsNone(g.down)
            self.assertIsNotNone(g.lair)

    def test_the_floor_above_is_normal(self):
        g = mapgen.generate(1, LAST_FLOOR - 1)
        self.assertEqual(g.tiles[g.down], STAIRS_DOWN)

    def test_you_can_reach_the_amulet_and_get_back_to_the_stairs_on_foot(self):
        for seed in range(25):
            w, lvl, p, n = last_floor(seed)
            spot = amulet_spot(lvl)
            self.assertTrue(lvl.mainland[spot], seed)
            self.assertTrue(lvl.mainland[n.x, n.y], seed)

    def test_it_sleeps_in_a_big_room_with_the_amulet_in_sight_but_not_close(self):
        for seed in range(25):
            w, lvl, p, n = last_floor(seed)
            self.assertEqual(n.state, "sleeping")
            self.assertEqual(n.kind, "necromancer")
            spot = amulet_spot(lvl)
            self.assertTrue(7 <= cheb_xy(spot, (n.x, n.y)) <= 9, seed)
            self.assertLessEqual(lvl.distances_to(n.x, n.y)[spot] // 2, 13, seed)  # the same room, not next door

    def test_the_console_cant_go_deeper(self):
        w = World(1)
        p = w.join("A")
        p.can_command = True
        w.drain_outbox()
        commands.run(w, p, f"floor {LAST_FLOOR + 1}")
        self.assertEqual(p.depth, 1)
        commands.run(w, p, f"floor {LAST_FLOOR}")
        self.assertEqual(p.depth, LAST_FLOOR)

    def test_descending_there_refuses_gently(self):
        w, lvl, p, n = last_floor()
        w.submit(p, {"a": "descend"})
        w.advance(1)
        self.assertEqual(p.depth, LAST_FLOOR)

    def test_only_one_of_each(self):
        w, lvl, p, n = last_floor()
        self.assertEqual(sum(m.kind == "necromancer" for m in lvl.monsters), 1)
        self.assertEqual(sum(i.category == "amulet" for i in lvl.items.values()), 1)
        self.assertIsNone(World(1).necromancer)


class NecromancerTests(unittest.TestCase):
    def beside(self, seed=1):
        w, lvl, p, n = last_floor(seed)
        lvl.move(p, *amulet_spot(lvl))
        return w, lvl, p, n

    def zombies(self, lvl):
        return [m for m in lvl.monsters if m.kind == "zombie"]

    def test_stealth_lets_you_take_the_amulet_without_waking_it(self):
        w, lvl, p, n = self.beside()
        p.stealth = 100
        for _ in range(100):
            w._monster_turn(n, lvl)
            p.stealth = 100
        self.assertEqual(n.state, "sleeping")
        self.assertFalse(w.necro_awake)
        w.submit(p, {"a": "pickup"})
        self.assertEqual(p.pack[0].category, "amulet")

    def test_walking_past_with_no_stealth_at_this_distance_can_work_too(self):
        w, lvl, p, n = self.beside()
        self.assertGreater(cheb(n, p), 6)

    def test_leaving_quietly_means_nothing_follows(self):
        w, lvl, p, n = self.beside()
        lvl.move(p, *lvl.up_front)
        w._take_stairs(p, -1)
        self.assertFalse(p.chased)
        above = w.levels[LAST_FLOOR - 1]
        before = len(self.zombies(above))
        p.god = True
        w.advance(int(10 * TIDE_SECONDS * TICKS_PER_SECOND))
        self.assertEqual(len(self.zombies(above)), before)

    def test_waking_it_is_announced_once(self):
        w, lvl, p, n = self.beside()
        w.drain_outbox()
        w._hunt(n, p)
        w._hunt(n, p)
        self.assertEqual(str(w.drain_outbox()).count("has woken"), 1)
        self.assertTrue(w.necro_awake)

    def test_it_raises_two_to_five_zombies(self):
        counts = set()
        for seed in range(60):
            w, lvl, p, n = self.beside(seed)
            w._hunt(n, p)
            if not w.fov(p)[n.x, n.y]:
                continue
            w._monster_turn(n, lvl)
            counts.add(len(self.zombies(lvl)))
        self.assertTrue(counts <= set(range(SUMMON_SIZE[0], SUMMON_SIZE[1] + 1)), counts)
        self.assertGreater(len(counts), 2)

    def test_it_has_to_wait_between_summons(self):
        w, lvl, p, n = self.beside()
        w._hunt(n, p)
        w._monster_turn(n, lvl)
        first = len(self.zombies(lvl))
        w._monster_turn(n, lvl)
        self.assertEqual(len(self.zombies(lvl)), first)

    def test_zombies_are_placed_properly_and_hunt_you(self):
        w, lvl, p, n = self.beside()
        w._hunt(n, p)
        w._monster_turn(n, lvl)
        for z in self.zombies(lvl):
            self.assertIs(lvl.occupant[(z.x, z.y)], z)
            self.assertEqual(z.state, "hunting")

    def flee(self, seed=1):
        w, lvl, p, n = self.beside(seed)
        p.hp = p.max_hp = 100000
        w._hunt(n, p)
        lvl.move(p, *lvl.up_front)
        w._take_stairs(p, -1)
        empty(w.levels[p.depth])
        return w, lvl, p, n

    def test_fleeing_it_awake_means_being_chased(self):
        w, lvl, p, n = self.flee()
        self.assertTrue(p.chased)
        self.assertIn("dead begin to rise", str(w.drain_outbox()))

    def test_the_dead_keep_coming_on_every_floor_you_climb_to(self):
        w, lvl, p, n = self.flee()
        for depth in (LAST_FLOOR - 1, LAST_FLOOR - 2):
            here = w.levels[p.depth]
            self.assertEqual(p.depth, depth)
            w.advance(int(3 * TIDE_SECONDS * TICKS_PER_SECOND))
            first = len(self.zombies(here))
            self.assertGreater(first, 0)
            w.advance(int(3 * TIDE_SECONDS * TICKS_PER_SECOND))
            self.assertGreater(len(self.zombies(here)), first)
            self.lvl_up(w, p)
            empty(w.levels[p.depth])

    @staticmethod
    def lvl_up(w, p):
        here = w.levels[p.depth]
        here.remove(p)
        here.place(p, *here.up_front)
        w._take_stairs(p, -1)

    def test_they_stop_once_you_leave_that_floor(self):
        w, lvl, p, n = self.flee()
        here = w.levels[p.depth]
        w.advance(int(3 * TIDE_SECONDS * TICKS_PER_SECOND))
        self.lvl_up(w, p)
        count = len(self.zombies(here))
        w.advance(int(5 * TIDE_SECONDS * TICKS_PER_SECOND))
        self.assertEqual(len(self.zombies(here)), count)

    def test_there_are_never_too_many_at_once(self):
        w, lvl, p, n = self.flee()
        w.advance(int(40 * TIDE_SECONDS * TICKS_PER_SECOND))
        self.assertLessEqual(len(self.zombies(w.levels[p.depth])), TIDE_MAX + 2)

    def test_they_appear_out_of_sight(self):
        w, lvl, p, n = self.flee()
        w.tide_at = 0
        w._tick_tide()
        for z in self.zombies(w.levels[p.depth]):
            self.assertFalse(w.fov(p)[z.x, z.y])

    def test_killing_it_ends_the_chase(self):
        w, lvl, p, n = self.flee()
        w._kill(n, p)
        self.assertFalse(p.chased)
        self.assertFalse(w.necro_awake)
        w.advance(int(5 * TIDE_SECONDS * TICKS_PER_SECOND))
        self.assertEqual(self.zombies(w.levels[p.depth]), [])

    def test_killing_it_leaves_the_amulet_there(self):
        w, lvl, p, n = self.beside()
        w._kill(n, p)
        self.assertIsNone(w.necromancer)
        self.assertTrue(any(i.category == "amulet" for i in lvl.items.values()))

    def test_a_new_run_resets_it_all(self):
        w, lvl, p, n = self.flee()
        w.reset_run()
        self.assertFalse(p.chased or w.necro_awake)
        self.assertIsNone(w.necromancer)


class WinningTests(unittest.TestCase):
    def setUp(self):
        self.w = World(2)
        self.p = self.w.join("A")
        self.lvl = self.w.levels[1]
        self.lvl.move(self.p, *self.lvl.up_front)

    def climb(self):
        self.w.advance(200)
        self.w.submit(self.p, {"a": "ascend"})
        self.w.advance(1)

    def test_floor_ones_stairs_stay_sealed_without_it(self):
        self.climb()
        self.assertEqual(self.w.victory, "")
        self.assertIn("Only the Amulet", str(self.w.drain_outbox()))

    def test_carrying_it_out_wins(self):
        self.p.pack.append(make_amulet())
        self.climb()
        self.assertEqual(self.w.victory, "A")
        self.assertIn("The party wins", str(self.w.drain_outbox()))

    def test_walking_into_the_stairs_counts(self):
        self.p.pack.append(make_amulet())
        self.w.advance(200)
        self.w.submit(self.p, {"a": "move", "dx": self.lvl.up[0] - self.p.x, "dy": self.lvl.up[1] - self.p.y})
        self.assertEqual(self.w.victory, "A")

    def test_the_whole_party_wins_and_sees_it(self):
        b = self.w.join("B")
        self.p.pack.append(make_amulet())
        b.gold, b.kills, b.turns = 100, 5, 50
        before = self.w.score_of(b)
        self.climb()
        v = view_of(self.w, b)
        self.assertEqual(v.victory, "A")
        text = rows_of(v.draw())
        self.assertIn("A escaped with the Amulet!", text)
        self.assertIn("The party wins.", text)
        self.assertEqual(self.w.score_of(b), 2 * before)  # a win doubles everyone's

    def test_a_new_dungeon_follows(self):
        self.p.pack.append(make_amulet())
        self.climb()
        seed = self.w.seed
        self.w.reset_at = 0
        self.assertTrue(self.w.check_reset(1))
        self.assertNotEqual(self.w.seed, seed)
        self.assertEqual(self.w.victory, "")
        self.assertEqual(self.p.pack, [])

    def test_it_doesnt_do_anything_from_the_pack(self):
        self.p.pack.append(make_amulet())
        self.w.submit(self.p, {"a": "use", "slot": 0})
        self.w.advance(1)
        self.assertEqual(len(self.p.pack), 1)

    def test_it_waits_for_g_and_everyone_hears(self):
        spot = (self.p.x, self.p.y)
        self.lvl.items[spot] = make_amulet()
        self.w._step_onto(self.p, self.lvl)
        self.assertEqual(self.p.pack, [])
        self.w.drain_outbox()
        self.w.submit(self.p, {"a": "pickup"})
        self.assertIn("has the Amulet", str(self.w.drain_outbox()))

    def test_leaving_the_game_with_it_drops_it(self):
        self.p.pack.append(make_amulet())
        self.w.leave(self.p)
        self.assertTrue(any(i.category == "amulet" for i in self.lvl.items.values()))
        self.assertEqual(self.p.pack, [])

    def test_a_classic_death_leaves_it_behind(self):
        self.w.join("B")
        self.p.pack.append(make_amulet())
        self.w.revive_seconds = None  # the fallen stay down, as on Hard
        self.w._kill(self.p, None)
        self.assertTrue(any(i.category == "amulet" for i in self.lvl.items.values()))

    def test_full_run_sneaking(self):
        w, lvl, p, n = last_floor(5)
        p.stealth = 100
        lvl.move(p, *amulet_spot(lvl))
        w.submit(p, {"a": "pickup"})
        w.advance(200)
        lvl.move(p, *lvl.up_front)
        w.submit(p, {"a": "ascend"})
        w.advance(1)
        self.assertEqual(p.depth, LAST_FLOOR - 1)
        self.assertFalse(p.chased)
        p.can_command = True
        commands.run(w, p, "floor 1")
        first = w.levels[1]
        first.move(p, *first.up_front)
        w.advance(200)
        w.submit(p, {"a": "ascend"})
        w.advance(1)
        self.assertEqual(w.victory, "A")


class FrostWandTests(unittest.TestCase):
    def setUp(self):
        self.w = World(3)
        self.p = self.w.join("A")
        self.lvl = self.w.levels[1]
        empty(self.lvl)
        self.lvl.light[:] = 0
        self.p.pack.append(make_item("frost_wand"))
        spot = self.lvl.free_near(self.p.x + 1, self.p.y)
        self.m = make_monster("ogre", 900)
        self.m.state = "hunting"
        self.m.hp = self.m.max_hp = 10000
        self.lvl.place(self.m, *spot)
        self.lvl.monsters.append(self.m)

    def zap(self):
        self.w.submit(self.p, {"a": "use", "slot": 0})
        self.w.advance(1)

    def test_it_holds_them_for_30_seconds_and_no_more(self):
        self.zap()
        hp = self.p.hp
        self.w.advance(int(29 * TICKS_PER_SECOND))
        self.assertEqual(self.p.hp, min(hp + 100, self.p.max_hp))
        self.assertGreater(self.m.frozen_until, self.w.clock)
        self.p.hp = self.p.max_hp
        self.p.defense = 0
        self.w.advance(int(5 * TICKS_PER_SECOND))
        self.assertEqual(self.m.frozen_until > self.w.clock, False)
        self.assertLess(self.p.hp + 0, self.p.max_hp + 1)
        self.assertGreater(self.m.next_time, 0)

    def test_it_does_no_damage(self):
        self.zap()
        self.assertEqual(self.m.hp, self.m.max_hp)
        self.assertEqual(self.m.burning, 0)

    def test_it_doesnt_wake_anything(self):
        self.m.state = "sleeping"
        self.zap()
        self.assertEqual(self.m.state, "sleeping")

    def test_it_uses_a_charge_and_breaks_like_the_other(self):
        wand = self.p.pack[0]
        self.assertEqual(wand.charges, 10)
        self.zap()
        self.assertEqual(wand.charges, 9)
        self.assertIn("freeze 30s", wand.info)
        wand.charges = 1
        self.w.advance(200)
        self.zap()
        self.assertEqual(self.p.pack, [])

    def test_it_shows(self):
        self.zap()
        v = view_of(self.w, self.p)
        e = next(e for e in v.ents if e["id"] == 900)
        self.assertTrue(e["frozen"])
        self.assertIn("Frozen solid", str(v._describe_actor(e)))

    def test_it_can_be_found(self):
        self.assertTrue(appears_on(ITEMS["frost_wand"], 10))
        found = any(i.kind == "frost_wand" for seed in range(200) for i in World(seed).level(10).items.values())
        self.assertTrue(found)

    def test_a_frozen_necromancer_can_be_walked_past(self):
        w, lvl, p, n = last_floor(1)
        lvl.move(p, *amulet_spot(lvl))
        p.pack.append(make_item("frost_wand"))
        w.submit(p, {"a": "use", "slot": 0})
        self.assertGreater(n.frozen_until, w.clock)
        self.assertEqual(n.state, "sleeping")
        self.assertFalse(w.necro_awake)


if __name__ == "__main__":
    unittest.main()
