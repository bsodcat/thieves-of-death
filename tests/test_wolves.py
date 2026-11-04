"""Wolves losing their nerve: badly hurt, or with their pack taking a beating."""
import unittest
from unittest import mock

from game.world import cheb
from helpers_210 import add, empty_world, logged, open_spot, put

RUN, STAY = 0.1, 0.5   # what the dice roll: under 0.2 it runs


class WolfNerveTests(unittest.TestCase):
    def setUp(self):
        self.w, self.lvl, self.p = empty_world()
        self.x, self.y = open_spot(self.lvl, 5)
        put(self.lvl, self.p, self.x, self.y)

    def pack(self, size=3):
        """A pack hunting the player: the first wolf leads, and is the one beside them."""
        lead = add(self.w, self.lvl, "wolf", self.x + 1, self.y, target=self.p)
        rest = [add(self.w, self.lvl, "wolf", self.x + 1 + i, self.y + 2, target=self.p) for i in range(size - 1)]
        for m in rest:
            m.leader = lead
        return [lead, *rest]

    def turn(self, m, roll):
        with mock.patch.object(self.w.rng, "random", return_value=roll):
            self.w._monster_turn(m, self.lvl)

    def test_a_healthy_pack_fights(self):
        lead, *_ = self.pack()
        self.turn(lead, RUN)
        self.assertFalse(lead.fleeing)
        self.assertEqual(lead.nerve_tested, ())
        self.assertEqual(cheb(lead, self.p), 1)

    def test_badly_hurt_it_may_run(self):
        lead, *_ = self.pack()
        lead.hp = 2   # under 20% of 12
        self.turn(lead, RUN)
        self.assertTrue(lead.fleeing)
        self.assertEqual(cheb(lead, self.p), 2)
        self.assertIn("lost its nerve (hurt)", logged(self.w))

    def test_it_rolls_once_for_being_hurt(self):
        lead, *_ = self.pack()
        lead.hp = 2
        self.turn(lead, STAY)
        self.assertFalse(lead.fleeing)
        self.turn(lead, RUN)   # it already stood its ground
        self.assertFalse(lead.fleeing)
        self.assertEqual(lead.nerve_tested, ("hurt",))

    def test_just_above_a_fifth_doesnt_count(self):
        lead, *_ = self.pack()
        lead.hp = 3   # 25%, and one hurt wolf in three isn't more than a third
        self.turn(lead, RUN)
        self.assertFalse(lead.fleeing)

    def test_a_beaten_pack_may_run_even_the_healthy_ones(self):
        lead, a, b = self.pack()
        a.hp = b.hp = 5   # two of three under half
        self.turn(lead, RUN)
        self.assertTrue(lead.fleeing)
        self.assertIn("lost its nerve (pack)", logged(self.w))

    def test_a_third_isnt_more_than_a_third(self):
        lead, a, b = self.pack()
        a.hp = 5
        self.turn(lead, RUN)
        self.assertFalse(lead.fleeing)

    def test_each_reason_gets_its_own_roll(self):
        lead, a, b = self.pack()
        a.hp = b.hp = 5
        self.turn(lead, STAY)           # the pack's beating doesn't scare it
        self.assertFalse(lead.fleeing)
        lead.hp = 2
        self.turn(lead, RUN)            # but being badly hurt does
        self.assertTrue(lead.fleeing)
        self.assertEqual(lead.nerve_tested, ("pack", "hurt"))

    def test_the_pack_holds_together_after_its_leader_dies(self):
        lead, a, b, _ = self.pack(4)
        self.w._kill(lead, self.p)
        a.hp = 5
        b.hp = 5   # two of the three left
        self.turn(a, RUN)
        self.assertTrue(a.fleeing)

    def test_once_running_it_keeps_running(self):
        lead, *_ = self.pack()
        lead.hp = 2
        self.turn(lead, RUN)
        lead.hp = lead.max_hp
        self.turn(lead, STAY)
        self.assertEqual(cheb(lead, self.p), 3)

    def test_a_lone_wolf_is_its_own_pack(self):
        wolf = add(self.w, self.lvl, "wolf", self.x + 1, self.y, target=self.p)
        wolf.hp = 5   # under half: all of its pack of one
        self.turn(wolf, RUN)
        self.assertTrue(wolf.fleeing)


if __name__ == "__main__":
    unittest.main()
