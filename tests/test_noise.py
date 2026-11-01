"""Equipped gear capping stealth, and the help panel."""
import unittest

from game import protocol
from game.constants import (MAP_H, MAP_W, MAP_X, MAP_Y, NOTICE_RANGE_AWAKE, SCREEN_H, SCREEN_W, STEALTH_FILL_SECONDS,
                            STEALTH_MAX, STEALTH_RANGE_MIN, TICKS_PER_SECOND, TICKS_PER_TURN)
from game.entities import make_monster
from game.items import ITEMS, make_item
from game.render import HELP_LINES, ClientView
from game.world import World, cheb

FILL = int(STEALTH_FILL_SECONDS * TICKS_PER_SECOND)


def setup_world(gear=()):
    w = World(1)
    lvl = w.level(1)
    for m in list(lvl.monsters):
        lvl.remove(m)
    lvl.monsters.clear()
    lvl.items.clear()
    a = w.join("Alice")
    a.pack = [make_item(k) for k in gear]
    for slot in range(len(gear)):
        w._perform(a, {"a": "use", "slot": slot})
    return w, lvl, a


def view_of(w, p):
    v = ClientView()
    v.apply({"t": "welcome", "id": p.id, "name": p.name})
    for msg in (w.level_msg(p.depth), w.pack_msg(p), w.state_for(p)):
        v.apply(protocol.decode(protocol.encode(msg)))
    return v


def screen(v):
    frame = v.draw()
    return "\n".join("".join(chr(c) for c in frame["ch"][:, y]) for y in range(frame.shape[1]))


class NoiseTests(unittest.TestCase):
    def test_bare_is_uncapped(self):
        w, lvl, a = setup_world()
        self.assertEqual(a.stealth_cap, STEALTH_MAX)
        w.advance(FILL)
        self.assertEqual(a.stealth, STEALTH_MAX)

    def test_each_item_lowers_the_cap(self):
        for kind, t in ITEMS.items():
            if t["category"] in ("weapon", "armor"):
                w, lvl, a = setup_world([kind])
                self.assertGreater(t["noise"], 0, kind)
                self.assertEqual(a.stealth_cap, STEALTH_MAX - t["noise"], kind)

    def test_more_gear_means_a_lower_cap(self):
        w, lvl, a = setup_world(["sword", "scale"])
        self.assertEqual(a.stealth_cap, 60)
        w, lvl, b = setup_world(["sword"])
        self.assertGreater(b.stealth_cap, a.stealth_cap)

    def test_heavier_gear_is_louder(self):
        noise = {k: t["noise"] for k, t in ITEMS.items() if "noise" in t}
        self.assertLess(noise["dagger"], noise["sword"])
        self.assertLess(noise["sword"], noise["mace"])
        self.assertLess(noise["leather"], noise["scale"])
        self.assertLess(noise["scale"], noise["plate"])

    def test_the_bar_stops_at_the_cap(self):
        w, lvl, a = setup_world(["mace", "plate"])
        w.advance(FILL * 3)
        self.assertEqual(a.stealth, 40)

    def test_equipping_pulls_the_bar_down_at_once(self):
        w, lvl, a = setup_world()
        w.advance(FILL)
        a.pack.append(make_item("plate"))
        w.advance(TICKS_PER_TURN)
        w.submit(a, {"a": "use", "slot": 0})
        self.assertEqual(a.stealth, 60)

    def test_removing_gear_lifts_the_cap(self):
        w, lvl, a = setup_world(["plate"])
        w.advance(FILL)
        w.submit(a, {"a": "use", "slot": 0})
        self.assertEqual(a.stealth_cap, STEALTH_MAX)
        w.advance(FILL)
        self.assertEqual(a.stealth, STEALTH_MAX)

    def test_dropping_equipped_gear_lifts_the_cap(self):
        w, lvl, a = setup_world(["plate"])
        w.advance(TICKS_PER_TURN * 2)
        w.submit(a, {"a": "drop", "slot": 0})
        self.assertEqual(a.stealth_cap, STEALTH_MAX)

    def test_carrying_gear_is_silent(self):
        w, lvl, a = setup_world()
        a.pack = [make_item("mace"), make_item("plate")]
        w.advance(FILL)
        self.assertEqual((a.stealth_cap, a.stealth), (STEALTH_MAX, STEALTH_MAX))

    def test_potions_make_no_noise(self):
        self.assertNotIn("noise", ITEMS["healing"])
        self.assertNotIn("noise", make_item("healing").info)

    def test_cap_widens_detection_even_when_still(self):
        w, lvl, quiet = setup_world()
        w.advance(FILL)
        w2, lvl2, loud = setup_world(["mace", "plate"])
        w2.advance(FILL)
        near = w._notice_range(quiet, NOTICE_RANGE_AWAKE)
        far = w2._notice_range(loud, NOTICE_RANGE_AWAKE)
        self.assertAlmostEqual(near, NOTICE_RANGE_AWAKE * STEALTH_RANGE_MIN)
        self.assertAlmostEqual(far, 14 * (1 - 0.7 * 0.4))
        self.assertGreater(far, near)

    def test_monster_notices_a_loud_player_a_quiet_one_gets_past(self):
        results = {}
        for name, gear in (("quiet", ()), ("loud", ("mace", "plate"))):
            w, lvl, a = setup_world(gear)
            for cell in lvl.floor_cells:
                lvl.move(a, *cell)
                spot = next(((x, y) for x, y in lvl.floor_cells if max(abs(x - a.x), abs(y - a.y)) == 7
                             and w.fov(a)[x, y] and (x, y) not in lvl.occupant), None)
                if spot:
                    break
            m = make_monster("goblin", 700)
            m.state = "wandering"
            lvl.place(m, *spot)
            lvl.monsters.append(m)
            a.stealth = a.stealth_cap
            self.assertEqual(cheb(m, a), 7)
            w._monster_turn(m, lvl)
            results[name] = m.state
        self.assertEqual(results, {"quiet": "wandering", "loud": "hunting"})

    def test_fallen_gear_and_new_runs_clear_the_cap(self):
        w, lvl, a = setup_world(["plate"])
        w._kill(a, make_monster("rat", 800))
        self.assertEqual(a.stealth_cap, STEALTH_MAX)         # dropped on death in Classic
        w, lvl, a = setup_world(["plate"])
        w.reset_run()
        self.assertEqual(a.stealth_cap, STEALTH_MAX)

    def test_revived_players_keep_their_cap(self):
        w = World(1, mode="Revive")
        lvl = w.level(1)
        a, b = w.join("A"), w.join("B")
        a.pack = [make_item("plate")]
        w._perform(a, {"a": "use", "slot": 0})
        w._kill(a, make_monster("rat", 800))
        w.advance(int(3 * TICKS_PER_SECOND))
        self.assertTrue(a.alive)
        self.assertEqual(a.stealth_cap, 60)
        self.assertLessEqual(a.stealth, a.stealth_cap)


