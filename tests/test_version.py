"""The version shown on the title screen, and refusing players on another version."""
import re
import socket
import time
import unittest

import client
from game import protocol
from game.constants import PROTOCOL_VERSION, SCREEN_H, SCREEN_W
from game.menu import Form, Row
from game.render import ClientView
from game.version import AUTHOR, RELEASE_DATE, VERSION
from server import ServerRunner
from togetherogue import title_footer


def rows_of(console):
    return ["".join(chr(c) for c in console.rgb["ch"][:, y]) for y in range(console.height)]


class TitleTests(unittest.TestCase):
    def test_version_looks_like_a_version(self):
        self.assertRegex(VERSION, r"^\d+\.\d+\.\d+$")

    def test_footer_says_everything(self):
        footer = title_footer()
        for part in (VERSION, RELEASE_DATE, "Made by bsodcat"):
            self.assertIn(part, footer)
        self.assertEqual(AUTHOR, "bsodcat")

    def test_footer_is_at_the_bottom_and_centered(self):
        con = client.new_console()
        form = Form("", [Row("Quit", action="quit")])
        form.footer = title_footer()
        form.draw(con)
        rows = rows_of(con)
        line = rows[SCREEN_H - 2]
        self.assertIn("Made by bsodcat", line)
        left = len(line) - len(line.lstrip())
        right = len(line) - len(line.rstrip())
        self.assertLessEqual(abs(left - right), 1)

    def test_other_screens_dont_show_it(self):
        con = client.new_console()
        Form("Options", [Row("Back", action="back")]).draw(con)
        self.assertNotIn("Made by", "\n".join(rows_of(con)))

    def test_footer_fits(self):
        self.assertLess(len(title_footer()), SCREEN_W)


class VersionCheckTests(unittest.TestCase):
    def setUp(self):
        self.runner = ServerRunner(0, host="127.0.0.1")
        self.runner.start()
        self.addCleanup(self.runner.stop)

    def hello(self, **fields):
        sock = socket.create_connection(("127.0.0.1", self.runner.port), timeout=3)
        self.addCleanup(sock.close)
        sock.sendall(protocol.encode({"t": "hello", "name": "Old", **fields}))
        return sock.makefile("r", encoding="utf-8")

    def test_old_copy_is_told_why_and_never_joins(self):
        f = self.hello(version=PROTOCOL_VERSION - 1)
        msg = protocol.decode(f.readline())
        self.assertEqual(msg["t"], "reject")
        self.assertIn(VERSION, msg["text"])
        self.assertEqual(f.readline(), "")     # hung up
        self.assertEqual(self.runner.world.players, {})

    def test_refusal_is_logged_for_the_server_tool(self):
        self.hello(version=1).readline()
        time.sleep(0.1)
        self.assertTrue(any("wrong version" in line for line in self.runner.log))

    def test_matching_copy_joins(self):
        f = self.hello(version=PROTOCOL_VERSION)
        self.assertEqual(protocol.decode(f.readline())["t"], "welcome")

    def test_the_real_client_is_accepted(self):
        net = client.Net("127.0.0.1", self.runner.port, "Real")
        self.addCleanup(net.close)
        end = time.time() + 3
        while time.time() < end and not self.runner.world.players:
            time.sleep(0.02)
        self.assertEqual(len(self.runner.world.players), 1)

    def test_client_shows_the_reason_then_disconnects(self):
        v = ClientView()
        f = self.hello(version=0)
        v.apply(protocol.decode(f.readline()))
        v.apply({"t": "_disconnected"})
        self.assertTrue(any("same version" in text for text, _ in v.messages))
        self.assertFalse(v.connected)


if __name__ == "__main__":
    unittest.main()
