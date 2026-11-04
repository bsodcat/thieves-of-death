"""The app's menus, saved settings and the server it runs in the background."""
import os
import socket
import tempfile
import time
import unittest
from unittest import mock

import client
from game import settings
from game.constants import DIFFICULTIES, MONSTER_SWING, REVIVE_HEALTH, TICKS_PER_SECOND, TICKS_PER_TURN
from game.entities import PLAYER_COLOR_NAMES, PLAYER_GLYPHS, make_monster
from game.menu import ROW_STEP, ROW_Y, VALUE_X, Form, Row
from game.world import World
from server import ServerRunner
from togetherogue import SETUP_NOTE, lan_addresses, parse_port, parse_setup


def sample_form():
    return Form("Test", [Row("Name", "name", "Al", limit=5), Row("Port", "port", "55", digits=True, limit=5),
                         Row("Speed", "speed", "Normal", choices=("Slow", "Normal", "Fast")),
                         Row("Go", action="go")])


class FormTests(unittest.TestCase):
    def test_typing_and_backspace(self):
        f = sample_form()
        for c in "ice":
            f.handle("text", c)
        self.assertEqual(f.values()["name"], "Alice")
        f.handle("text", "x")                  # at the limit
        self.assertEqual(f.values()["name"], "Alice")
        f.handle("backspace")
        self.assertEqual(f.values()["name"], "Alic")

    def test_digit_fields_refuse_letters(self):
        f = sample_form()
        f.handle("down")
        f.handle("text", "a")
        f.handle("text", "7")
        self.assertEqual(f.values()["port"], "557")

    def test_choices_cycle_both_ways(self):
        f = sample_form()
        f.index = 2
        f.handle("right")
        self.assertEqual(f.values()["speed"], "Fast")
        f.handle("right")
        self.assertEqual(f.values()["speed"], "Slow")
        f.handle("left")
        self.assertEqual(f.values()["speed"], "Fast")
        f.handle("enter")
        self.assertEqual(f.values()["speed"], "Slow")

    def test_arrows_wrap_and_enter_presses_buttons(self):
        f = sample_form()
        f.handle("up")
        self.assertEqual(f.row.label, "Go")
        self.assertEqual(f.handle("enter"), "go")
        self.assertEqual(f.handle("back"), "back")

    def test_enter_on_a_text_field_moves_on(self):
        f = sample_form()
        self.assertIsNone(f.handle("enter"))
        self.assertEqual(f.index, 1)

    def test_typing_on_a_button_does_nothing(self):
        f = sample_form()
        f.index = 3
        f.handle("text", "a")
        f.handle("backspace")
        self.assertEqual(f.values(), sample_form().values())

    def test_mouse(self):
        f = sample_form()
        f.handle("hover", ROW_Y + ROW_STEP)
        self.assertEqual(f.index, 1)
        f.handle("hover", 0)                   # off every row
        self.assertEqual(f.index, 1)
        self.assertIsNone(f.handle("click", ROW_Y))
        self.assertEqual(f.handle("click", ROW_Y + 3 * ROW_STEP), "go")
        f.handle("click", ROW_Y + 2 * ROW_STEP)
        self.assertEqual(f.values()["speed"], "Fast")

    def test_clicking_a_choices_arrows_steps_it_either_way(self):
        f = sample_form()
        y = ROW_Y + 2 * ROW_STEP
        width = len("< Normal >")
        f.handle("click", (VALUE_X, y))                  # <
        self.assertEqual(f.values()["speed"], "Slow")
        f.handle("click", (VALUE_X, y))                  # < again wraps round
        self.assertEqual(f.values()["speed"], "Fast")
        f.handle("click", (VALUE_X + len("< Fast >") - 1, y))   # >
        self.assertEqual(f.values()["speed"], "Slow")
        f.handle("click", (VALUE_X + 3, y))              # the value itself still steps on
        self.assertEqual(f.values()["speed"], "Normal")
        self.assertEqual(f.index, 2)
        self.assertEqual(f.arrow_at(2, VALUE_X + width), 0)    # just past the >
        self.assertEqual(f.arrow_at(0, VALUE_X), 0)            # a text row has no arrows
        self.assertEqual(f.handle("click", (0, ROW_Y + 3 * ROW_STEP)), "go")

    def test_every_screen_draws(self):
        con = client.new_console()
        f = sample_form()
        f.note, f.error, f.message = "a note", "an error", "a message"
        f.draw(con)
        text = "\n".join("".join(chr(c) for c in con.rgb["ch"][:, y]) for y in range(con.height))
        for expected in ("T O G E T H E R O G U E", "Alice"[:2], "< Normal >", "Go", "an error"):
            self.assertIn(expected, text)


