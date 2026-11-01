"""The blink before a monster's melee hit, the red of a player's, and glows on players."""
import unittest
from unittest import mock

from game.constants import MONSTER_SWING
from game.entities import make_monster
from game.items import make_item
from game.render import ClientView
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


class ServerTests(unittest.TestCase):
    def test_a_monster_in_reach_reports_its_swing(self):
        w, lvl, p, m = setup()
        e = entity(w, p, m)
        self.assertAlmostEqual(e["strike"], 0.16)
        self.assertAlmostEqual(e["swing"], m.attack_cost * MONSTER_SWING * w.monster_time / 625)

    def test_monsters_swing_half_as_often(self):
        w, lvl, p, m = setup()
        p.hp = p.max_hp = 100000
        w._hunt(m, p)
        w.clock = m.next_time
        w._monster_act(m)
        self.assertEqual(m.next_time - w.clock, int(m.attack_cost * MONSTER_SWING * w.monster_time))

    def test_they_still_walk_at_the_same_speed(self):
        w, lvl, p, m = setup()
        spot = next(c for c in lvl.land_cells if 4 <= max(abs(c[0] - p.x), abs(c[1] - p.y)) <= 8)
        lvl.move(m, *spot)
        w._hunt(m, p)
        w.clock = m.next_time
        w._monster_act(m)
        self.assertEqual(m.next_time - w.clock, int(m.move_cost * w.monster_time))

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


def blinking(v, swing_share):
    """Whether a monster with a 1 second swing is dark at this point in it."""
    v.clock_at = 100.0
    with mock.patch("game.render.time.monotonic", return_value=100.0 + swing_share):
        return v.blinked_off({"strike": 1.0, "swing": 1.0})


class ClientTests(unittest.TestCase):
    def test_nothing_without_a_swing(self):
        self.assertFalse(ClientView().blinked_off({"id": 1}))

    def test_it_blinks_faster_near_the_end(self):
        v = ClientView()
        changes = []
        for start, stop in ((0.3, 0.65), (0.65, 1.0)):
            states = [blinking(v, start + (stop - start) * i / 2000) for i in range(2001)]
            changes.append(sum(a != b for a, b in zip(states, states[1:])))
        self.assertGreater(changes[1], changes[0] * 2)

    def test_it_doesnt_start_right_away(self):
        v = ClientView()
        self.assertFalse(any(blinking(v, i / 100) for i in range(28)))

    def test_it_counts_down_by_itself_between_states(self):
        v = ClientView()
        self.assertEqual({blinking(v, i / 100) for i in range(30, 100)}, {True, False})

    def test_a_late_state_leaves_it_showing(self):
        v = ClientView()
        v.clock_at = 10.0
        with mock.patch("game.render.time.monotonic", return_value=99.0):
            self.assertFalse(v.blinked_off({"strike": 0.5, "swing": 0.5}))

    def test_a_warning_only_dims_the_monster_and_adds_no_red(self):
        w, lvl, p, m = setup()
        v = view_of(w, p)
        at = (21 + m.x, 3 + m.y)
        calm = v.draw()
        with mock.patch.object(ClientView, "blinked_off", lambda self, ent: ent["id"] == m.id):
            dark = v.draw()
        self.assertLess(sum(int(c) for c in dark["fg"][at]), sum(int(c) for c in calm["fg"][at]))
        self.assertEqual(tuple(int(c) for c in dark["bg"][at]), tuple(int(c) for c in calm["bg"][at]))

    def test_without_a_warning_its_normal(self):
        w, lvl, p, m = setup(state="sleeping")
        frame = view_of(w, p).draw()
        self.assertEqual(tuple(int(c) for c in frame["fg"][21 + m.x, 3 + m.y]), m.color)


