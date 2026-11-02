"""Walking past allies, quick heal, sorting and clicking the pack, and changing the keys."""
import os
import tempfile
import unittest
from unittest import mock

import tcod.event

import client
from game import controls, settings
from game.constants import MAP_X
from game.entities import make_monster
from game.items import make_item
from game.menu import Form, Row
from game.render import ClientView
from game.tiles import DEEP, FLOOR, PIT, WALL
from game.world import World

KEYS = tcod.event.KeySym


def open_floor():
    """Two players in an empty room, with nothing in the way."""
    w = World(3)
    lvl = w.level(1)
    for m in list(lvl.monsters):
        lvl.remove(m)
    lvl.monsters.clear()
    lvl.items.clear()
    a, b = w.join("A"), w.join("B")
    lvl.tiles[10:30, 10:20] = FLOOR
    lvl.walkable[10:30, 10:20] = True
    lvl.hover[10:30, 10:20] = True
    lvl.mainland[10:30, 10:20] = True
    lvl.is_door[10:30, 10:20] = False
    lvl.plants[10:30, 10:20] = False
    lvl.remove(a)
    lvl.remove(b)
    lvl.place(a, 15, 15)
    lvl.place(b, 16, 15)
    return w, lvl, a, b


def wall(lvl, x, y):
    lvl.tiles[x, y] = WALL
    lvl.walkable[x, y] = False
    lvl.hover[x, y] = False


class PassingTests(unittest.TestCase):
    def test_you_walk_past_an_ally_and_they_stay_put(self):
        w, lvl, a, b = open_floor()
        self.assertGreater(w._player_move(a, lvl, 1, 0), 0)
        self.assertEqual((a.x, a.y), (17, 15))
        self.assertEqual((b.x, b.y), (16, 15))

    def test_two_allies_heading_the_same_way_dont_hold_each_other_back(self):
        w, lvl, a, b = open_floor()
        for _ in range(6):
            w._player_move(a, lvl, 1, 0)
            w._player_move(b, lvl, 1, 0)
        self.assertGreaterEqual(min(a.x, b.x), 21)

    def test_two_allies_meeting_in_a_corridor_both_get_through(self):
        w, lvl, a, b = open_floor()
        for x in range(10, 30):
            wall(lvl, x, 14)
            wall(lvl, x, 16)
        w._player_move(a, lvl, 1, 0)
        w._player_move(b, lvl, -1, 0)
        self.assertGreater(a.x, 15)
        self.assertLess(b.x, a.x)

    def test_a_line_of_allies_is_passed_all_at_once(self):
        w, lvl, a, b = open_floor()
        c = w.join("C")
        lvl.move(c, 17, 15)
        w._player_move(a, lvl, 1, 0)
        self.assertEqual((a.x, a.y), (18, 15))

    def test_with_a_wall_behind_them_you_swap(self):
        w, lvl, a, b = open_floor()
        wall(lvl, 17, 15)
        w._player_move(a, lvl, 1, 0)
        self.assertEqual(((a.x, a.y), (b.x, b.y)), ((16, 15), (15, 15)))

    def test_with_a_monster_behind_them_you_swap(self):
        w, lvl, a, b = open_floor()
        m = make_monster("rat", 900)
        lvl.monsters.append(m)
        lvl.place(m, 17, 15)
        w._player_move(a, lvl, 1, 0)
        self.assertEqual((a.x, b.x, m.x), (16, 15, 17))
        self.assertEqual(m.hp, m.max_hp)

    def test_you_never_land_in_a_pit_by_passing_someone(self):
        w, lvl, a, b = open_floor()
        lvl.tiles[17, 15] = PIT
        lvl.walkable[17, 15] = False
        w._player_move(a, lvl, 1, 0)
        self.assertEqual(a.depth, 1)
        self.assertEqual((a.x, b.x), (16, 15))

    def test_you_cant_be_passed_onto_deep_water(self):
        w, lvl, a, b = open_floor()
        lvl.tiles[17, 15] = DEEP
        lvl.walkable[17, 15] = False
        w._player_move(a, lvl, 1, 0)
        self.assertEqual((a.x, b.x), (16, 15))

    def test_a_potion_lets_you_land_on_water(self):
        w, lvl, a, b = open_floor()
        lvl.tiles[17, 15] = DEEP
        lvl.walkable[17, 15] = False
        a.waterwalk_until = w.clock + 10 ** 6
        w._player_move(a, lvl, 1, 0)
        self.assertEqual((a.x, b.x), (17, 16))

    def test_diagonals_dont_cut_a_corner_past_an_ally(self):
        w, lvl, a, b = open_floor()
        lvl.move(b, 16, 16)
        wall(lvl, 17, 16)
        w._player_move(a, lvl, 1, 1)
        self.assertEqual((a.x, a.y), (16, 16))
        self.assertEqual((b.x, b.y), (15, 15))

    def test_an_ally_over_water_is_no_bridge(self):
        w, lvl, a, b = open_floor()
        lvl.tiles[16, 15] = DEEP
        lvl.walkable[16, 15] = False
        b.levitate_until = w.clock + 10 ** 6
        w._player_move(a, lvl, 1, 0)
        self.assertEqual((a.x, b.x), (15, 16))

    def test_nor_is_a_line_of_them(self):
        w, lvl, a, b = open_floor()
        c = w.join("C")
        lvl.move(c, 17, 15)
        lvl.tiles[17, 15] = DEEP
        lvl.walkable[17, 15] = False
        c.levitate_until = w.clock + 10 ** 6
        w._player_move(a, lvl, 1, 0)
        self.assertEqual(a.x, 16)  # traded places with the first
        self.assertEqual(b.x, 15)

    def test_a_potion_lets_you_pass_over_water(self):
        w, lvl, a, b = open_floor()
        lvl.tiles[16, 15] = DEEP
        lvl.walkable[16, 15] = False
        b.levitate_until = a.waterwalk_until = w.clock + 10 ** 6
        w._player_move(a, lvl, 1, 0)
        self.assertEqual(a.x, 17)

    def test_it_says_so_if_truly_nobody_can_move(self):
        w, lvl, a, b = open_floor()
        wall(lvl, 17, 15)
        lvl.tiles[15, 15] = DEEP
        lvl.walkable[15, 15] = False
        a.waterwalk_until = w.clock + 10 ** 6
        w.drain_outbox()
        self.assertEqual(w._player_move(a, lvl, 1, 0), 0)
        self.assertIn("no way past B", str(w.drain_outbox()))

    def test_auto_walk_goes_through_an_ally_in_a_corridor(self):
        w, lvl, a, b = open_floor()
        for x in range(10, 30):
            wall(lvl, x, 14)
            wall(lvl, x, 16)
        v = ClientView()
        v.apply({"t": "welcome", "id": a.id, "name": a.name})
        v.apply(w.level_msg(1))
        v.apply(w.state_for(a))
        v.seen[1][:] = True
        self.assertEqual(v.walk_step(20, 15), (1, 0))

    def test_auto_walk_still_goes_around_monsters(self):
        w, lvl, a, b = open_floor()
        v = ClientView()
        v.apply({"t": "welcome", "id": a.id, "name": a.name})
        v.apply(w.level_msg(1))
        v.apply(w.state_for(a))
        v.seen[1][:] = True
        v.ents = [{**e, "p": e["id"] == a.id, "seen": True} for e in v.ents]
        self.assertNotEqual(v.walk_step(20, 15), (1, 0))


