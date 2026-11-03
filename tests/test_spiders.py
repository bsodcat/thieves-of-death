"""The giant spider queen, her brood, their webs and venom, and things that fly instead of flashing."""
import unittest
from unittest import mock

from game.constants import (LEAP_RETREAT, MAP_X, MAP_Y, SLOW_FACTOR, SPIDER_BROOD, SPIDER_FLOORS, TICKS_PER_SECOND,
                            VENOM_MOST, WEB_FACTOR, WEB_SPIT_RANGE)
from game.items import make_item
from game.render import FLIGHTS, WEB_GLYPH, ClientView
from game.world import World, cheb
from helpers_210 import add, deliver, empty_world, open_spot, put, said, seconds, view_of


def nests(seeds=range(8), floors=range(1, 45)):
    """(world, level) for every floor with a spider queen."""
    for seed in seeds:
        w = World(seed)
        for depth in floors:
            lvl = w.level(depth)
            if any(m.kind == "spider_queen" for m in lvl.monsters):
                yield w, lvl


class NestTests(unittest.TestCase):
    def test_a_queen_and_her_brood_in_a_cave_among_webs(self):
        found = 0
        for w, lvl in nests():
            found += 1
            self.assertTrue(SPIDER_FLOORS[0] <= lvl.depth <= SPIDER_FLOORS[1])
            self.assertIsNotNone(lvl.cave)
            queen = next(m for m in lvl.monsters if m.kind == "spider_queen")
            brood = [m for m in lvl.monsters if m.kind == "spider" and m.leader is queen]
            self.assertTrue(SPIDER_BROOD[0] <= len(brood) <= SPIDER_BROOD[1], (w.seed, lvl.depth))
            self.assertTrue(lvl.cave[queen.x, queen.y])
            self.assertTrue(lvl.webs)
            self.assertTrue(all(lvl.cave[c] for c in lvl.webs))
            self.assertEqual(sum(m.kind == "spider_queen" for m in lvl.monsters), 1)
        self.assertGreater(found, 3)

    def test_the_console_can_add_one(self):
        from game import commands
        w, lvl, p = empty_world()
        p.can_command = True
        commands.run(w, p, "spawn nest")
        self.assertTrue(any(m.kind == "spider_queen" for m in lvl.monsters) or "no room" in str(w.drain_outbox()))


class SpiderFight(unittest.TestCase):
    def setUp(self):
        self.w, self.lvl, self.p = empty_world()
        self.x, self.y = open_spot(self.lvl, reach=5)
        put(self.lvl, self.p, self.x, self.y)
        self.p.hp = self.p.max_hp = 200

    def turn(self, m):
        self.w.drain_outbox()
        cost = self.w._monster_turn(m, self.lvl)
        return cost, [msg for _, msg in self.w.drain_outbox()]


class WebTests(SpiderFight):
    def test_walking_into_a_web_slows_you(self):
        self.lvl.webs.add((self.x + 1, self.y))
        self.w.submit(self.p, {"a": "move", "dx": 1, "dy": 0})
        self.assertGreater(self.p.slow_until, self.w.clock)
        self.assertIn("web", said(self.w))
        self.assertEqual(self.w._stride(self.p), self.p.move_cost * SLOW_FACTOR)

    def test_fire_burns_them_away(self):
        self.lvl.webs.add((self.x + 1, self.y))
        self.w._start_fire(self.lvl, self.x + 1, self.y, None)
        self.w.advance(seconds(0.2))
        self.assertNotIn((self.x + 1, self.y), self.lvl.webs)
        self.assertIn("webs", [m["t"] for _, m in self.w.drain_outbox()])

    def test_you_see_them_and_remember_them(self):
        self.lvl.webs.add((self.x + 1, self.y))
        v = view_of(self.w, self.p)
        frame = v.draw()
        self.assertEqual(frame["ch"][MAP_X + self.x + 1, MAP_Y + self.y], WEB_GLYPH)
        self.assertEqual(v.describe(self.x + 1, self.y)[0][0], ":" + " Spider web")