class SetupTests(unittest.TestCase):
    def test_ports(self):
        self.assertEqual(parse_port("5555"), 5555)
        for bad in ("", "0", "70000", "abc"):
            with self.assertRaises(ValueError):
                parse_port(bad)

    def test_setup_values(self):
        self.assertEqual(parse_setup({"port": "6000", "seed": "", "difficulty": "Medium"}), (6000, None, "Medium"))
        self.assertEqual(parse_setup({"port": "6000", "seed": "42", "difficulty": "Hard"})[1:], (42, "Hard"))
        self.assertEqual(parse_setup({"port": "6000", "seed": "", "difficulty": "Silly"})[2], "Medium")
        self.assertEqual(parse_setup({"port": "6000", "seed": ""})[2], "Medium")  # an old settings file

    def test_the_setup_screen_explains_each(self):
        for name in DIFFICULTIES:
            self.assertIn(f"{name}:", SETUP_NOTE)
        self.assertLess(max(map(len, SETUP_NOTE.splitlines())), 80)


class DifficultyTests(unittest.TestCase):
    def rat_beside(self, w):
        lvl = w.level(1)
        for m in list(lvl.monsters):
            lvl.remove(m)
        lvl.monsters.clear()
        a = w.join("A")
        rat = make_monster("rat", 900)
        rat.state = "wandering"
        lvl.place(rat, *lvl.free_near(a.x, a.y))
        lvl.monsters.append(rat)
        return a, rat

    def test_monster_speed(self):
        for name, rules in DIFFICULTIES.items():
            w = World(1, name)
            a, rat = self.rat_beside(w)
            w.advance(0)
            self.assertEqual(rat.next_time, int(TICKS_PER_TURN * MONSTER_SWING * rules["monster_time"]), name)
        self.assertGreater(DIFFICULTIES["Easy"]["monster_time"], DIFFICULTIES["Medium"]["monster_time"])
        self.assertLess(DIFFICULTIES["Hard"]["monster_time"], DIFFICULTIES["Medium"]["monster_time"])

    def test_monster_toughness(self):
        hp = {}
        for name in DIFFICULTIES:
            ogre = World(1, name)._new_monster("ogre")
            hp[name] = (ogre.max_hp, ogre.defense)
        self.assertEqual(hp["Medium"][0], make_monster("ogre", 1).max_hp)
        self.assertLess(hp["Easy"], hp["Medium"])
        self.assertGreater(hp["Hard"], hp["Medium"])

    def test_only_easy_heals_over_time(self):
        for name in DIFFICULTIES:
            w = World(1, name)
            a = w.join("A")
            a.hp = 1
            w.advance(int(30 * TICKS_PER_SECOND))
            self.assertEqual(a.hp > 1, name == "Easy", name)

    def fall(self, name):
        w = World(1, name)
        a, b = w.join("A"), w.join("B")
        lvl = w.level(1)
        lvl.move(b, *lvl.free_near(a.x, a.y))
        w._kill(b, None, "test")
        return w, a, b

    def test_revive_times(self):
        for name in ("Easy", "Medium"):
            w, a, b = self.fall(name)
            seconds = DIFFICULTIES[name]["revive"]
            self.assertTrue(b.downed, name)
            w.advance(int((seconds - 0.5) * TICKS_PER_SECOND))
            self.assertFalse(b.alive, name)
            w.advance(int(TICKS_PER_SECOND))
            self.assertTrue(b.alive, name)
            self.assertEqual(b.hp, max(1, int(b.max_hp * REVIVE_HEALTH)))

    def test_no_revives_on_hard(self):
        w, a, b = self.fall("Hard")
        self.assertFalse(b.downed)
        w.advance(int(20 * TICKS_PER_SECOND))
        self.assertFalse(b.alive)

    def test_the_host_and_server_pass_it_on(self):
        runner = ServerRunner(0, host="127.0.0.1", difficulty="Hard")
        self.addCleanup(runner.loop.close)
        self.assertEqual(runner.world.difficulty, "Hard")
        self.assertIsNone(runner.world.revive_seconds)
        self.assertEqual(settings.DEFAULTS["difficulty"], "Medium")


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "sub", "settings.json")

    def tearDown(self):
        self.dir.cleanup()

    def test_defaults_when_missing(self):
        self.assertEqual(settings.load(self.path), settings.DEFAULTS)

    def test_round_trip(self):
        config = dict(settings.DEFAULTS, name="Morgan", port="6000")
        settings.save(config, self.path)
        self.assertEqual(settings.load(self.path), config)

    def test_damaged_files_give_defaults(self):
        os.makedirs(os.path.dirname(self.path))
        for content in ("{nonsense", "[1, 2]", ""):
            with open(self.path, "w", encoding="utf-8") as f:
                f.write(content)
            self.assertEqual(settings.load(self.path), settings.DEFAULTS)

    def test_unknown_keys_are_dropped(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w", encoding="utf-8") as f:
            f.write('{"name": "Sam", "other": 1}')
        loaded = settings.load(self.path)
        self.assertEqual(loaded["name"], "Sam")
        self.assertNotIn("other", loaded)


class RunnerTests(unittest.TestCase):
    def wait_for(self, check, timeout=4.0):
        end = time.time() + timeout
        while time.time() < end:
            if check():
                return True
            time.sleep(0.02)
        return False

    def test_host_join_and_stop(self):
        runner = ServerRunner(0, seed=7, host="127.0.0.1")
        runner.start()
        self.addCleanup(runner.stop)
        self.assertGreater(runner.port, 0)
        net = client.Net("127.0.0.1", runner.port, "Hoster")
        got = []

        def poll():
            got.extend(net.poll())
            return any(m["t"] == "state" for m in got)
        self.assertTrue(self.wait_for(poll))
        self.assertTrue(self.wait_for(lambda: len(runner.status["players"]) == 1))
        self.assertEqual(runner.status["seed"], 7)
        self.assertEqual(runner.status["players"][0]["name"], "Hoster")
        self.assertTrue(any("Hoster joined" in line for line in runner.log))

        runner.stop()                          # the player finds out
        self.assertTrue(self.wait_for(lambda: any(m["t"] == "_disconnected" for m in [*got, *net.poll()])
                                      or got.extend(net.poll())))
        net.close()

    def test_chosen_look_survives_the_network(self):
        runner = ServerRunner(0, host="127.0.0.1")
        runner.start()
        self.addCleanup(runner.stop)
        for glyph in PLAYER_GLYPHS:
            net = client.Net("127.0.0.1", runner.port, f"P{ord(glyph)}", look={"glyph": glyph, "color": "Teal"})
            self.addCleanup(net.close)
        self.assertTrue(self.wait_for(lambda: len(runner.world.players) == len(PLAYER_GLYPHS)))
        self.assertEqual({p.glyph for p in runner.world.players.values()}, set(PLAYER_GLYPHS))
        self.assertEqual({p.color for p in runner.world.players.values()}, {PLAYER_COLOR_NAMES["Teal"]})

    def test_port_in_use_is_reported(self):
        first = ServerRunner(0, host="127.0.0.1")
        first.start()
        self.addCleanup(first.stop)
        second = ServerRunner(first.port, host="127.0.0.1")
        with self.assertRaises(OSError):
            second.start()

    def test_port_is_free_again_after_stopping(self):
        first = ServerRunner(0, host="127.0.0.1")
        first.start()
        port = first.port
        first.stop()
        second = ServerRunner(port, host="127.0.0.1")
        second.start()
        second.stop()
        with socket.create_server(("127.0.0.1", port)):
            pass

    def test_addresses_are_reachable_ones_with_the_real_adapter_first(self):
        found = ["192.168.56.1", "192.168.1.72", "169.254.83.107", "127.0.0.1"]
        with mock.patch("socket.gethostbyname_ex", return_value=("pc", [], found)), \
                mock.patch("togetherogue.primary_address", return_value="192.168.1.72"):
            self.assertEqual(lan_addresses(), ["192.168.1.72", "192.168.56.1"])
        with mock.patch("socket.gethostbyname_ex", side_effect=OSError), \
                mock.patch("togetherogue.primary_address", return_value=None):
            self.assertEqual(lan_addresses(), [])


if __name__ == "__main__":
    unittest.main()
