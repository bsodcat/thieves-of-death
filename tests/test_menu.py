"""The app's menus, saved settings and the server it runs in the background."""
import os
import socket
import tempfile
import time
import unittest
from unittest import mock

import client
from game import settings
from game.constants import MONSTER_TIME, TICKS_PER_TURN
from game.entities import PLAYER_COLOR_NAMES, PLAYER_GLYPHS, make_monster
from game.menu import ROW_STEP, ROW_Y, Form, Row
from game.world import World
from server import ServerRunner
from togetherogue import MONSTER_SPEEDS, lan_addresses, parse_port, parse_setup


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
        self.assertEqual(parse_setup({"port": "6000", "seed": "", "monster_speed": "Normal", "game_mode": "Classic"}),
                         (6000, None, MONSTER_TIME, "Classic"))
        self.assertEqual(parse_setup({"port": "6000", "seed": "42", "monster_speed": "Fast", "game_mode": "Revive"})[1:],
                         (42, MONSTER_SPEEDS["Fast"], "Revive"))

    def test_monster_speed_reaches_the_world(self):
        for time_scale in MONSTER_SPEEDS.values():
            w = World(1, monster_time=time_scale)
            lvl = w.level(1)
            for m in list(lvl.monsters):
                lvl.remove(m)
            lvl.monsters.clear()
            a = w.join("A")
            rat = make_monster("rat", 900)
            rat.state = "wandering"
            lvl.place(rat, *lvl.free_near(a.x, a.y))
            lvl.monsters.append(rat)
            w.advance(0)
            self.assertEqual(rat.next_time, int(TICKS_PER_TURN * time_scale))


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