class QuickHealTests(unittest.TestCase):
    def setUp(self):
        self.w, self.lvl, self.p, _ = open_floor()
        self.p.pack.clear()

    def give(self, *kinds):
        for kind in kinds:
            self.p.pack.append(make_item(kind))

    def press(self):
        return self.w._quick_heal(self.p)

    def test_it_uses_the_smallest_that_fills_you_up(self):
        self.give("greater_healing", "healing")
        self.p.hp = self.p.max_hp - 10
        self.press()
        self.assertEqual([i.kind for i in self.p.pack], ["greater_healing"])
        self.assertEqual(self.p.hp, self.p.max_hp)

    def test_it_uses_the_biggest_if_none_would(self):
        self.give("healing", "greater_healing")
        self.p.hp = 1
        self.press()
        self.assertEqual([i.kind for i in self.p.pack], ["healing"])

    def test_it_ignores_other_potions(self):
        self.give("waterwalking")
        self.p.hp = 1
        self.assertEqual(self.press(), 0)
        self.assertEqual(len(self.p.pack), 1)

    def test_it_says_when_you_have_none(self):
        self.w.drain_outbox()
        self.press()
        self.assertIn("no healing potions", str(self.w.drain_outbox()))

    def test_it_wont_waste_one_at_full_health(self):
        self.give("healing")
        self.assertEqual(self.press(), 0)
        self.assertEqual(len(self.p.pack), 1)

    def test_it_works_through_a_real_action(self):
        self.give("healing")
        self.p.hp = 5
        self.p.next_time = self.w.clock
        self.w.submit(self.p, {"a": "quickheal"})
        self.assertEqual(self.p.hp, 25)


