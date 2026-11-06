"""The action log: what the world notes down, the file it's saved to, and reading it in the game."""
import os
import tempfile
import unittest
from unittest import mock

import tcod.event

import client
import server
from game import commands, ledger
from game.constants import MAP_W, TICKS_PER_SECOND
from game.entities import make_monster
from game.items import make_item
from game.ledger import Ledger
from game.render import LOG_ROWS, LOG_ROWS_DEAD, WHEEL_LINES, ClientView
from game.world import World


def lines(w):
    return [m["line"] for m in w.drain_ledger() if "line" in m]


def setup(kind="ogre"):
    w = World(3)
    lvl = w.level(1)
    for m in list(lvl.monsters):
        lvl.remove(m)
    lvl.monsters.clear()
    p = w.join("A")
    m = make_monster(kind, 900)
    lvl.monsters.append(m)
    lvl.place(m, *lvl.free_near(p.x, p.y))
    w.drain_ledger()
    return w, lvl, p, m


def screen_text(frame):
    return "\n".join("".join(chr(c) for c in frame["ch"][:, y]) for y in range(frame["ch"].shape[1]))


class NotesTests(unittest.TestCase):
    def test_a_line_has_the_time_floor_and_who(self):
        w, lvl, p, m = setup()
        w.clock = w.run_start + int(3725.5 * TICKS_PER_SECOND)
        w.note(p, "did a thing")
        self.assertEqual(lines(w), ["1:02:05.5 F01 A did a thing"])

    def test_monsters_are_told_apart_by_number(self):
        w, lvl, p, m = setup()
        p.accuracy = 10 ** 6
        w._attack(p, m)
        self.assertRegex(lines(w)[0], rf"F01 A hit {m.name}#900 -\d+ .*hp \d+/{m.max_hp}$")

    def test_a_miss_says_the_odds(self):
        w, lvl, p, m = setup()
        p.accuracy = 0
        m.state = "hunting"
        w._attack(p, m)
        self.assertIn(f"A missed {m.name}#900 (0% to hit)", lines(w)[0])

    def test_a_monsters_death_says_who_did_it(self):
        w, lvl, p, m = setup()
        w._kill(m, p)
        self.assertIn(f"{m.name}#900 killed by A", lines(w)[0])

    def test_a_death_sums_up_the_character(self):
        w, lvl, p, m = setup()
        w.revive_seconds = None  # the fallen stay down, as on Hard
        p.hp = 0
        w._kill(p, m)
        last = [s for s in lines(w) if "DIED" in s][0]
        self.assertIn(f"Killed by an {m.name} on depth 1.", last)
        self.assertIn("kills", last)
        self.assertIn("gold", last)

    def test_taking_the_stairs(self):
        w, lvl, p, m = setup()
        w._take_stairs(p, 1)
        self.assertIn(f"A stairs F01->F02 hp {p.hp}/{p.max_hp}", lines(w)[0])

    def test_drinking_and_wearing_off(self):
        w, lvl, p, m = setup()
        p.pack.append(make_item("waterwalking"))
        w._use(p, len(p.pack) - 1)
        self.assertIn("A drank potion of water walking", lines(w)[0])
        p.god = True
        w.advance(int(61 * TICKS_PER_SECOND))
        self.assertTrue(any("waterwalk wore off" in s for s in lines(w)))

    def test_console_commands_are_marked(self):
        w, lvl, p, m = setup()
        p.can_command = True
        commands.run(w, p, "gold 50")
        self.assertIn("A CONSOLE gold 50", lines(w)[0])

    def test_a_refused_command_isnt_noted(self):
        w, lvl, p, m = setup()
        commands.run(w, p, "gold 50")
        self.assertEqual(lines(w), [])

    def test_a_new_run_starts_a_new_log(self):
        w, lvl, p, m = setup()
        w.reset_run()
        heads = [msg for msg in w.drain_ledger() if "head" in msg]
        self.assertEqual([h["run"] for h in heads], [2])
        self.assertEqual(heads[0]["seed"], w.seed)
        w.note(p, "again")
        self.assertTrue(lines(w)[0].startswith("0:00:00.0 "))

    def test_the_head_names_the_version_seed_and_difficulty(self):
        head = World(3).ledger_head()["head"]
        self.assertRegex(head, r"^Togetherogue \d+\.\d+\.\d+ \| run 1 \| seed 3 \| Medium$")

    def test_noting_changes_nothing_in_the_game(self):
        def play(noted):
            w, lvl, p, m = setup()
            if not noted:
                w.note = lambda *a, **k: None
            p.accuracy = 50
            for _ in range(20):
                if m.hp > 0:
                    w._attack(p, m)
            return m.hp, w.rng.random()
        self.assertEqual(play(True), play(False))


class FileTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = os.path.join(folder.name, "logs")
        self.ledger = Ledger(self.folder)

    @staticmethod
    def head(run=1, seed=5):
        return {"t": "log", "run": run, "seed": seed, "head": f"Togetherogue | run {run}"}

    def read(self):
        with open(self.ledger.path, encoding="utf-8") as f:
            return f.read()

    def test_a_run_gets_a_file_with_a_legend(self):
        self.ledger.apply(self.head())
        self.ledger.apply({"t": "log", "line": "0:00:01.0 F01 A hit something"})
        text = self.read()
        self.assertTrue(text.startswith("# Togetherogue | run 1\n# time since"))
        self.assertTrue(text.endswith("0:00:01.0 F01 A hit something\n"))
        self.assertRegex(os.path.basename(self.ledger.path), r"^\d{4}-\d\d-\d\d_\d\d-\d\d-\d\d_seed5\.txt$")

    def test_each_line_is_on_disk_right_away(self):
        self.ledger.apply(self.head())
        self.ledger.apply({"t": "log", "line": "one"})
        self.assertIn("one", self.read())

    def test_being_told_the_head_twice_changes_nothing(self):
        self.ledger.apply(self.head())
        path = self.ledger.path
        self.ledger.apply(self.head())
        self.assertEqual(self.ledger.path, path)
        self.assertEqual(self.read().count("Togetherogue"), 1)

    def test_a_new_run_gets_a_new_file(self):
        self.ledger.apply(self.head())
        first = self.ledger.path
        with mock.patch("game.ledger.time.strftime", return_value="later"):
            self.ledger.apply(self.head(2, 6))
        self.assertNotEqual(self.ledger.path, first)
        self.assertEqual(len(os.listdir(self.folder)), 2)

    def test_old_logs_are_cleared_out(self):
        os.makedirs(self.folder)
        for i in range(ledger.KEEP_FILES + 3):
            open(os.path.join(self.folder, f"2000-01-01_{i:04d}.txt"), "w").close()
        self.ledger.apply(self.head())
        names = os.listdir(self.folder)
        self.assertEqual(len(names), ledger.KEEP_FILES)
        self.assertNotIn("2000-01-01_0000.txt", names)
        self.assertIn(os.path.basename(self.ledger.path), names)

    def test_other_messages_are_ignored(self):
        self.ledger.apply({"t": "msg", "text": "hello"})
        self.assertEqual(self.ledger.path, "")

    def test_lines_before_a_head_go_nowhere(self):
        self.ledger.apply({"t": "log", "line": "one"})
        self.assertFalse(os.path.exists(self.folder))

    def test_failing_to_write_doesnt_stop_the_game(self):
        with mock.patch("builtins.open", side_effect=OSError):
            self.ledger.apply(self.head())
            self.ledger.apply({"t": "log", "line": "one"})

    def test_a_dedicated_server_saves_its_own(self):
        w = World(3)
        game = server.GameServer(w, self.ledger)
        p = w.join("A")
        game.flush()
        self.assertIn("A joined", self.read())

    def test_the_app_leaves_saving_to_the_players(self):
        w = World(3)
        game = server.GameServer(w)
        w.join("A")
        game.flush()
        self.assertEqual(w.ledger, [])

    def test_a_game_bug_goes_in_the_log(self):
        w = World(3)
        game = server.GameServer(w, self.ledger)
        game.flush()
        try:
            raise ValueError("it broke")
        except ValueError:
            game.note_error(4)
        game.flush()
        self.assertRegex(self.read(), r"F04 ERROR .*ValueError: it broke")


class WheelEventTests(unittest.TestCase):
    def test_a_real_wheel_event_reaches_the_panel(self):
        seen = {}

        class Net:
            def poll(self):
                return []

            def send(self, msg):
                pass

        class Fake:
            def present(self, *a, **k):
                pass

            def new_console(self, *a, **k):
                return client.new_console()

        wheel = tcod.event.MouseWheel(x=0, y=1, flipped=False)
        real = ClientView.wheel

        def spy(view, notches):
            seen["notches"] = notches
            real(view, notches)
        with mock.patch("tcod.event.get", side_effect=[[wheel], [tcod.event.Quit()]]), \
                mock.patch.object(ClientView, "wheel", spy):
            client.play(Fake(), client.new_console(), Net())
        self.assertEqual(seen["notches"], 1)


