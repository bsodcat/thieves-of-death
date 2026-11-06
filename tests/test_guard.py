"""Keeping an open server safe: the join password, the player cap and the rate limits."""
import socket
import time
import unittest
from unittest import mock

import client
import togetherogue
from game import protocol, settings
from game.constants import (CHAT_BURST, FLOOD_STRIKES, JOIN_BURST, MAX_LINE, MAX_PLAYERS, MSG_BURST,
                            PROTOCOL_VERSION)
from game.world import World
from server import Bucket, GameServer, ServerRunner, password_matches


class Raw:
    """A bare connection, so a test can send what the real client never would."""

    def __init__(self, port, name="Raw", **hello):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=5)
        self.file = self.sock.makefile("r", encoding="utf-8")
        self.send({"t": "hello", "name": name, "version": PROTOCOL_VERSION, **hello})

    def send(self, msg):
        self.sock.sendall(protocol.encode(msg))

    def read_until(self, pred, timeout=5.0):
        """The first message that passes, or None if the server hangs up first."""
        end = time.time() + timeout
        while time.time() < end:
            line = self.file.readline()
            if not line:
                return None
            msg = protocol.decode(line)
            if pred(msg):
                return msg
        raise AssertionError("timed out")

    def first(self):
        return self.read_until(lambda m: m["t"] in ("welcome", "reject"))

    def close(self):
        self.file.close()
        self.sock.close()