class QueenTests(SpiderFight):
    def test_close_by_she_bites(self):
        q = add(self.w, self.lvl, "spider_queen", self.x + 1, self.y, target=self.p)
        with mock.patch.object(self.w.rng, "random", return_value=0.0):
            self.turn(q)
        self.assertLess(self.p.hp, self.p.max_hp)
        self.assertGreater(self.p.venom_until, self.w.clock)

    def test_run_more_than_five_tiles_and_she_spits_web(self):
        x, y = self.x, self.y
        self.lvl.move(self.p, x - 3, y)
        q = add(self.w, self.lvl, "spider_queen", x + 3, y, target=self.p)  # 6 tiles off
        self.assertGreater(cheb(q, self.p), WEB_SPIT_RANGE)
        with mock.patch.object(self.w.rng, "random", return_value=0.0):
            _, out = self.turn(q)
        self.assertIn("web", [m.get("kind") for m in out if m["t"] == "fx"])
        self.assertGreater(self.p.webbed_until, self.w.clock)
        self.assertEqual(self.w._stride(self.p), self.p.move_cost * WEB_FACTOR)  # slower than a web underfoot
        self.assertIn((self.p.x, self.p.y), self.lvl.webs)
        self.assertTrue(self.w.state_for(self.p)["webbed"])

    def test_within_five_tiles_she_comes_for_you_instead(self):
        q = add(self.w, self.lvl, "spider_queen", self.x + 4, self.y, target=self.p)
        _, out = self.turn(q)
        self.assertNotIn("web", [m.get("kind") for m in out if m["t"] == "fx"])
        self.assertEqual(cheb(q, self.p), 3)


class LeapTests(SpiderFight):
    def test_it_leaps_bites_and_backs_off(self):
        s = add(self.w, self.lvl, "spider", self.x + 3, self.y, target=self.p)
        with mock.patch.object(self.w.rng, "random", return_value=0.0):
            _, out = self.turn(s)
        self.assertEqual(cheb(s, self.p), 1)  # landed right beside you
        self.assertIn("leap", [m.get("kind") for m in out if m["t"] == "fx"])
        self.assertLess(self.p.hp, self.p.max_hp)
        for _ in range(LEAP_RETREAT):
            self.turn(s)
        self.assertGreater(cheb(s, self.p), 1)  # and backed away again
        _, out = self.turn(s)
        self.assertNotIn("leap", [m.get("kind") for m in out if m["t"] == "fx"])  # not ready to leap yet


class VenomTests(SpiderFight):
    def test_it_adds_up_to_forty_seconds(self):
        for _ in range(10):
            self.w._envenom(self.p)
        self.assertEqual(self.p.venom_until - self.w.clock, int(VENOM_MOST * TICKS_PER_SECOND))

    def test_it_never_kills(self):
        self.p.hp = 4
        for _ in range(4):
            self.w._envenom(self.p)
        self.w.advance(seconds(VENOM_MOST + 1))
        self.assertTrue(self.p.alive)
        self.assertEqual(self.p.hp, 1)

    def test_it_stops_healing_and_shows(self):
        self.w.regen = True
        self.p.hp = 50
        self.w._envenom(self.p)
        self.w.advance(seconds(5))
        self.assertLess(self.p.hp, 50)
        state = self.w.state_for(self.p)
        self.assertTrue(state["toxin"])
        self.assertGreater(state["venom"], 0)
        v = view_of(self.w, self.p)
        frame = v.draw()
        sidebar = " ".join("".join(chr(c) for c in frame["ch"][:20, y]) for y in range(frame.shape[1]))
        self.assertIn("Venom", sidebar)

    def test_death_clears_it(self):
        self.w._envenom(self.p)
        self.w.revive_seconds = None
        self.w._kill(self.p, None, "test")
        self.assertEqual(self.p.venom_until, 0)