class SortTests(unittest.TestCase):
    def test_it_puts_worn_gear_then_potions_first(self):
        w, lvl, p, _ = open_floor()
        p.pack.clear()
        sword, potion, big, plate = (make_item(k) for k in ("sword", "healing", "greater_healing", "plate"))
        p.pack.extend((plate, sword, potion, big))
        p.weapon = sword
        p.next_time = w.clock
        w.submit(p, {"a": "sort"})
        self.assertEqual(p.pack, [sword, big, potion, plate])
        self.assertTrue(p.pack_dirty)

    def test_it_takes_no_time(self):
        w, lvl, p, _ = open_floor()
        p.next_time = when = w.clock
        w.submit(p, {"a": "sort"})
        self.assertEqual(p.next_time, when)


def fake_view(items=3):
    v = ClientView()
    v.pack = [{"name": f"thing{i}", "g": "!", "c": [255, 255, 255], "info": "", "eq": False} for i in range(items)]
    v.show_pack = True
    return v


class PackClickTests(unittest.TestCase):
    def rows(self, v):
        return [v.pack_slot_at((MAP_X + 40, y)) for y in range(34)]

    def test_each_row_is_its_slot(self):
        slots = [s for s in self.rows(fake_view()) if s is not None]
        self.assertEqual(slots, [0, 1, 2])

    def test_empty_slots_cant_be_clicked(self):
        self.assertEqual(max(s for s in self.rows(fake_view(2)) if s is not None), 1)

    def test_only_while_its_open(self):
        v = fake_view()
        v.show_pack = False
        self.assertEqual({s for s in self.rows(v)}, {None})

    def test_it_works_in_drop_mode(self):
        v = fake_view()
        v.show_pack, v.drop_mode = False, True
        self.assertIn(1, self.rows(v))

    def test_it_matches_where_its_drawn(self):
        v = fake_view()
        frame = v.draw()
        for y in range(34):
            slot = v.pack_slot_at((MAP_X + 40, y))
            if slot is not None:
                text = "".join(chr(c) for c in frame["ch"][:, y])
                self.assertIn(f"thing{slot}", text)


class ControlsTests(unittest.TestCase):
    def test_defaults_are_all_different_keys(self):
        keys = controls.defaults()
        ids = [controls.key_id(a, k) for a, k in keys.items()]
        self.assertEqual(len(ids), len(set(ids)))

    def test_defaults_are_wasd_and_drop_moved_off_d(self):
        keys = controls.defaults()
        self.assertEqual([keys[a] for a in ("up", "left", "down", "right")], ["W", "A", "S", "D"])
        self.assertEqual(keys["drop"], "x")

    def test_changing_a_key(self):
        keys = controls.defaults()
        self.assertEqual(controls.assign(keys, "heal", "H", "h"), "")
        self.assertEqual(keys["heal"], "h")

    def test_held_actions_keep_the_key_name(self):
        keys = controls.defaults()
        self.assertEqual(controls.assign(keys, "up", "I", "i"), "i is already Pack.")
        self.assertEqual(keys["up"], "W")
        self.assertEqual(controls.assign(keys, "up", "F", "f"), "")
        self.assertEqual(keys["up"], "F")

    def test_a_key_cant_do_two_things(self):
        keys = controls.defaults()
        self.assertIn("already Move up", controls.assign(keys, "heal", "W", "w"))
        self.assertEqual(keys["heal"], "q")

    def test_shifted_keys_are_different_keys(self):
        keys = controls.defaults()
        self.assertEqual(controls.assign(keys, "heal", "Y", "Y"), "")

    def test_a_key_that_types_nothing_goes_by_name(self):
        keys = controls.defaults()
        controls.assign(keys, "heal", "F3", "")
        self.assertEqual(keys["heal"], "F3")

    def test_space_goes_by_name(self):
        keys = controls.defaults()
        controls.assign(keys, "heal", "SPACE", " ")
        self.assertEqual(keys["heal"], "SPACE")

    def test_the_games_own_keys_are_refused(self):
        keys = controls.defaults()
        for name, text in (("RETURN", ""), ("N1", "1"), ("GRAVE", "`"), ("F2", "")):
            self.assertIn("already used", controls.assign(keys, "heal", name, text))
        self.assertEqual(keys["heal"], "q")

    def test_saved_keys_survive_a_reload(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "settings.json")
            config = settings.load(path)
            config[controls.setting("heal")] = "h"
            settings.save(config, path)
            self.assertEqual(controls.load(settings.load(path))["heal"], "h")

    def test_a_blank_saved_key_falls_back_to_the_default(self):
        self.assertEqual(controls.load({controls.setting("heal"): ""})["heal"], "q")

    def test_the_screen_shows_your_keys(self):
        v = ClientView({controls.setting("heal"): "h", controls.setting("up"): "F"})
        self.assertIn("h heal", v._key_text("{heal} heal"))
        self.assertEqual(v._key_text("{keys}"), "fasd")

    def test_long_key_names_dont_break_the_text(self):
        v = ClientView({controls.setting("up"): "PAGEUP"})
        self.assertEqual(v._key_text("{keys}"), "keys")


