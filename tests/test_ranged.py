"""Bows, boomerangs and what they aim at, and the tower's monsters and treasure."""
import unittest
from unittest import mock

import client
import togetherogue
from game import commands, settings
from game.constants import ARROW_PILE, HOARD_PILES, LAST_FLOOR, POTION_ROOM, TOWER_FIRST
from game.entities import make_monster
from game.items import AUTO_PICKUP, ITEMS, make_item
from game.render import SPIN, SPIN_TILE_SECONDS, SPIN_TURN_SECONDS, ClientView
from game.world import World
from server import GameServer


def player(seed=3):
    w = World(seed)
    lvl = w.level(1)
    for m in list(lvl.monsters):
        lvl.remove(m)
    lvl.monsters.clear()
    lvl.items.clear()
    p = w.join("A")
    lvl.items.clear()
    return w, lvl, p


def monster(w, lvl, p, kind, gap, hp=100000, state="hunting"):
    sight = w.fov(p)
    spot = next(c for c in lvl.land_cells if sight[c] and c not in lvl.occupant
                and max(abs(c[0] - p.x), abs(c[1] - p.y)) == gap)
    m = make_monster(kind, 900 + len(lvl.monsters))
    m.hp = m.max_hp = hp
    m.state, m.next_time = state, 10 ** 9
    lvl.place(m, *spot)
    lvl.monsters.append(m)
    return m


def fire(w, p, item):
    p.pack.insert(0, item)
    w.advance(300)
    w.submit(p, {"a": "use", "slot": 0})
    w.advance(1)


class SpawnTests(unittest.TestCase):
    def found(self, depths, seeds=60):
        kinds = {}
        for seed in range(seeds):
            w = World(seed)
            for depth in depths:
                for item in w.level(depth).items.values():
                    kinds.setdefault(item.kind, []).append(item)
        return kinds

    def test_they_turn_up_shallow_and_deep(self):
        for depth in (3, 15, 60):
            kinds = self.found([depth])
            self.assertIn("bow", kinds, depth)
            self.assertIn("arrows", kinds, depth)
            self.assertIn("boomerang", kinds, depth)

    def test_arrows_come_in_piles(self):
        piles = self.found([3, 4])["arrows"]
        self.assertGreater(len(piles), 3)
        for pile in piles:
            self.assertTrue(ARROW_PILE[0] <= pile.count <= ARROW_PILE[1])
            self.assertIn("x", pile.label)

    def test_merchants_dont_sell_them(self):
        for seed in range(30):
            lvl = World(seed).level(5)
            if lvl.merchant:
                self.assertFalse(any(i.category in ("ranged", "ammo") for i in lvl.merchant.stock.values()))

    def test_arrows_are_picked_up_by_walking_and_stack(self):
        w, lvl, p = player()
        self.assertIn("ammo", AUTO_PICKUP)
        pile = make_item("arrows")
        pile.count = 20
        lvl.items[(p.x, p.y)] = pile
        w._step_onto(p, lvl)
        more = make_item("arrows")
        more.count = 5
        lvl.items[(p.x, p.y)] = more
        w._step_onto(p, lvl)
        self.assertEqual([(i.kind, i.count) for i in p.pack], [("arrows", 25)])

    def test_bows_wait_for_g(self):
        w, lvl, p = player()
        lvl.items[(p.x, p.y)] = make_item("bow")
        w._step_onto(p, lvl)
        self.assertEqual(p.pack, [])

    def test_the_console_can_give_them(self):
        w, lvl, p = player()
        p.can_command = True
        commands.run(w, p, "give bow")
        commands.run(w, p, "give arrow 25")
        commands.run(w, p, "give boom")
        self.assertEqual(sorted((i.kind, i.count) for i in p.pack), [("arrows", 25), ("boomerang", 1), ("bow", 1)])

    def test_they_say_what_they_do(self):
        self.assertEqual(make_item("bow").info, "dmg 4-8, range 12, uses arrows")
        self.assertEqual(make_item("boomerang").info, "dmg 3-6, range 9, comes back")


