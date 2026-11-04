"""The kobold leader's spear: what it looks like, and tiring after a run of thrusts."""
import unittest

from game.constants import SPEAR_REST_DISTANCE, SPEAR_THRUSTS
from game.render import SPEAR_BACK, SPEAR_LUNGE, SPEAR_SECONDS, ClientView
from game.world import cheb
from helpers_210 import add, empty_world, open_spot, put, said


class SpearTests(unittest.TestCase):
    def setUp(self):
        self.w, self.lvl, self.p = empty_world()
        self.x, self.y = open_spot(self.lvl, 5)
        put(self.lvl, self.p, self.x, self.y)
        self.p.god = True  # thrusts land on nothing, so the fight can run on
        self.k = add(self.w, self.lvl, "kobold_leader", self.x + 2, self.y, target=self.p)
        self.w.drain_outbox()

    def spears(self):
        return [m for pid, m in self.w.drain_outbox() if m["t"] == "fx" and m.get("kind") == "spear"
                and pid == self.p.id]

    def test_a_thrust_shows_the_spear_across_the_gap(self):
        self.w._monster_turn(self.k, self.lvl)
        (fx,) = self.spears()
        self.assertEqual([tuple(c) for c in fx["cells"]], [(self.x + 1, self.y), (self.x, self.y)])
        self.assertEqual(fx["from"], [self.x + 2, self.y])

    def test_it_tires_after_five_thrusts_and_backs_off(self):
        for _ in range(SPEAR_THRUSTS):
            self.w._monster_turn(self.k, self.lvl)
        self.spears()
        self.assertGreater(self.k.rest_until, self.w.clock)
        self.assertEqual(self.k.thrusts, 0)
        self.w._monster_turn(self.k, self.lvl)
        self.assertEqual(self.spears(), [])
        self.assertGreater(cheb(self.k, self.p), 2)

    def test_the_run_of_thrusts_and_the_message(self):
        sent = 0
        for _ in range(SPEAR_THRUSTS):
            self.w._monster_turn(self.k, self.lvl)
            sent += len(self.spears())
        self.assertEqual(sent, SPEAR_THRUSTS)
        self.w.drain_outbox()

    def test_it_says_when_its_winded(self):
        for _ in range(SPEAR_THRUSTS - 1):
            self.w._monster_turn(self.k, self.lvl)
        self.w.drain_outbox()
        self.w._monster_turn(self.k, self.lvl)
        self.assertIn("winded and backs off", said(self.w))

    def test_rested_it_comes_back(self):
        for _ in range(SPEAR_THRUSTS):
            self.w._monster_turn(self.k, self.lvl)
        while cheb(self.k, self.p) < SPEAR_REST_DISTANCE:
            self.w._monster_turn(self.k, self.lvl)
        self.w.clock = self.k.rest_until
        self.w._monster_turn(self.k, self.lvl)
        self.assertLess(cheb(self.k, self.p), SPEAR_REST_DISTANCE)


class SpearLookTests(unittest.TestCase):
    def test_every_angle_has_its_own_stick(self):
        arrow = ClientView.arrow
        self.assertEqual(arrow((2, 0), [(1, 0), (0, 0)]), "-")
        self.assertEqual(arrow((0, 2), [(0, 1), (0, 0)]), "|")
        self.assertEqual(arrow((2, 2), [(1, 1), (0, 0)]), "\\")
        self.assertEqual(arrow((0, 2), [(1, 1), (2, 0)]), "/")

    def test_it_lunges_into_the_target_then_pulls_back(self):
        v = ClientView.__new__(ClientView)
        cells = [(5, 5), (4, 5)]
        self.assertEqual(v.spear_cells(cells, 0.0), [(5, 5)])
        self.assertEqual(v.spear_cells(cells, (SPEAR_LUNGE + SPEAR_BACK) / 2), cells)
        self.assertEqual(v.spear_cells(cells, SPEAR_BACK), [(5, 5)])
        self.assertEqual(v.spear_cells(cells, SPEAR_SECONDS), [])

    def test_a_view_draws_it_in_red(self):
        from helpers_210 import view_of
        w, lvl, p = empty_world()
        v = view_of(w, p)
        v.apply({"t": "fx", "kind": "spear", "cells": [[p.x + 1, p.y], [p.x, p.y]], "from": [p.x + 2, p.y]})
        self.assertEqual(v.spears[0][2], "-")
        v.draw()


if __name__ == "__main__":
    unittest.main()
