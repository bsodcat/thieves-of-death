"""Holding a direction: walking stops the moment the key comes up."""
import unittest

from game.constants import MAP_W, TICKS_PER_TURN
from game.items import make_item
from game.world import World


def corridor_world():
    """An empty level with the player at the start of its longest straight row."""
    w = World(1)
    lvl = w.level(1)
    for m in list(lvl.monsters):
        lvl.remove(m)
    lvl.monsters.clear()
    lvl.items.clear()
    a = w.join("Alice")
    best, start, row = 0, 0, 0
    for y in range(lvl.walkable.shape[1]):
        run = 0
        for x in range(MAP_W):
            run = run + 1 if lvl.walkable[x, y] else 0
            if run > best:
                best, start, row = run, x - run + 1, y
    lvl.move(a, start, row)
    return w, lvl, a, best


def hold(w, p, dx, dy, press=False):
    w.submit(p, {"a": "hold", "dx": dx, "dy": dy, "press": press})


class HoldTests(unittest.TestCase):
    def test_press_moves_at_once(self):
        w, lvl, a, _ = corridor_world()
        hold(w, a, 1, 0, press=True)
        self.assertEqual(a.turns, 1)

    def test_holding_keeps_walking_once_per_cooldown(self):
        w, lvl, a, length = corridor_world()
        self.assertGreater(length, 6)
        hold(w, a, 1, 0, press=True)
        w.advance(TICKS_PER_TURN * 3)
        self.assertEqual(a.turns, 4)

    def test_release_stops_you_dead(self):
        for extra in range(0, TICKS_PER_TURN, 7):  # every point in the cooldown
            w, lvl, a, _ = corridor_world()
            hold(w, a, 1, 0, press=True)
            w.advance(TICKS_PER_TURN * 2 + extra)
            moves = a.turns
            hold(w, a, 0, 0)
            w.advance(TICKS_PER_TURN * 5)
            self.assertEqual(a.turns, moves)

    def test_quick_tap_during_a_cooldown_still_counts(self):
        w, lvl, a, _ = corridor_world()
        w.submit(a, {"a": "move", "dx": 1, "dy": 0})
        w.advance(TICKS_PER_TURN // 2)
        hold(w, a, 1, 0, press=True)
        hold(w, a, 0, 0)                       # released before the cooldown ended
        self.assertEqual(a.turns, 1)
        w.advance(TICKS_PER_TURN * 3)
        self.assertEqual(a.turns, 2)           # one step, not more

    def test_lifting_one_key_of_a_diagonal_doesnt_buffer_a_step(self):
        w, lvl, a, _ = corridor_world()
        hold(w, a, 1, 0, press=True)
        hold(w, a, 0, 1)                       # a change with no press
        self.assertIsNone(a.pending)

    def test_changing_direction_mid_hold_takes_the_new_way(self):
        w, lvl, a, _ = corridor_world()
        hold(w, a, 1, 0, press=True)
        hold(w, a, -1, 0, press=True)
        x = a.x
        w.advance(TICKS_PER_TURN)
        self.assertEqual(a.x, x - 1)

    def test_potion_during_a_hold_then_keeps_walking(self):
        w, lvl, a, _ = corridor_world()
        a.hp = 5
        a.pack.append(make_item("healing"))
        hold(w, a, 1, 0, press=True)
        w.submit(a, {"a": "use", "slot": 0})
        hold(w, a, 1, 0, press=True)           # another press mustn't replace the potion
        w.advance(TICKS_PER_TURN)
        self.assertEqual(a.hp, 25)
        w.advance(TICKS_PER_TURN)
        self.assertEqual(a.turns, 3)

    def test_walking_into_a_wall_stops_without_hanging(self):
        w, lvl, a, length = corridor_world()
        hold(w, a, 1, 0, press=True)
        w.advance(TICKS_PER_TURN * (length + 5))
        self.assertEqual(a.turns, length - 1)
        self.assertIsNone(a.hold)

    def test_sealed_stairs_only_complain_once(self):
        w, lvl, a, _ = corridor_world()
        lvl.move(a, *lvl.up_front)
        w.drain_outbox()
        hold(w, a, lvl.up[0] - a.x, lvl.up[1] - a.y, press=True)
        w.advance(TICKS_PER_TURN * 10)
        texts = [m["text"] for _, m in w.drain_outbox()]
        self.assertEqual(sum("sealed" in t for t in texts), 1)

    def test_bad_input_is_ignored(self):
        w, lvl, a, _ = corridor_world()
        for dx, dy in ((2, 0), (0, -5), ("x", 0), (None, 1)):
            hold(w, a, dx, dy, press=True)
        self.assertIsNone(a.hold)
        self.assertEqual(a.turns, 0)

    def test_dying_or_leaving_lets_go(self):
        w, lvl, a, _ = corridor_world()
        hold(w, a, 1, 0, press=True)
        w.leave(a)
        self.assertIsNone(a.hold)
        w, lvl, a, _ = corridor_world()
        hold(w, a, 1, 0, press=True)
        w._kill(a, None)
        self.assertIsNone(a.hold)
        w.advance(TICKS_PER_TURN * 3)          # a dead player's hold can't run


if __name__ == "__main__":
    unittest.main()
