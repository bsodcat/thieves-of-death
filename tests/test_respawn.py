"""The wait between the whole party falling and a fresh dungeon, and skipping it with Enter."""
import time
import unittest

from game.constants import RESET_DELAY
from game.entities import make_monster

from helpers_210 import empty_world, said


def wipe(w, *players):
    for p in players:
        w._kill(p, make_monster("ogre", 77))


class RespawnDelayTests(unittest.TestCase):
    def test_the_wait_is_at_least_ten_seconds(self):
        self.assertGreaterEqual(RESET_DELAY, 10)
        w, lvl, a = empty_world()
        start = time.monotonic()
        wipe(w, a)
        self.assertGreaterEqual(w.reset_at - start, 10)
        self.assertFalse(w.check_reset(start + 9.9))
        self.assertEqual(w.run, 1)
        self.assertTrue(w.check_reset(w.reset_at + 0.1))
        self.assertEqual(w.run, 2)

    def test_status_counts_down_and_offers_enter(self):
        w, lvl, a = empty_world()
        wipe(w, a)
        kind, text = w.state_for(a)["status"]
        self.assertEqual(kind, "over")
        self.assertIn("Press Enter", text)
        self.assertRegex(text, r"New dungeon in (9|10)s")

    def test_enter_alone_starts_the_new_dungeon(self):
        w, lvl, a = empty_world()
        wipe(w, a)
        w.submit(a, {"a": "ready"})
        self.assertTrue(w.check_reset(time.monotonic()))
        self.assertEqual(w.run, 2)
        self.assertTrue(a.alive)
        self.assertEqual(w.ready, set())

    def test_the_whole_party_must_press_enter(self):
        w, lvl, a, b = empty_world(names=("Alice", "Bob"))
        wipe(w, a, b)
        self.assertIsNotNone(w.reset_at)
        w.drain_outbox()
        w.submit(a, {"a": "ready"})
        self.assertIn("Alice is ready for a new dungeon (1/2)", said(w))
        self.assertFalse(w.check_reset(time.monotonic()))
        self.assertIn("Waiting for the rest", w.state_for(a)["status"][1])
        w.submit(a, {"a": "ready"})  # pressing again changes nothing
        self.assertFalse(w.check_reset(time.monotonic()))
        w.submit(b, {"a": "ready"})
        self.assertTrue(w.check_reset(time.monotonic()))
        self.assertEqual(w.run, 2)

    def test_players_who_left_are_not_waited_for(self):
        w, lvl, a, b = empty_world(names=("Alice", "Bob"))
        wipe(w, a, b)
        w.leave(b)
        w.submit(a, {"a": "ready"})
        self.assertTrue(w.check_reset(time.monotonic()))

    def test_enter_does_nothing_while_the_party_lives(self):
        w, lvl, a, b = empty_world(names=("Alice", "Bob"))
        wipe(w, a)
        w.submit(a, {"a": "ready"})
        self.assertEqual(w.ready, set())
        self.assertNotEqual(w.state_for(a)["status"][0], "over")

    def test_enter_does_not_cut_the_victory_short(self):
        w, lvl, a = empty_world()
        w._win(a)
        w.submit(a, {"a": "ready"})
        self.assertFalse(w.check_reset(time.monotonic()))


if __name__ == "__main__":
    unittest.main()