class ViewTests(unittest.TestCase):
    def view(self, count=3):
        w, lvl, p, m = setup()
        v = ClientView()
        v.apply({"t": "welcome", "id": p.id, "name": p.name})
        v.apply(w.level_msg(p.depth))
        v.apply(w.state_for(p))
        v.apply(w.ledger_head())
        for i in range(count):
            v.apply({"t": "log", "line": f"0:00:0{i % 10}.0 F01 A line{i:04d}"})
        return v

    def test_it_stays_hidden_until_asked_for(self):
        self.assertNotIn("line0001", screen_text(self.view().draw()))

    def test_v_shows_the_lines_and_where_they_are_saved(self):
        v = self.view()
        v.log_path = r"C:\logs\run.txt"
        v.toggle_log()
        text = screen_text(v.draw())
        self.assertIn("Action log", text)
        self.assertIn("line0002", text)
        self.assertIn(r"C:\logs\run.txt", text)

    def test_it_shows_the_newest_lines_first(self):
        v = self.view(100)
        v.toggle_log()
        text = screen_text(v.draw())
        self.assertIn("line0099", text)
        self.assertNotIn("line0050", text)

    def test_scrolling_up_reaches_the_oldest_and_stops(self):
        v = self.view(100)
        v.toggle_log()
        for _ in range(50):
            v.scroll_log(1)
        text = screen_text(v.draw())
        self.assertIn("line0000", text)
        self.assertNotIn("line0099", text)
        self.assertEqual(v.log_back, len(v.log) - LOG_ROWS)
        for _ in range(50):
            v.scroll_log(-1)
        self.assertEqual(v.log_back, 0)

    def test_the_wheel_scrolls_the_log(self):
        v = self.view(100)
        v.toggle_log()
        v.wheel(2)
        self.assertEqual(v.log_back, 2 * WHEEL_LINES)
        v.wheel(-1)
        self.assertEqual(v.log_back, WHEEL_LINES)
        v.wheel(-5)
        self.assertEqual(v.log_back, 0)

    def test_the_wheel_does_nothing_with_the_log_shut(self):
        v = self.view(100)
        v.wheel(2)
        self.assertEqual(v.log_back, 0)

    def console_view(self, count=40):
        v = self.view()
        v.console_open = True
        for i in range(count):
            v.apply({"t": "console", "text": f"out{i:04d}", "c": [255, 255, 255]})
        return v

    def test_the_wheel_scrolls_the_console(self):
        v = self.console_view()
        self.assertIn("out0039", screen_text(v.draw()))
        for _ in range(20):
            v.wheel(1)
        text = screen_text(v.draw())
        self.assertIn("out0000", text)
        self.assertNotIn("out0039", text)
        for _ in range(20):
            v.wheel(-1)
        self.assertIn("out0039", screen_text(v.draw()))

    def test_the_console_wins_over_the_log(self):
        v = self.console_view()
        v.show_log = True
        v.wheel(1)
        self.assertEqual((v.console_scroll, v.log_back), (WHEEL_LINES, 0))

    def test_a_short_console_doesnt_scroll(self):
        v = self.console_view(3)
        v.wheel(1)
        self.assertEqual(v.console_scroll, 0)

    def test_new_console_lines_dont_move_what_youre_reading(self):
        v = self.console_view()
        v.wheel(1)
        before = screen_text(v.draw())
        v.apply({"t": "console", "text": "newest", "c": [255, 255, 255]})
        self.assertEqual(screen_text(v.draw()), before)

    def test_running_a_command_returns_to_the_newest(self):
        v = self.console_view()
        v.wheel(1)
        v.console_buf = "heal"
        v.console_submit()
        self.assertEqual(v.console_scroll, 0)

    def test_a_short_log_doesnt_scroll(self):
        v = self.view()
        v.toggle_log()
        v.scroll_log(1)
        self.assertEqual(v.log_back, 0)

    def test_new_lines_dont_move_what_youre_reading(self):
        v = self.view(100)
        v.toggle_log()
        v.scroll_log(1)
        before = screen_text(v.draw())
        v.apply({"t": "log", "line": "0:00:09.0 F01 A newest"})
        self.assertEqual(screen_text(v.draw()), before)

    def test_a_new_run_starts_clean(self):
        v = self.view()
        v.apply({"t": "log", "run": 2, "seed": 9, "head": "Run two"})
        self.assertEqual(list(v.log), ["Run two"])

    def test_being_told_the_head_twice_changes_nothing(self):
        v = self.view()
        before = list(v.log)
        v.apply({"t": "log", "run": 1, "seed": 3, "head": before[0]})
        self.assertEqual(list(v.log), before)

    def test_it_can_be_read_after_dying(self):
        v = self.view()
        v.alive = False
        v.death = "Killed."
        self.assertIn("Press v", screen_text(v.draw()))
        v.toggle_log()
        self.assertIn("line0002", screen_text(v.draw()))

    def test_its_taller_once_youre_dead(self):
        v = self.view(100)
        v.alive = False
        v.toggle_log()
        text = screen_text(v.draw())
        self.assertIn(f"line{100 - LOG_ROWS_DEAD:04d}", text)
        self.assertNotIn(f"line{100 - LOG_ROWS_DEAD - 1:04d}", text)

    def test_its_short_while_waiting_to_be_revived(self):
        v = self.view(100)
        v.alive, v.downed = False, True
        self.assertEqual(v.log_rows(), LOG_ROWS)

    def test_other_panels_close_it(self):
        v = self.view()
        v.toggle_log()
        v.toggle_help()
        self.assertFalse(v.show_log)
        v.toggle_log()
        self.assertFalse(v.show_help)

    def test_it_fits_inside_the_map(self):
        v = self.view(100)
        v.log_path = "x" * 500
        v.toggle_log()
        text = screen_text(v.draw())
        self.assertIn("..." + "x" * (MAP_W - 7), text)  # the end is the part that differs
        self.assertNotIn("x" * (MAP_W - 6), text)


if __name__ == "__main__":
    unittest.main()
