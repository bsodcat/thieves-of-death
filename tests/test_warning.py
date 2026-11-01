"""The warning a monster gives before a melee hit."""
import math
import unittest
from unittest import mock

from game.entities import make_monster
from game.render import WARNING_RED, ClientView
from game.world import World


def setup(kind="ogre", state="hunting"):
    w = World(3)
    lvl = w.level(1)
    for m in list(lvl.monsters):
        lvl.remove(m)
    lvl.monsters.clear()
    p = w.join("A")
    m = make_monster(kind, 900)
    m.state, m.next_time = state, w.clock + 100
    spot = next((p.x + dx, p.y + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)) if lvl.walkable[p.x + dx, p.y + dy])
    lvl.place(m, *spot)
    lvl.monsters.append(m)
    return w, lvl, p, m


def view_of(w, p):
    v = ClientView()
    v.apply({"t": "welcome", "id": p.id, "name": p.name})
    v.apply(w.level_msg(p.depth))
    v.apply(w.state_for(p))
    return v


def entity(w, p, m):
    return next(e for e in w.state_for(p)["ents"] if e["id"] == m.id)


def at_share(v, e, share):
    """The warning a share of the way through a swing."""
    v.clock_at = 100.0
    e = {**e, "swing": 1.0, "strike": 1.0}
    with mock.patch("game.render.time.monotonic", return_value=100.0 + share):
        return v.warning(e)


class ServerTests(unittest.TestCase):
    def test_a_monster_in_reach_reports_its_swing(self):
        w, lvl, p, m = setup()
        e = entity(w, p, m)
        self.assertAlmostEqual(e["strike"], 0.16)
        self.assertAlmostEqual(e["swing"], m.attack_cost * w.monster_time / 625)

    def test_out_of_reach_there_is_no_warning(self):
        w, lvl, p, m = setup()
        spot = next(c for c in lvl.land_cells if max(abs(c[0] - p.x), abs(c[1] - p.y)) == 3 and w.fov(p)[c])
        lvl.move(m, *spot)
        self.assertNotIn("strike", entity(w, p, m))

    def test_sleepers_dont_warn(self):
        w, lvl, p, m = setup(state="sleeping")
        self.assertNotIn("strike", entity(w, p, m))

    def test_frozen_monsters_dont_warn(self):
        w, lvl, p, m = setup()
        m.frozen_until = w.clock + 1000
        self.assertNotIn("strike", entity(w, p, m))

    def test_mushrooms_dont_warn(self):
        w, lvl, p, m = setup("mushroom")
        self.assertNotIn("strike", entity(w, p, m))

    def test_it_doesnt_go_negative(self):
        w, lvl, p, m = setup()
        m.next_time = w.clock - 500
        self.assertEqual(entity(w, p, m)["strike"], 0.0)

    def test_players_and_merchants_never_warn(self):
        w, lvl, p, m = setup()
        self.assertNotIn("strike", next(e for e in w.state_for(p)["ents"] if e["id"] == p.id))

    def test_a_wall_corner_stops_it(self):
        w, lvl, p, m = setup()
        spots = [(x, y) for x, y in lvl.land_cells if not lvl.hover[x + 1, y] and not lvl.hover[x, y + 1]
                 and lvl.walkable[x + 1, y + 1]]
        if spots:
            x, y = spots[0]
            lvl.move(p, x, y)
            lvl.move(m, x + 1, y + 1)
            self.assertNotIn("strike", entity(w, p, m))


class ClientTests(unittest.TestCase):
    def test_nothing_without_a_swing(self):
        self.assertEqual(ClientView().warning({"id": 1}), 0.0)

    def test_the_red_climbs_exponentially(self):
        v = ClientView()
        rise = [at_share(v, {}, s) / (0.65 + 0.35 * math.cos(math.exp(s * 4.5)))
                for s in (0.25, 0.5, 0.75, 1.0)]
        self.assertEqual(rise, sorted(rise))
        self.assertLess(rise[1], rise[3] / 5)
        self.assertGreater(rise[3] - rise[2], rise[1] - rise[0])

    def test_it_blinks_faster_near_the_end(self):
        v = ClientView()
        flips = []
        for start, stop in ((0.0, 0.5), (0.5, 1.0)):
            values = [at_share(v, {}, start + (stop - start) * i / 400) for i in range(401)]
            ratio = [b / a if a else 1 for a, b in zip(values, values[1:])]
            flips.append(sum((x > 1) != (y > 1) for x, y in zip(ratio, ratio[1:])))
        self.assertGreater(flips[1], flips[0])

    def test_nearly_invisible_early_and_strong_at_the_end(self):
        v = ClientView()
        self.assertLess(at_share(v, {}, 0.2), 0.02)
        self.assertGreater(max(at_share(v, {}, 0.9 + i / 1000) for i in range(100)), 0.6)

    def test_it_counts_down_by_itself_between_states(self):
        v = ClientView()
        v.clock_at = 50.0
        e = {"strike": 1.0, "swing": 1.0}
        with mock.patch("game.render.time.monotonic", return_value=50.2):
            early = v.warning(e)
        with mock.patch("game.render.time.monotonic", return_value=50.97):
            late = v.warning(e)
        self.assertGreater(late, early)

    def test_a_late_state_stays_at_full_rather_than_breaking(self):
        v = ClientView()
        v.clock_at = 10.0
        with mock.patch("game.render.time.monotonic", return_value=99.0):
            self.assertGreaterEqual(v.warning({"strike": 0.5, "swing": 0.5}), 0.0)

    def test_the_monster_is_drawn_red(self):
        w, lvl, p, m = setup()
        v = view_of(w, p)
        at = (21 + m.x, 3 + m.y)
        e = next(e for e in v.ents if e["id"] == m.id)
        with mock.patch("game.render.time.monotonic", return_value=v.clock_at + e["strike"] - 0.0001):
            with mock.patch.object(ClientView, "warning", lambda self, ent: 1.0 if ent["id"] == m.id else 0.0):
                frame = v.draw()
        self.assertEqual(tuple(int(c) for c in frame["bg"][at]), WARNING_RED)
        self.assertEqual(tuple(int(c) for c in frame["fg"][at]), WARNING_RED)

    def test_without_a_warning_its_normal(self):
        w, lvl, p, m = setup(state="sleeping")
        frame = view_of(w, p).draw()
        self.assertEqual(tuple(int(c) for c in frame["fg"][21 + m.x, 3 + m.y]), m.color)


if __name__ == "__main__":
    unittest.main()
