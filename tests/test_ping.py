"""The players list: each player's ping and floor, measured over a real connection."""
import asyncio
import threading
import time
import unittest
from unittest import mock

from game import protocol
from game.render import ClientView
from game.world import World
from server import GameServer
from tests.test_network import Client


def screen_text(view):
    frame = view.draw()
    return "\n".join("".join(chr(c) for c in frame["ch"][:, y]) for y in range(frame.shape[1]))


class PingClient(Client):
    """Answers pings, optionally after a delay, and keeps the latest state."""

    def __init__(self, port, name, delay=0.0):
        super().__init__(port, name)
        self.delay, self.state = delay, None
        threading.Thread(target=self.loop, daemon=True).start()

    def loop(self):
        try:
            for line in self.file:
                msg = protocol.decode(line)
                if msg["t"] == "ping":
                    time.sleep(self.delay)
                    self.send({"t": "pong", "n": msg["n"]})
                elif msg["t"] == "state":
                    self.state = msg
        except (OSError, ValueError):
            pass

    def party(self, name):
        return next(p for p in self.state["party"] if p["name"] == name)


class PingNetworkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.loop = asyncio.new_event_loop()
        cls.world = World(seed=3)
        cls.game = GameServer(cls.world)
        cls.server = cls.loop.run_until_complete(cls.game.start("127.0.0.1", 0))
        cls.port = cls.server.sockets[0].getsockname()[1]
        threading.Thread(target=cls.loop.run_forever, daemon=True).start()

    def wait_for(self, check, timeout=6.0):
        end = time.time() + timeout
        while time.time() < end:
            try:
                if check():
                    return
            except (StopIteration, TypeError):
                pass
            time.sleep(0.02)
        self.fail("timed out")

    def test_everyone_sees_everyones_ping_and_floor(self):
        fast = PingClient(self.port, "Fast")
        slow = PingClient(self.port, "Slow", delay=0.15)
        self.wait_for(lambda: fast.party("Slow")["ping"] is not None and fast.party("Fast")["ping"] is not None)
        self.assertLess(fast.party("Fast")["ping"], 100)
        self.assertGreaterEqual(fast.party("Slow")["ping"], 140)
        self.wait_for(lambda: slow.party("Fast")["ping"] is not None)   # both directions
        self.assertEqual(fast.party("Slow")["depth"], 1)

        mover = next(p for p in self.world.players.values() if p.name == "Slow")
        lvl = self.world.levels[1]
        lvl.remove(mover)
        lower = self.world.level(2)
        lower.place(mover, *lower.free_near(*lower.up_front))
        self.world.dirty = True
        self.wait_for(lambda: fast.party("Slow")["depth"] == 2)
        fast.close()
        slow.close()
        self.wait_for(lambda: not self.game.pings and not self.world.players)


class ServerPingTests(unittest.TestCase):
    def setUp(self):
        self.world = World(1)
        self.game = GameServer(self.world)
        self.p = self.world.join("Alice")
        self.game.writers[self.p.id] = mock.Mock(is_closing=lambda: True)

    def test_wrong_number_is_ignored(self):
        self.game.send_pings(100.0)
        self.game.on_pong(self.p, {"n": 12345})
        self.game.on_pong(self.p, {})
        self.assertIsNone(self.p.ping)

    def test_only_one_ping_at_a_time(self):
        self.game.send_pings(100.0)
        first = self.game.pings[self.p.id]
        self.game.send_pings(101.0)
        self.assertEqual(self.game.pings[self.p.id], first)

    def test_unanswered_ping_is_retried(self):
        self.game.send_pings(100.0)
        first = self.game.pings[self.p.id]
        self.game.send_pings(106.0)
        self.assertNotEqual(self.game.pings[self.p.id], first)

    def test_ping_is_smoothed_and_cleared_on_leaving(self):
        self.world.record_ping(self.p, 100.0)
        self.world.record_ping(self.p, 200.0)
        self.assertEqual(round(self.p.ping), 130)
        self.assertEqual(self.world.state_for(self.p)["party"][0]["ping"], 130)
        self.world.leave(self.p)
        self.assertIsNone(self.p.ping)


class PlayerListDrawTests(unittest.TestCase):
    def view(self, party):
        v = ClientView()
        v.my_id = 1
        v.party = party
        return v

    def entry(self, pid, name, depth, ping, alive=True):
        return {"id": pid, "name": name, "c": [255, 255, 255], "hp": 30, "mhp": 40,
                "depth": depth, "alive": alive, "ping": ping}

    def test_lists_you_and_everyone_else(self):
        text = screen_text(self.view([self.entry(1, "Alice", 1, 12), self.entry(2, "Bob", 3, 148)]))
        self.assertIn("Players", text)
        self.assertIn("Alice", text)
        self.assertIn("Floor 1  12ms", text)
        self.assertIn("Bob", text)
        self.assertIn("Floor 3  148ms", text)

    def test_unmeasured_and_dead(self):
        text = screen_text(self.view([self.entry(1, "Alice", 1, None),
                                      self.entry(2, "Bob", 12, 1200, alive=False)]))
        self.assertIn("Floor 1  --", text)
        self.assertIn("Floor 12 1200ms dead", text)   # tightened so the longest label still fits

    def test_full_party_fits(self):
        party = [self.entry(i, f"Player{i}", 12, 999) for i in range(1, 7)]
        text = screen_text(self.view(party))
        self.assertIn("Player6", text)


if __name__ == "__main__":
    unittest.main()