def wait_for(cond, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end and not cond():
        time.sleep(0.02)
    return cond()


class BucketTests(unittest.TestCase):
    def test_a_burst_then_nothing(self):
        b = Bucket(1, 3, now=0)
        self.assertEqual([b.take(0) for _ in range(4)], [True, True, True, False])

    def test_refills_at_its_rate(self):
        b = Bucket(2, 2, now=0)
        b.take(0), b.take(0)
        self.assertFalse(b.take(0.2))
        self.assertTrue(b.take(0.5))

    def test_never_holds_more_than_its_burst(self):
        b = Bucket(10, 2, now=0)
        self.assertEqual([b.take(100) for _ in range(3)], [True, True, False])


class PasswordTests(unittest.TestCase):
    def setUp(self):
        self.runner = ServerRunner(0, host="127.0.0.1", password="open sesame")
        self.runner.start()
        self.addCleanup(self.runner.stop)

    def join(self, **hello):
        c = Raw(self.runner.port, **hello)
        self.addCleanup(c.close)
        return c

    def test_the_right_password_joins(self):
        self.assertEqual(self.join(password="open sesame").first()["t"], "welcome")

    def test_a_wrong_one_is_told_and_never_joins(self):
        c = self.join(password="open sesame!")
        msg = c.first()
        self.assertEqual(msg["t"], "reject")
        self.assertIn("Wrong password", msg["text"])
        self.assertIsNone(c.read_until(lambda m: True))   # hung up
        self.assertEqual(self.runner.world.players, {})

    def test_none_at_all_is_told_there_is_one(self):
        msg = self.join().first()
        self.assertIn("has a password", msg["text"])

    def test_a_wrong_guess_waits_first(self):
        start = time.monotonic()
        self.join(password="guess").first()
        self.assertGreaterEqual(time.monotonic() - start, 0.9)

    def test_it_is_logged_for_the_server_tool(self):
        self.join(password="guess").first()
        self.assertTrue(wait_for(lambda: any("wrong password" in line for line in self.runner.log)))

    def test_the_host_needs_it_too(self):
        """A tunnel such as playit or ngrok can make a stranger look local."""
        self.assertIn("password", self.join(name="Host").first()["text"])

    def test_the_real_client_sends_it(self):
        net = client.Net("127.0.0.1", self.runner.port, "Real", password="open sesame")
        self.addCleanup(net.close)
        self.assertTrue(wait_for(lambda: len(self.runner.world.players) == 1))

    def test_a_server_without_one_lets_anyone_in(self):
        runner = ServerRunner(0, host="127.0.0.1")
        runner.start()
        self.addCleanup(runner.stop)
        c = Raw(runner.port, password="whatever")
        self.addCleanup(c.close)
        self.assertEqual(c.first()["t"], "welcome")

    def test_matching_is_exact(self):
        self.assertTrue(password_matches("abc", "abc"))
        for wrong in ("ABC", "abc ", "", None, 123, ["abc"]):
            self.assertFalse(password_matches(wrong, "abc"), wrong)


class PlayerCapTests(unittest.TestCase):
    def test_six_by_default(self):
        self.assertEqual(MAX_PLAYERS, 6)
        self.assertEqual(ServerRunner(0).game.max_players, 6)

    def test_the_seventh_is_turned_away(self):
        runner = ServerRunner(0, host="127.0.0.1")
        runner.start()
        self.addCleanup(runner.stop)
        players = []
        for i in range(MAX_PLAYERS):
            c = Raw(runner.port, f"P{i}")
            self.addCleanup(c.close)
            self.assertEqual(c.first()["t"], "welcome")
            players.append(c)
        extra = Raw(runner.port, "Seventh")
        self.addCleanup(extra.close)
        msg = extra.first()
        self.assertEqual(msg["t"], "reject")
        self.assertIn("full", msg["text"])
        self.assertEqual(len(runner.world.players), MAX_PLAYERS)

        players[0].close()   # a seat comes free
        self.assertTrue(wait_for(lambda: len(runner.game.writers) == MAX_PLAYERS - 1))
        late = Raw(runner.port, "Late")
        self.addCleanup(late.close)
        self.assertEqual(late.first()["t"], "welcome")


class RateLimitTests(unittest.TestCase):
    def setUp(self):
        self.runner = ServerRunner(0, host="127.0.0.1")
        self.runner.start()
        self.addCleanup(self.runner.stop)
        self.c = Raw(self.runner.port, "Spammer")
        self.addCleanup(self.c.close)
        self.assertEqual(self.c.first()["t"], "welcome")

    def test_a_flood_is_cut_off(self):
        line = protocol.encode({"t": "act", "a": "move", "dx": 1, "dy": 0})
        self.c.sock.sendall(line * (MSG_BURST + FLOOD_STRIKES + 50))
        msg = self.c.read_until(lambda m: m["t"] == "reject", timeout=10)
        self.assertIn("too many", msg["text"])
        self.assertTrue(wait_for(lambda: not self.runner.game.writers))
        self.assertTrue(any("sending too much" in line for line in self.runner.log))

    def test_a_burst_within_the_limit_is_fine(self):
        self.c.sock.sendall(protocol.encode({"t": "pong", "n": 0}) * (MSG_BURST - 2))
        self.c.send({"t": "chat", "text": "still here"})
        self.assertIsNotNone(self.c.read_until(lambda m: m["t"] == "msg" and "still here" in m["text"]))
        self.assertEqual(len(self.runner.game.writers), 1)

    def test_chat_spam_is_held_back(self):
        for i in range(CHAT_BURST + 3):
            self.c.send({"t": "chat", "text": f"spam {i}"})
        self.c.send({"t": "chat", "text": "spam last"})
        seen, warned = [], 0
        while True:
            msg = self.c.read_until(lambda m: m["t"] == "msg", timeout=3)
            if "chatting too fast" in msg["text"]:
                warned += 1
                if warned == 4:
                    break
            elif "spam" in msg["text"]:
                seen.append(msg["text"])
        self.assertEqual(len(seen), CHAT_BURST)
        self.assertEqual(len(self.runner.game.writers), 1)   # warned, not dropped

    def test_a_huge_line_hangs_up(self):
        self.c.sock.sendall(b'{"t":"chat","text":"' + b"x" * (MAX_LINE * 2) + b'"}\n')
        self.assertIsNone(self.c.read_until(lambda m: m["t"] == "reject"))
        self.assertTrue(wait_for(lambda: not self.runner.game.writers))


class JoinRateTests(unittest.TestCase):
    def test_one_address_cant_keep_joining(self):
        game = GameServer(World(1))
        stranger = ("203.0.113.5", 40000)
        self.assertEqual([game.may_join(stranger) for _ in range(JOIN_BURST + 1)], [True] * JOIN_BURST + [False])
        self.assertTrue(game.may_join(("198.51.100.7", 40001)))   # others aren't held up by it

    def test_this_computer_is_never_limited(self):
        game = GameServer(World(1))
        self.assertTrue(all(game.may_join(("127.0.0.1", 5)) for _ in range(JOIN_BURST * 3)))

    def test_old_addresses_are_forgotten(self):
        game = GameServer(World(1))
        for i in range(1001):
            game.joins[f"10.0.{i // 256}.{i % 256}"] = Bucket(1, 5, now=0)
        game.may_join(("203.0.113.5", 1))
        self.assertLess(len(game.joins), 10)


class MenuTests(unittest.TestCase):
    def setUp(self):
        saver = mock.patch("togetherogue.settings.save")   # never touch the real settings file
        self.addCleanup(saver.stop)
        saver.start()
        context = mock.Mock()   # stands in for the window
        self.app = togetherogue.App(context, client.new_console(), dict(settings.DEFAULTS, host_password="pw"))

    def script(self, *actions):
        forms, answers = [], iter(actions)

        def show(form, extra=None, timeout=None):
            forms.append(form)
            return next(answers)
        self.app.show = show
        return forms

    def test_no_password_by_default(self):
        self.assertEqual(settings.DEFAULTS["host_password"], "")
        self.assertEqual(settings.DEFAULTS["join_password"], "")

    def test_host_and_server_tool_pass_it_on(self):
        for screen in ("host_game", "server_tool"):
            forms = self.script("go", "back")
            with mock.patch("togetherogue.ServerRunner") as runner:
                runner.return_value.start.side_effect = OSError
                getattr(self.app, screen)()
            self.assertEqual(runner.call_args.kwargs["password"], "pw", screen)
            self.assertIn("host_password", forms[0].values())

    def test_join_sends_it(self):
        self.app.config["join_password"] = "theirs"
        self.script("go", "back")
        with mock.patch("togetherogue.client.Net", side_effect=OSError) as net:
            self.app.join_game()
        self.assertEqual(net.call_args.kwargs["password"], "theirs")

    def test_the_forms_fit_on_screen(self):
        from game.constants import SCREEN_H, SCREEN_W
        for screen in ("host_game", "server_tool", "join_game"):
            forms = self.script("back")
            getattr(self.app, screen)()
            form = forms[0]
            lines = form.note.splitlines()
            self.assertLess(form.top + len(form.rows) * form.step + len(lines) + 2, SCREEN_H, screen)
            self.assertLess(26 + max(map(len, lines)), SCREEN_W, screen)


if __name__ == "__main__":
    unittest.main()
