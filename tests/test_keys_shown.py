"""Bugs found by playing 2.9.0 in the real game: killall while down, and text that got cut off or
showed the default keys."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game import commands
from game.constants import MAP_W, SCREEN_H, SCREEN_W
from game.items import make_item
from game.render import HELP_TIPS, LOG_ROWS, ClientView
from game.world import World


def screen_text(frame) -> str:
    return "\n".join("".join(chr(frame["ch"][x, y]) for x in range(SCREEN_W)) for y in range(SCREEN_H))


class KillallTests(unittest.TestCase):
    def setUp(self):
        self.w = World(7, mode="Revive")
        self.down, self.other = self.w.join("Down"), self.w.join("Other")
        self.lvl = self.w.levels[self.down.depth]
        self.lvl.monsters.clear()

    def test_it_kills_everything_when_the_player_is_down(self):
        commands.spawn(self.w, self.other, ["rat", "3"])
        self.w._kill(self.down, None, "Test.")
        self.w.drain_outbox()
        commands.killall(self.w, self.down, [])
        self.assertEqual(self.lvl.monsters, [])
        texts = [m.get("text", "") for _, m in self.w.drain_outbox()]
        self.assertIn("The rat dies.", texts)

    def test_no_kill_is_credited_without_a_killer(self):
        commands.spawn(self.w, self.other, ["rat"])
        self.w._kill(self.down, None, "Test.")
        commands.killall(self.w, self.down, [])
        self.assertEqual((self.down.kills, self.other.kills), (0, 0))

    def test_a_living_player_still_gets_the_credit(self):
        commands.spawn(self.w, self.other, ["rat"])
        commands.killall(self.w, self.other, [])
        self.assertEqual(self.other.kills, 1)


class PackTests(unittest.TestCase):
    @staticmethod
    def pack(name, info):
        v = ClientView()
        v.pack = [{"g": "!", "c": [255, 60, 90], "name": name, "info": info, "eq": False}]
        v.show_pack = True
        return screen_text(v.draw())

    def test_a_long_name_keeps_its_count(self):
        self.assertIn("potion of greater healing x2", self.pack("potion of greater healing x2", "heals 40"))

    def test_the_name_never_runs_into_its_note(self):
        self.assertIn("n jump to a random floor", self.pack("n" * 60, "jump to a random floor"))

    def test_the_shop_shows_whole_names(self):
        v = ClientView()
        v.shop_name = "merchant"
        v.shop = [{"id": 1, "g": "!", "c": [255, 60, 90], "name": "potion of greater healing", "info": "heals 40",
                   "price": 1200}]
        self.assertIn("potion of greater healing", screen_text(v.draw()))


class LogPanelTests(unittest.TestCase):
    PATH = "C:\\Users\\bsodcat\\AppData\\Roaming\\Togetherogue\\logs\\2026-11-01_22-04-24_seed1343292355.txt"

    @staticmethod
    def view(*lines):
        v = ClientView()
        v.log.extend(lines)
        v.toggle_log()
        return v

    def test_a_long_line_wraps_and_stays_whole(self):
        tail = "wearing plate armor of warding and a very long enchanted sword of something"
        line = "0:07:32.4 F01 Hosty DOWN: Killed by an ogre on depth 1. 7 kills, 0 gold, " + tail
        self.assertIn(tail, " ".join(screen_text(self.view(line).draw()).split()))

    def test_wrapped_lines_keep_their_color_and_indent(self):
        rows = self.view("0:07:32.4 F01 Hosty DOWN: " + "word " * 30)._log_lines(LOG_ROWS, MAP_W - 4)
        self.assertGreater(len(rows), 1)
        self.assertEqual(len({color for _, color in rows}), 1)
        self.assertTrue(rows[1][0].startswith(" " * 10))

    def test_following_the_log_shows_the_newest_line(self):
        lines = [f"line{i:02} " + "word " * 30 for i in range(LOG_ROWS)]
        self.assertIn("the newest", screen_text(self.view(*lines, "the newest").draw()))

    def test_scrolled_back_shows_the_oldest_line(self):
        v = self.view("the oldest", *(f"line{i:02} " + "word " * 30 for i in range(LOG_ROWS * 2)))
        for _ in range(20):
            v.scroll_log(1)
        self.assertIn("the oldest", screen_text(v.draw()))

    def test_a_long_path_keeps_the_file_name(self):
        v = self.view("x")
        v.log_path = self.PATH
        self.assertIn("2026-11-01_22-04-24_seed1343292355.txt", screen_text(v.draw()))
        self.assertEqual(len(v._log_where(MAP_W - 4)), MAP_W - 4)

    def test_a_short_path_is_left_alone(self):
        v = self.view("x")
        v.log_path = "C:\\logs\\run.txt"
        self.assertEqual(v._log_where(MAP_W - 4), v.log_path)


class YourOwnKeysTests(unittest.TestCase):
    @staticmethod
    def view(**keys):
        return ClientView({f"key_{action}": key for action, key in keys.items()})

    @staticmethod
    def help_text(v):
        v.show_help = True
        return screen_text(v.draw())

    def test_the_help_title_shows_your_key(self):
        self.assertIn("h or Esc closes", self.help_text(self.view(help="h")))

    def test_defaults_are_unchanged(self):
        text = self.help_text(self.view())
        self.assertIn("? or Esc closes", text)
        self.assertIn("Arrows, wasd, hjklyubn", text)

    def test_a_letter_given_another_job_no_longer_says_it_walks(self):
        self.assertIn("Arrows, wasd, jklyubn", self.help_text(self.view(help="h")))

    def test_no_letters_left_leaves_no_stray_comma(self):
        keys = dict(zip(("help", "pack", "tally", "log", "drop", "sort", "heal", "pickup"), "hjklyubn"))
        self.assertIn("Arrows, wasd  ", self.help_text(self.view(**keys)))

    def test_tips_show_your_keys(self):
        v = self.view(pickup="SPACE", sprint="C")
        v.tip = next(t for t in HELP_TIPS if "{pickup}" in t)
        self.assertIn("Gear needs Space.", self.help_text(v))
        v.tip = next(t for t in HELP_TIPS if "{sprint}" in t)
        self.assertIn("Hold c to sprint", self.help_text(v))

    def test_the_look_panel_shows_your_key(self):
        item = {"g": ")", "c": [1, 2, 3], "name": "sword", "info": ""}
        self.assertEqual(self.view(pickup="SPACE")._describe_item(item, True)[-1][0], "Stand on it and press Space.")

    def test_the_hint_line_fits(self):
        for v in (ClientView(), self.view(pickup="SPACE", help="h")):
            self.assertIn(f" {v.keys['quit']} quit", screen_text(v.draw()))

    def test_the_server_says_your_pickup_key(self):
        w = World(7)
        p = w.join("A")
        lvl = w.levels[p.depth]
        p.pickup_key = "Space"
        lvl.items[(p.x, p.y)] = make_item("sword")
        w.drain_outbox()
        w._step_onto(p, lvl)
        self.assertTrue(any("Press Space to pick it up" in m.get("text", "") for _, m in w.drain_outbox()))

    def test_a_bad_key_from_a_client_gets_the_default(self):
        for bad in (None, 5, "", "x" * 13, "a\nb", ["g"]):
            self.assertEqual(World.clean_key(bad), "g")
        self.assertEqual(World.clean_key("Space"), "Space")


if __name__ == "__main__":
    unittest.main()