class FlightTests(unittest.TestCase):
    def setUp(self):
        self.w, self.lvl, self.p = empty_world()
        self.x, self.y = open_spot(self.lvl, reach=5)
        put(self.lvl, self.p, self.x, self.y)

    def flights(self, out):
        v = ClientView()
        for msg in out:
            v.apply(msg)
        return v

    def test_arrows_point_the_way_they_fly(self):
        self.assertEqual(ClientView.arrow((0, 0), [(1, 0), (2, 0), (5, 1)]), "-")
        self.assertEqual(ClientView.arrow((0, 0), [(0, 3)]), "|")
        self.assertEqual(ClientView.arrow((0, 0), [(3, 3)]), "\\")
        self.assertEqual(ClientView.arrow((0, 3), [(3, 0)]), "/")

    def test_an_archers_arrow_flies_to_you(self):
        a = add(self.w, self.lvl, "skeleton_archer", self.x + 4, self.y, target=self.p)
        self.lvl.move(self.p, self.x - 3, self.y)  # at bowshot
        a.ready_at = 0
        v = view_of(self.w, self.p)
        self.w._archer(a, self.lvl, self.p)
        deliver(self.w, v, self.p.id)
        self.assertEqual(len(v.flights), 1)
        cells, thrown, glyph, color, pace, fell = v.flights[0]
        self.assertEqual(glyph, "-")
        self.assertEqual(cells[-1], (self.p.x, self.p.y))
        self.assertGreaterEqual(len(cells), 6)
        for i, cell in enumerate(cells):
            with mock.patch("game.render.time.monotonic", return_value=thrown + (i + 0.5) * pace):
                frame = v.draw()
            self.assertEqual(chr(frame["ch"][MAP_X + cell[0], MAP_Y + cell[1]]), "-")

    def test_rocks_and_fireballs_and_webs_fly_too(self):
        for kind in ("rock", "fireball", "web"):
            v = ClientView()
            v.apply({"t": "fx", "kind": kind, "cells": [[1, 1], [2, 1]], "from": [0, 1]})
            self.assertEqual((len(v.flights), v.bolts), (1, []), kind)
            self.assertEqual(v.flights[0][2], FLIGHTS[kind][0])

    def test_magic_still_flashes(self):
        for kind in ("fire", "lightning", "frost", "blink"):
            v = ClientView()
            v.apply({"t": "fx", "kind": kind, "cells": [[1, 1]]})
            self.assertEqual((len(v.bolts), v.flights), (1, []), kind)

    def test_what_your_arrow_kills_stays_till_it_lands(self):
        m = add(self.w, self.lvl, "ogre", self.x + 4, self.y, state="wandering")
        m.hp = 1
        glyph = m.glyph
        self.w._stash(self.p, make_item("bow"))
        self.w._stash(self.p, make_item("arrows"))
        v = view_of(self.w, self.p)
        self.w.submit(self.p, {"a": "use", "slot": 0})
        deliver(self.w, v, self.p.id)
        self.assertNotIn(m, self.lvl.monsters)
        cells, thrown, _, _, pace, fell = v.flights[-1]
        self.assertEqual(fell[:3], (self.x + 4, self.y, glyph))
        with mock.patch("game.render.time.monotonic", return_value=thrown + 0.5 * pace):
            frame = v.draw()
        self.assertEqual(chr(frame["ch"][MAP_X + self.x + 4, MAP_Y + self.y]), glyph)

    def test_the_scouts_fireball_is_thrown(self):
        s = add(self.w, self.lvl, "kobold_scout", self.x + 4, self.y, target=self.p)
        self.w.drain_outbox()
        self.w._scout(s, self.lvl, self.p)
        kinds = [m.get("kind") for _, m in self.w.drain_outbox() if m["t"] == "fx"]
        self.assertEqual(kinds, ["fireball"])


if __name__ == "__main__":
    unittest.main()