class BowTests(unittest.TestCase):
    def setUp(self):
        self.w, self.lvl, self.p = player()
        pile = make_item("arrows")
        pile.count = 2
        self.p.pack.append(pile)
        self.pile = pile

    def test_it_uses_an_arrow_and_hits(self):
        m = monster(self.w, self.lvl, self.p, "ogre", 3)
        self.p.accuracy = 100000
        fire(self.w, self.p, make_item("bow"))
        self.assertEqual(self.pile.count, 1)
        self.assertLess(m.hp, m.max_hp)
        self.assertEqual(m.state, "hunting")

    def test_no_arrows_no_shot(self):
        m = monster(self.w, self.lvl, self.p, "ogre", 3)
        self.p.pack.clear()
        fire(self.w, self.p, make_item("bow"))
        self.assertEqual(m.hp, m.max_hp)
        self.assertEqual(self.p.turns, 0)
        self.assertIn("no arrows", str(self.w.drain_outbox()))

    def test_no_target_keeps_the_arrow(self):
        fire(self.w, self.p, make_item("bow"))
        self.assertEqual(self.pile.count, 2)
        self.assertEqual(self.p.turns, 0)

    def test_the_last_arrow_goes(self):
        monster(self.w, self.lvl, self.p, "ogre", 3)
        self.pile.count = 1
        bow = make_item("bow")
        fire(self.w, self.p, bow)
        self.assertEqual(self.p.pack, [bow])

    def test_it_can_miss(self):
        m = monster(self.w, self.lvl, self.p, "ogre", 3)
        self.p.accuracy = 0
        fire(self.w, self.p, make_item("bow"))
        self.assertEqual(m.hp, m.max_hp)
        self.assertEqual(self.pile.count, 1)

    def test_a_kill_counts(self):
        monster(self.w, self.lvl, self.p, "rat", 3, hp=1)
        self.p.accuracy = 100000
        fire(self.w, self.p, make_item("bow"))
        self.assertEqual(self.p.kills, 1)

    def test_a_sneak_shot_does_triple(self):
        m = monster(self.w, self.lvl, self.p, "ogre", 3, state="sleeping")
        fire(self.w, self.p, make_item("bow"))
        self.assertGreaterEqual(m.max_hp - m.hp, 12)
        self.assertEqual(m.state, "hunting")

    def test_shots_show(self):
        m = monster(self.w, self.lvl, self.p, "ogre", 3)
        self.w.drain_outbox()
        fire(self.w, self.p, make_item("bow"))
        fx = [msg for _, msg in self.w.drain_outbox() if msg["t"] == "fx"]
        self.assertEqual(fx[0]["kind"], "bow")
        self.assertEqual(tuple(fx[0]["cells"][-1]), (m.x, m.y))


class BoomerangTests(unittest.TestCase):
    def setUp(self):
        self.w, self.lvl, self.p = player()

    def test_a_range_of_9(self):
        self.assertEqual(ITEMS["boomerang"]["reach"], 9)
        with mock.patch.object(self.w, "fov", return_value=__import__("numpy").ones((79, 29), bool)):
            near = make_monster("ogre", 901)
            far = make_monster("ogre", 902)
            near.state = far.state = "hunting"
            near.x, near.y, far.x, far.y = self.p.x + 9, self.p.y, self.p.x + 10, self.p.y
            self.lvl.monsters.extend([far])
            self.assertIsNone(self.w._target(self.p, self.lvl, 9))
            self.lvl.monsters.append(near)
            self.assertIs(self.w._target(self.p, self.lvl, 9), near)

    def test_it_comes_back(self):
        monster(self.w, self.lvl, self.p, "ogre", 3)
        boomerang = make_item("boomerang")
        fire(self.w, self.p, boomerang)
        self.assertIn(boomerang, self.p.pack)
        self.assertEqual(self.p.turns, 1)