class MenuRowTests(unittest.TestCase):
    def test_a_tall_form_finds_rows_at_its_own_spacing(self):
        form = Form("x", [Row(str(i), action="a") for i in range(5)], top=7, step=1)
        self.assertEqual(form.row_at(9), 2)
        self.assertIsNone(form.row_at(12))

    def test_all_the_controls_fit_on_screen(self):
        self.assertLess(7 + len(controls.ACTIONS) + 2 + 2, 34)


class FakeNet:
    def __init__(self):
        self.sent = []

    def poll(self):
        return []

    def send(self, msg):
        self.sent.append(msg)


class FakeContext:
    def present(self, console, keep_aspect=True):
        pass

    def convert_event(self, event):
        return event


def key(sym, repeat=False):
    return tcod.event.KeyDown(scancode=tcod.event.Scancode.UNKNOWN, sym=sym, mod=tcod.event.Modifier.NONE, repeat=repeat)


class PlayLoopTests(unittest.TestCase):
    """Sends the real play loop the same events a keyboard would."""

    def play(self, *events, config=None):
        net = FakeNet()
        batches = iter([[], *([e] for e in events), [], [tcod.event.Quit()]])
        with mock.patch("client.tcod.event.get", lambda: next(batches)), mock.patch("client.time.sleep"):
            client.play(FakeContext(), client.new_console(), net, config=config)
        return [m for m in net.sent if m.get("t") == "act"]

    def moves(self, acts):
        return [(a["dx"], a["dy"]) for a in acts if a["a"] == "hold" and (a["dx"] or a["dy"])]

    def test_wasd_walks(self):
        for sym, step in ((KEYS.W, (0, -1)), (KEYS.A, (-1, 0)), (KEYS.S, (0, 1)), (KEYS.D, (1, 0))):
            self.assertEqual(self.moves(self.play(key(sym)))[0], step)

    def test_arrows_and_vi_keys_still_walk(self):
        self.assertEqual(self.moves(self.play(key(KEYS.UP)))[0], (0, -1))
        self.assertEqual(self.moves(self.play(key(KEYS.H)))[0], (-1, 0))

    def test_d_no_longer_opens_drop(self):
        acts = self.play(key(KEYS.D), tcod.event.TextInput(text="d"), key(KEYS.N1))
        self.assertFalse([a for a in acts if a["a"] == "drop"])

    def test_x_drops(self):
        acts = self.play(tcod.event.TextInput(text="x"), key(KEYS.N1))
        self.assertEqual([a["slot"] for a in acts if a["a"] == "drop"], [0])

    def test_q_quick_heals(self):
        self.assertIn("quickheal", [a["a"] for a in self.play(tcod.event.TextInput(text="q"))])

    def test_o_sorts(self):
        self.assertIn("sort", [a["a"] for a in self.play(tcod.event.TextInput(text="o"))])

    def test_a_changed_key_works_and_the_old_one_doesnt(self):
        config = {controls.setting("heal"): "h"}
        acts = self.play(tcod.event.TextInput(text="h"), config=config)
        self.assertIn("quickheal", [a["a"] for a in acts])
        self.assertNotIn("quickheal", [a["a"] for a in self.play(tcod.event.TextInput(text="q"), config=config)])

    def test_giving_a_fixed_move_key_a_job_takes_it_off_movement(self):
        config = {controls.setting("heal"): "h"}
        self.assertEqual(self.moves(self.play(key(KEYS.H), config=config)), [])

    def test_a_changed_move_key_works(self):
        config = {controls.setting("up"): "F"}
        self.assertEqual(self.moves(self.play(key(KEYS.F), config=config))[0], (0, -1))
        self.assertEqual(self.moves(self.play(key(KEYS.W), config=config)), [])

    def test_a_key_that_types_nothing_works(self):
        config = {controls.setting("heal"): "F3"}
        self.assertIn("quickheal", [a["a"] for a in self.play(key(KEYS.F3), config=config)])

    def test_clicking_the_pack_uses_an_item(self):
        net = FakeNet()
        down = tcod.event.MouseButtonDown(position=(0, 0), tile=(0, 0), button=tcod.event.MouseButton.LEFT)
        batches = iter([[], [down], [tcod.event.Quit()]])
        with mock.patch("client.tcod.event.get", lambda: next(batches)), mock.patch("client.time.sleep"), \
                mock.patch.object(ClientView, "pack_slot_at", lambda self, tile: 2):
            client.play(FakeContext(), client.new_console(), net)
        self.assertIn({"t": "act", "a": "use", "slot": 2}, net.sent)


if __name__ == "__main__":
    unittest.main()