class DisplayTests(unittest.TestCase):
    def test_sidebar_shows_the_cap_and_detection(self):
        w, lvl, a = setup_world(["mace", "plate"])
        w.advance(FILL)
        text = screen(view_of(w, a))
        self.assertIn("Stealth 40% max 40", text)
        self.assertIn("Detection 10 tiles", text)

    def test_no_cap_label_when_bare(self):
        w, lvl, a = setup_world()
        w.advance(FILL)
        text = screen(view_of(w, a))
        self.assertIn("Stealth 100%", text)
        self.assertNotIn(" max ", text)
        self.assertIn("Detection 4 tiles", text)

    def test_bar_marks_the_part_out_of_reach(self):
        w, lvl, a = setup_world(["mace", "plate"])
        frame = view_of(w, a).draw()
        self.assertEqual(tuple(frame["bg"][19, 2]), (70, 24, 24))
        self.assertNotEqual(tuple(frame["bg"][7, 2]), (70, 24, 24))
        w, lvl, a = setup_world()
        frame = view_of(w, a).draw()
        self.assertNotEqual(tuple(frame["bg"][19, 2]), (70, 24, 24))

    def test_pack_shows_noise_and_the_limit(self):
        w, lvl, a = setup_world(["mace", "plate"])
        v = view_of(w, a)
        v.show_pack = True
        text = screen(v)
        self.assertIn("dmg 12-18, slow, noise 20 (on)", text)
        self.assertIn("armor +60, heavy, noise 40 (on)", text)
        self.assertIn("Equipped gear limits stealth to 40%", text)


class HelpTests(unittest.TestCase):
    def view(self):
        w, lvl, a = setup_world()
        return view_of(w, a)

    def test_hidden_until_asked_for(self):
        self.assertNotIn("Controls (", screen(self.view()))

    def test_lists_every_control(self):
        v = self.view()
        v.show_help = True
        text = screen(v)
        for keys, what in HELP_LINES:
            self.assertIn(keys, text)
            self.assertIn(what, text)
        self.assertIn(v.tip, text)

    def test_every_control_in_the_real_key_handling_is_listed(self):
        keys = " ".join(k for k, _ in HELP_LINES)
        for needed in ("hjklyubn", "1-9, 0", "i", "d, then 1-0 or $", "Mouse", "g", "Enter", "Esc", "Q twice", "? or F1"):
            self.assertIn(needed, keys)

    def test_footer_mentions_it(self):
        self.assertIn("? help", screen(self.view()))

    def test_fits_on_screen(self):
        v = self.view()
        v.show_help = True
        for side in (5, 70):                     # on either side of the map, away from the player
            v.ents = [{**e, "x": side} for e in v.ents]
            frame = v.draw()
            self.assertEqual(frame.shape, (SCREEN_W, SCREEN_H))
            text = screen(v)
            self.assertIn(v.tip, text)
            for keys, what in HELP_LINES:
                self.assertIn(what, text)

    def test_panels_never_cover_the_player_anywhere_on_the_map(self):
        for panel in ("show_help", "show_pack"):
            v = self.view()
            setattr(v, panel, True)
            for x in range(MAP_W):
                for y in range(MAP_H):
                    v.ents = [{**e, "x": x, "y": y} for e in v.ents]
                    frame = v.draw()
                    self.assertEqual(chr(frame["ch"][MAP_X + x, MAP_Y + y]), "@", (panel, x, y))

    def test_works_while_dead(self):
        w, lvl, a = setup_world()
        w._kill(a, make_monster("rat", 800))
        v = view_of(w, a)
        v.show_help = True
        self.assertIn("Controls (", screen(v))


if __name__ == "__main__":
    unittest.main()