class SpinTests(unittest.TestCase):
    def thrown(self):
        w, lvl, p = player()
        m = monster(w, lvl, p, "ogre", 5)
        v = ClientView()
        v.apply({"t": "welcome", "id": p.id, "name": p.name})
        v.apply(w.level_msg(1))
        v.apply(w.state_for(p))
        w.drain_outbox()
        fire(w, p, make_item("boomerang"))
        for _, msg in w.drain_outbox():
            v.apply(msg)
        return v, m

    def at(self, v, seconds):
        """What a flying boomerang looks like this long after it was thrown: (x, y, glyph)."""
        cells, thrown = v.throws[0]
        with mock.patch("game.render.time.monotonic", return_value=thrown + seconds):
            frame = v.draw()
        found = [(x, y, chr(frame["ch"][21 + x, 3 + y])) for x, y in cells if chr(frame["ch"][21 + x, 3 + y]) in SPIN]
        return found

    def test_it_makes_no_flash(self):
        v, m = self.thrown()
        self.assertEqual(v.bolts, [])
        self.assertEqual(len(v.throws), 1)

    def test_it_leaves_the_player_and_reaches_the_monster(self):
        v, m = self.thrown()
        cells = v.throws[0][0]
        self.assertEqual(self.at(v, 0)[0][:2], tuple(cells[0]))
        self.assertEqual(tuple(cells[-1]), (m.x, m.y))
        self.assertEqual(self.at(v, (len(cells) - 0.5) * SPIN_TILE_SECONDS)[0][:2], tuple(cells[-1]))

    def test_only_one_tile_shows_at_a_time(self):
        v, m = self.thrown()
        for i in range(len(v.throws[0][0])):
            self.assertEqual(len(self.at(v, (i + 0.5) * SPIN_TILE_SECONDS)), 1, i)

    def test_it_spins_through_all_four_glyphs_in_order(self):
        v, m = self.thrown()
        cells = v.throws[0][0]
        self.assertEqual(SPIN, "/-\\|")
        seen = []
        for i in range(int(len(cells) * SPIN_TILE_SECONDS / SPIN_TURN_SECONDS)):
            seen.append(self.at(v, (i + 0.5) * SPIN_TURN_SECONDS)[0][2])
        self.assertEqual(seen, [SPIN[i % 4] for i in range(len(seen))])
        self.assertEqual(len(set(seen)), 4)

    def test_it_is_gone_after_it_lands(self):
        v, m = self.thrown()
        cells, thrown = v.throws[0]
        with mock.patch("game.render.time.monotonic", return_value=thrown + len(cells) * SPIN_TILE_SECONDS + 0.01):
            v.draw()
        self.assertEqual(v.throws, [])

    def test_the_bow_still_flashes(self):
        v = ClientView()
        v.apply({"t": "fx", "kind": "bow", "cells": [(1, 1)]})
        self.assertEqual((len(v.bolts), v.throws), (1, []))


class AimTests(unittest.TestCase):
    def setUp(self):
        self.w, self.lvl, self.p = player()

    def spread(self):
        return (monster(self.w, self.lvl, self.p, "rat", 1), monster(self.w, self.lvl, self.p, "ogre", 3),
                monster(self.w, self.lvl, self.p, "goblin", 2))

    def test_strongest_by_default(self):
        rat, ogre, goblin = self.spread()
        self.assertEqual(settings.DEFAULTS["ranged_target"], "Strongest")
        self.assertIs(self.w._target(self.p, self.lvl, 12), ogre)

    def test_weakest_when_chosen(self):
        rat, ogre, goblin = self.spread()
        self.p.aim = "Weakest"
        self.assertIs(self.w._target(self.p, self.lvl, 12), rat)

    def test_those_fighting_come_before_those_that_arent(self):
        ogre = monster(self.w, self.lvl, self.p, "ogre", 3, state="sleeping")
        rat = monster(self.w, self.lvl, self.p, "rat", 2)
        self.assertIs(self.w._target(self.p, self.lvl, 12), rat)
        self.assertIsNot(ogre, rat)

    def test_equals_go_nearest_first(self):
        far = monster(self.w, self.lvl, self.p, "rat", 3)
        near = monster(self.w, self.lvl, self.p, "rat", 1)
        self.assertIs(self.w._target(self.p, self.lvl, 12), near)
        self.assertIsNot(far, near)

    def test_wands_aim_the_same_way(self):
        rat, ogre, goblin = self.spread()
        fire(self.w, self.p, make_item("frost_wand"))
        self.assertGreater(ogre.frozen_until, 0)
        self.assertEqual(rat.frozen_until, 0)

    def test_sleepers_can_still_be_targeted(self):
        ogre = monster(self.w, self.lvl, self.p, "ogre", 3, state="sleeping")
        self.assertIs(self.w._target(self.p, self.lvl, 12), ogre)


class FakeContext:
    def present(self, console, keep_aspect=True):
        pass


