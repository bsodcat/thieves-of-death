"""Bot teammates from the test console: enable bot and disable bot."""
import socket
import time
import unittest

from game import algo, bots, commands, protocol
from game.constants import PROTOCOL_VERSION, TICKS_PER_SECOND
from game.world import World, cheb
from server import ServerRunner


def host(seed=3, difficulty="Medium"):
    w = World(seed, difficulty)
    p = w.join("Host")
    p.can_command = True
    return w, p


def run(w, p, text):
    """The lines a command sends back to that player's console."""
    w.drain_outbox()
    commands.run(w, p, text)
    return [m["text"] for pid, m in w.drain_outbox() if pid == p.id and m["t"] == "console"]


def clear_monsters(w, depth):
    for m in list(w.levels[depth].monsters):
        w._kill(m, None)


def play(w, seconds):
    """Runs the game the way the server does: bots think, then the clock moves on."""
    for _ in range(int(seconds * 30)):
        bots.step(w)
        w.advance(TICKS_PER_SECOND // 30 or 1)


class CommandTests(unittest.TestCase):
    def test_enable_bot_adds_one(self):
        w, p = host()
        lines = run(w, p, "enable bot")
        self.assertIn("Added Bot", lines[0])
        self.assertEqual(len(w.bots), 1)
        bot = w.players[next(iter(w.bots))]
        self.assertEqual(bot.name, "Bot")
        self.assertTrue(bot.auto_attack)
        self.assertEqual(bot.depth, p.depth)

    def test_a_count_adds_several(self):
        w, p = host()
        run(w, p, "enable bot 3")
        self.assertEqual(sorted(w.players[b].name for b in w.bots), ["Bot", "Bot2", "Bot3"])

    def test_no_more_than_five(self):
        w, p = host()
        run(w, p, "enable bot 3")
        lines = run(w, p, "enable bot 4")
        self.assertIn("at most 5", lines[0])
        self.assertEqual(len(w.bots), bots.MAX_BOTS)
        self.assertIn("already 5 bots", run(w, p, "enable bot")[0])

    def test_disable_bot_removes_them_all(self):
        w, p = host()
        run(w, p, "enable bot 2")
        lines = run(w, p, "disable bot")
        self.assertIn("Removed Bot, Bot2", lines[0])
        self.assertEqual(w.bots, {})
        self.assertEqual(list(w.players.values()), [p])
        self.assertNotIn("Bot", w.offline)   # gone for good, not waiting to come back

    def test_disable_with_none_says_so(self):
        w, p = host()
        self.assertIn("no bots", run(w, p, "disable bot")[0])

    def test_short_forms_work(self):
        w, p = host()
        run(w, p, "ena b")
        self.assertEqual(len(w.bots), 1)
        run(w, p, "dis bot")
        self.assertEqual(w.bots, {})

    def test_usage_without_bot(self):
        w, p = host()
        self.assertIn("enable bot [count]", run(w, p, "enable")[0])
        self.assertIn("disable bot", run(w, p, "disable")[0])

    def test_a_bad_count_is_refused(self):
        w, p = host()
        self.assertIn("number from 1 to 5", run(w, p, "enable bot 0")[0])
        self.assertEqual(w.bots, {})

    def test_only_the_host_can(self):
        w, p = host()
        guest = w.join("Guest")
        self.assertIn("host's computer", run(w, guest, "enable bot")[0])
        self.assertEqual(w.bots, {})

    def test_listed_in_help_and_completed(self):
        w, p = host()
        text = "\n".join(run(w, p, "help"))
        self.assertIn("enable bot [count]", text)
        self.assertIn("disable bot", text)
        self.assertEqual(commands.complete("enable ")[1], ["bot"])
        self.assertEqual(commands.complete("disable b")[1], ["bot"])

    def test_never_takes_over_someone_called_bot(self):
        w, p = host()
        real = w.join("Bot")     # say, someone running bot.py, who then drops out
        real.gold = 77
        w.leave(real)
        run(w, p, "enable bot")
        self.assertEqual(w.players[next(iter(w.bots))].name, "Bot2")
        self.assertEqual(w.offline["Bot"].gold, 77)
        run(w, p, "disable bot")
        self.assertIn("Bot", w.offline)


class FollowTests(unittest.TestCase):
    def test_walks_back_to_its_player(self):
        w, p = host()
        clear_monsters(w, 1)
        p.god = True
        run(w, p, "enable bot")
        bot = w.players[next(iter(w.bots))]
        lvl = w.levels[1]
        steps = lvl.distances_to(p.x, p.y) // algo.CARDINAL_COST
        far = next(c for c in lvl.land_cells if c not in lvl.occupant and 12 <= steps[c] <= 25)
        lvl.move(bot, *far)
        start = cheb(bot, p)
        self.assertGreater(start, bots.FOLLOW)
        play(w, 30)
        self.assertLessEqual(cheb(bot, p), bots.FOLLOW + 1)
        self.assertEqual(bot.depth, 1)

    def test_catches_up_on_another_floor(self):
        w, p = host()
        run(w, p, "enable bot")
        bot = w.players[next(iter(w.bots))]
        w.warp(p, 4)
        bots.step(w)
        self.assertEqual(bot.depth, 4)
        self.assertLessEqual(cheb(bot, p), 2)

    def test_catching_up_waits_between_tries(self):
        w, p = host()
        run(w, p, "enable bot")
        bot = w.players[next(iter(w.bots))]
        w.warp(p, 4)
        bots.step(w)
        w.warp(p, 6)
        bots.step(w)
        self.assertEqual(bot.depth, 4)   # too soon
        w.advance(bots.CATCH_UP * TICKS_PER_SECOND)
        bots.step(w)
        self.assertEqual(bot.depth, 6)

    def test_follows_someone_else_when_its_player_leaves(self):
        w, p = host()
        friend = w.join("Friend")
        run(w, p, "enable bot")
        bot = w.players[next(iter(w.bots))]
        w.leave(p)
        self.assertIs(bots.leader(w, bot), friend)

    def test_bots_leave_when_everyone_real_has(self):
        w, p = host()
        run(w, p, "enable bot 2")
        w.leave(p)
        bots.step(w)
        self.assertEqual(w.players, {})
        self.assertEqual(w.bots, {})


class PartyTests(unittest.TestCase):
    def test_goes_to_revive_a_downed_player(self):
        w, p = host(difficulty="Medium")
        run(w, p, "enable bot")
        bot = w.players[next(iter(w.bots))]
        w._kill(p, None)
        self.assertTrue(p.downed)
        self.assertFalse(w.wiped())
        self.assertIs(bots.leader(w, bot), p)

    def test_on_hard_bots_fall_with_the_party(self):
        w, p = host(difficulty="Hard")
        run(w, p, "enable bot 2")
        w._kill(p, None)
        self.assertFalse(w.wiped())         # the bots were still standing...
        bots.step(w)
        self.assertTrue(w.wiped())          # ...but don't play on alone
        self.assertFalse(any(w.players[b].alive for b in w.bots))

    def test_bots_are_ready_for_the_next_dungeon(self):
        w, p = host(difficulty="Hard")
        run(w, p, "enable bot")
        w._kill(p, None)
        bots.step(w)
        bots.step(w)
        self.assertTrue(all(b in w.ready for b in w.bots))
        w._ready(p)
        self.assertEqual(w.reset_at, 0.0)   # the host alone decides when


class ServerTests(unittest.TestCase):
    def test_the_server_runs_them(self):
        runner = ServerRunner(0, host="127.0.0.1")
        runner.start()
        self.addCleanup(runner.stop)
        sock = socket.create_connection(("127.0.0.1", runner.port), timeout=5)
        self.addCleanup(sock.close)
        sock.sendall(protocol.encode({"t": "hello", "name": "Host", "version": PROTOCOL_VERSION}))
        sock.sendall(protocol.encode({"t": "cmd", "text": "enable bot 2"}))
        end = time.time() + 5
        while time.time() < end and len(runner.world.players) < 3:
            time.sleep(0.05)
        self.assertEqual(len(runner.world.players), 3)
        self.assertEqual(len(runner.game.writers), 1)   # bots take no seats


if __name__ == "__main__":
    unittest.main()
