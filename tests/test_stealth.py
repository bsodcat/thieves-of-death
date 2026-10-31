"""Stealth: the bar, and what it does to monster detection range."""
import unittest

from game import protocol
from game.constants import (NOTICE_RANGE_AWAKE, NOTICE_RANGE_SLEEPING, STEALTH_FILL_SECONDS, STEALTH_MAX,
                            STEALTH_MOVE_DRAIN, STEALTH_RANGE_MIN, TICKS_PER_SECOND, TICKS_PER_TURN)
from game.entities import make_monster, reset_player
from game.render import ClientView
from game.world import World, cheb


def setup_world():
    w = World(1)
    lvl = w.level(1)
    for m in list(lvl.monsters):
        lvl.remove(m)
    lvl.monsters.clear()
    lvl.items.clear()
    return w, lvl, w.join("Alice")


def open_step(lvl, p):
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        n = (p.x + dx, p.y + dy)
        if lvl.walkable[n] and n not in lvl.occupant:
            return {"a": "move", "dx": dx, "dy": dy}
    raise AssertionError("boxed in")


def watcher_at(w, lvl, p, dist, state):
    """Puts the player somewhere with a monster in plain sight exactly `dist` tiles away."""
    for cell in lvl.floor_cells:
        lvl.move(p, *cell)
        for x, y in lvl.floor_cells:
            if max(abs(x - p.x), abs(y - p.y)) == dist and w.fov(p)[x, y] and (x, y) not in lvl.occupant:
                m = make_monster("goblin", 700)
                m.state = state
                lvl.place(m, x, y)
                lvl.monsters.append(m)
                return m
    raise AssertionError(f"no line of sight {dist} tiles long")


class StealthBarTests(unittest.TestCase):
    def test_standing_still_fills_it(self):
        w, lvl, a = setup_world()
        self.assertEqual(a.stealth, 0)
        w.advance(int(STEALTH_FILL_SECONDS * TICKS_PER_SECOND / 2))
        self.assertAlmostEqual(a.stealth, STEALTH_MAX / 2, delta=1)
        w.advance(int(STEALTH_FILL_SECONDS * TICKS_PER_SECOND))
        self.assertEqual(a.stealth, STEALTH_MAX)

    def test_each_step_drains_it(self):
        w, lvl, a = setup_world()
        a.stealth = STEALTH_MAX
        w.submit(a, open_step(lvl, a))
        self.assertEqual(a.stealth, STEALTH_MAX - STEALTH_MOVE_DRAIN)

    def test_bumping_a_wall_costs_nothing(self):
        w, lvl, a = setup_world()
        a.stealth = 50
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            if not lvl.walkable[a.x + dx, a.y + dy] and lvl.tiles[a.x + dx, a.y + dy] == 0:
                w.submit(a, {"a": "move", "dx": dx, "dy": dy})
                self.assertEqual(a.stealth, 50)
                return
        self.skipTest("no wall beside the start")

    def test_holding_a_direction_empties_it(self):
        w, lvl, a = setup_world()
        a.stealth = STEALTH_MAX
        for _ in range(10):
            w.submit(a, open_step(lvl, a))
            w.advance(TICKS_PER_TURN)
        self.assertLess(a.stealth, 15)

    def test_attacking_empties_it(self):
        w, lvl, a = setup_world()
        a.stealth = STEALTH_MAX
        rat = make_monster("rat", 500)
        rat.hp = 99
        step = open_step(lvl, a)
        lvl.place(rat, a.x + step["dx"], a.y + step["dy"])
        lvl.monsters.append(rat)
        w.submit(a, step)
        self.assertEqual(a.stealth, 0)

    def test_potions_dont_break_it(self):
        from game.items import make_item
        w, lvl, a = setup_world()
        a.hp, a.stealth = 5, 80
        a.pack.append(make_item("healing"))
        w.submit(a, {"a": "use", "slot": 0})
        self.assertEqual(a.stealth, 80)

    def test_new_run_resets_it(self):
        w, lvl, a = setup_world()
        a.stealth = 80
        reset_player(a)
        self.assertEqual(a.stealth, 0)

    def test_shown_to_the_client(self):
        w, lvl, a = setup_world()
        a.stealth = 62.9
        view = ClientView()
        view.apply({"t": "welcome", "id": a.id, "name": a.name})
        for msg in (w.level_msg(1), w.pack_msg(a), w.state_for(a)):
            view.apply(protocol.decode(protocol.encode(msg)))
        frame = view.draw()
        text = "\n".join("".join(chr(c) for c in frame["ch"][:, y]) for y in range(frame.shape[1]))
        self.assertIn("Stealth 62%", text)


class DetectionTests(unittest.TestCase):
    def test_range_shrinks_with_stealth(self):
        w, lvl, a = setup_world()
        self.assertEqual(w._notice_range(a, NOTICE_RANGE_AWAKE), NOTICE_RANGE_AWAKE)
        a.stealth = STEALTH_MAX
        self.assertAlmostEqual(w._notice_range(a, NOTICE_RANGE_AWAKE), NOTICE_RANGE_AWAKE * STEALTH_RANGE_MIN)

    def test_awake_monster_misses_a_still_player(self):
        w, lvl, a = setup_world()
        m = watcher_at(w, lvl, a, 7, "wandering")
        a.stealth = STEALTH_MAX
        w._monster_turn(m, lvl)
        self.assertEqual(m.state, "wandering")

    def test_awake_monster_spots_a_moving_player(self):
        w, lvl, a = setup_world()
        m = watcher_at(w, lvl, a, 7, "wandering")
        a.stealth = 0
        w._monster_turn(m, lvl)
        self.assertEqual(m.state, "hunting")

    def test_stealth_stops_working_up_close(self):
        w, lvl, a = setup_world()
        m = watcher_at(w, lvl, a, 3, "wandering")
        a.stealth = STEALTH_MAX
        self.assertLessEqual(cheb(m, a), w._notice_range(a, NOTICE_RANGE_AWAKE))
        w._monster_turn(m, lvl)
        self.assertEqual(m.state, "hunting")

    def test_sleeping_monster_stays_asleep(self):
        w, lvl, a = setup_world()
        m = watcher_at(w, lvl, a, 5, "sleeping")
        self.assertLessEqual(cheb(m, a), NOTICE_RANGE_SLEEPING)
        a.stealth = STEALTH_MAX
        for _ in range(200):
            w._monster_turn(m, lvl)
        self.assertEqual(m.state, "sleeping")

    def test_sleeping_monster_wakes_for_a_noisy_player(self):
        w, lvl, a = setup_world()
        m = watcher_at(w, lvl, a, 5, "sleeping")
        a.stealth = 0
        for _ in range(200):
            if m.state != "sleeping":
                break
            w._monster_turn(m, lvl)
        self.assertEqual(m.state, "hunting")

    def test_hunters_keep_hunting(self):
        w, lvl, a = setup_world()
        m = watcher_at(w, lvl, a, 7, "hunting")
        m.target_id = a.id
        a.stealth = STEALTH_MAX
        w._monster_turn(m, lvl)
        self.assertEqual(m.state, "hunting")


if __name__ == "__main__":
    unittest.main()