class OptionTests(unittest.TestCase):
    def app(self, aim="Strongest"):
        return togetherogue.App(FakeContext(), client.new_console(), dict(settings.DEFAULTS, ranged_target=aim))

    def test_it_is_in_the_options(self):
        app = self.app()
        with mock.patch("togetherogue.settings.save"):
            forms = []
            app.show = lambda form, extra=None, timeout=None: (forms.append(form), "back")[1]
            app.options()
        row = next(r for r in forms[0].rows if r.key == "ranged_target")
        self.assertEqual(row.choices, ("Strongest", "Weakest"))

    def test_saving_it_sticks(self):
        app = self.app()

        def show(form, extra=None, timeout=None):
            next(r for r in form.rows if r.key == "ranged_target").value = "Weakest"
            return "save"
        app.show = show
        with mock.patch("togetherogue.settings.save"):
            app.options()
        self.assertEqual(app.config["ranged_target"], "Weakest")

    def test_it_reaches_the_server(self):
        self.assertEqual(self.app("Weakest").look()["aim"], "Weakest")

    def test_the_server_keeps_it_and_ignores_nonsense(self):
        import asyncio
        import socket
        import threading
        from game import protocol
        for sent, expected in (("Weakest", "Weakest"), ("Banana", "Strongest"), (None, "Strongest")):
            loop = asyncio.new_event_loop()
            world = World(seed=3)
            server = loop.run_until_complete(GameServer(world).start("127.0.0.1", 0))
            port = server.sockets[0].getsockname()[1]
            thread = threading.Thread(target=loop.run_forever, daemon=True)
            thread.start()
            sock = socket.create_connection(("127.0.0.1", port), timeout=5)
            file = sock.makefile("r", encoding="utf-8")
            sock.sendall(protocol.encode({"t": "hello", "name": "A", "aim": sent}))
            while protocol.decode(file.readline()).get("t") != "state":
                pass
            self.assertEqual(next(iter(world.players.values())).aim, expected)
            file.close()
            sock.close()

            async def shutdown():
                server.close()
                for task in asyncio.all_tasks():
                    if task is not asyncio.current_task():
                        task.cancel()
                await asyncio.sleep(0.05)
            asyncio.run_coroutine_threadsafe(shutdown(), loop).result(5)
            loop.call_soon_threadsafe(loop.stop)


class TowerMonsterTests(unittest.TestCase):
    def test_no_ogres_or_mushrooms_anywhere_in_the_tower(self):
        for seed in range(12):
            w = World(seed)
            for depth in range(TOWER_FIRST, LAST_FLOOR + 1):
                kinds = {m.kind for m in w.level(depth).monsters}
                self.assertFalse(kinds & {"ogre", "mushroom"}, (seed, depth))

    def test_they_arent_left_empty(self):
        for depth in range(TOWER_FIRST, LAST_FLOOR):
            self.assertTrue(World(1).level(depth).monsters, depth)

    def test_the_floors_above_still_have_them(self):
        kinds = {m.kind for seed in range(10) for m in World(seed).level(45).monsters}
        self.assertLessEqual({"ogre", "mushroom"}, kinds)


class LairTreasureTests(unittest.TestCase):
    def floor(self, seed):
        w = World(seed)
        return w, w.level(LAST_FLOOR)

    def test_four_side_rooms_of_real_floor(self):
        w, lvl = self.floor(1)
        self.assertEqual(len(lvl.side_rooms), 4)
        for room in lvl.side_rooms:
            self.assertGreater(len(room), 20)
            self.assertTrue(all(lvl.mainland[c] for c in room))

    def test_one_holds_a_hoard_and_one_holds_potions(self):
        for seed in range(15):
            w, lvl = self.floor(seed)
            contents = [[lvl.items[c] for c in room if c in lvl.items] for room in lvl.side_rooms]
            gold = [[i for i in r if i.category == "gold"] for r in contents]
            hoard = [r for r in gold if len(r) >= HOARD_PILES - 2]         # ordinary items can lie here too
            potions = [r for r in contents if sum(i.category == "potion" for i in r) >= POTION_ROOM - 2]
            self.assertEqual((len(hoard), len(potions)), (1, 1), seed)
            self.assertGreater(sum(i.count for i in hoard[0]), 3000)

    def test_the_amulet_is_away_from_the_doors_and_stairs(self):
        for seed in range(40):
            w, lvl = self.floor(seed)
            spot = next(c for c, i in lvl.items.items() if i.category == "amulet")
            self.assertGreaterEqual(lvl.distances_to(*lvl.up_front)[spot] // 2, 20, seed)
            for door in map(tuple, __import__("numpy").argwhere(lvl.is_door)):
                self.assertGreaterEqual(lvl.distances_to(int(door[0]), int(door[1]))[spot] // 2, 15, seed)


if __name__ == "__main__":
    unittest.main()