class HitTests(unittest.TestCase):
    def struck(self):
        w, lvl, p, m = setup()
        m.hp = m.max_hp = 100000
        v = view_of(w, p)
        w.drain_outbox()
        w._attack(p, m)
        for _, msg in w.drain_outbox():
            v.apply(msg)
        return w, p, m, v

    def test_a_players_blow_shows_red_on_the_monster_and_fades(self):
        w, p, m, v = self.struck()
        at = (21 + m.x, 3 + m.y)
        struck = v.hits[0][2]
        with mock.patch("game.render.time.monotonic", return_value=struck):
            fresh = v.draw()["bg"][at].copy()
        with mock.patch("game.render.time.monotonic", return_value=struck + 0.25):
            later = v.draw()["bg"][at].copy()
        self.assertGreater(int(fresh[0]), 200)
        self.assertGreater(int(fresh[0]), int(fresh[2]) * 3)
        self.assertLess(int(later[0]), int(fresh[0]))

    def test_it_is_a_gradient(self):
        w, p, m, v = self.struck()
        struck = v.hits[0][2]
        with mock.patch("game.render.time.monotonic", return_value=struck):
            frame = v.draw()
        lit = [int(frame["bg"][21 + m.x + dx, 3 + m.y][0]) for dx in (0, 1, -1)]
        self.assertEqual(max(lit), lit[0])

    def test_it_clears(self):
        w, p, m, v = self.struck()
        with mock.patch("game.render.time.monotonic", return_value=v.hits[0][2] + 1):
            v.draw()
        self.assertEqual(v.hits, [])

    def test_a_monsters_blow_shows_nothing(self):
        w, lvl, p, m = setup()
        p.hp = p.max_hp = 100000
        w.drain_outbox()
        w._attack(m, p)
        self.assertFalse([msg for _, msg in w.drain_outbox() if msg.get("kind") == "hit"])


class GlowTests(unittest.TestCase):
    def player_view(self):
        w = World(3)
        p = w.join("A")
        lvl = w.levels[1]
        v = view_of(w, p)
        return w, lvl, p, v

    def glow_at(self, v, p, dx, dy, channel=2):
        with_glow = v.draw()["bg"][21 + p.x + dx, 3 + p.y + dy]
        ents, v.ents = v.ents, [{k: val for k, val in e.items() if k not in ("wet", "aura")} for e in v.ents]
        without = v.draw()["bg"][21 + p.x + dx, 3 + p.y + dy]
        v.ents = ents
        return int(with_glow[channel]) - int(without[channel])

    def test_water_walking_glows_out_to_5_tiles_and_fades(self):
        w, lvl, p, v = self.player_view()
        p.waterwalk_until = w.clock + 10 ** 6
        v.apply(w.state_for(p))
        v.visible[:] = True
        with mock.patch("game.render.time.monotonic", return_value=0.0):
            glow = [self.glow_at(v, p, dx, 0) for dx in (0, 1, 2, 3, 4)]
            outside = self.glow_at(v, p, 6, 0)
        self.assertEqual(glow, sorted(glow, reverse=True))
        self.assertGreater(glow[0], 100)
        self.assertGreater(glow[4], 0)
        self.assertEqual(outside, 0)

    def test_it_ends_with_the_potion(self):
        w, lvl, p, v = self.player_view()
        v.apply(w.state_for(p))
        self.assertFalse(next(e for e in v.ents if e["id"] == p.id)["wet"])

    def test_magic_armor_glows_3x3_with_a_gradient(self):
        w, lvl, p, v = self.player_view()
        p.armor = make_item("magic")
        v.apply(w.state_for(p))
        v.visible[:] = True
        with mock.patch("game.render.time.monotonic", return_value=0.0):
            center, side, corner = (self.glow_at(v, p, x, y) for x, y in ((0, 0), (1, 0), (1, 1)))
            outside = self.glow_at(v, p, 2, 0)
        self.assertGreater(center, side)
        self.assertGreater(side, corner)
        self.assertGreater(corner, 0)
        self.assertEqual(outside, 0)

    def test_it_pulses_slowly(self):
        w, lvl, p, v = self.player_view()
        p.armor = make_item("magic")
        v.apply(w.state_for(p))
        v.visible[:] = True

        def brightness(t):
            with mock.patch("game.render.time.monotonic", return_value=t):
                return self.glow_at(v, p, 0, 0)
        self.assertLess(abs(brightness(0.0) - brightness(0.1)), 25)
        self.assertGreater(max(brightness(t / 2) for t in range(11)) - min(brightness(t / 2) for t in range(11)), 40)

    def test_magic_armor_doesnt_sparkle(self):
        w, lvl, p, v = self.player_view()
        p.armor = make_item("magic")
        e = next(e for e in w.state_for(p)["ents"] if e["id"] == p.id)
        self.assertTrue(e["aura"])
        self.assertFalse(e["ward"])
        self.assertIn("Reflecting magic", str(v._describe_actor(e)))

    def test_a_ponds_ward_still_sparkles(self):
        w, lvl, p, v = self.player_view()
        p.reflect_until = w.clock + 10 ** 6
        e = next(e for e in w.state_for(p)["ents"] if e["id"] == p.id)
        self.assertTrue(e["ward"])
        self.assertFalse(e["aura"])


if __name__ == "__main__":
    unittest.main()
