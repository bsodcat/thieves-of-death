"""End-to-end: a real server on a random port, two raw socket clients, and the client view."""
import asyncio
import socket
import threading
import time
import unittest

from game import protocol
from game.constants import TICKS_PER_SECOND
from game.render import ClientView
from game.world import World
from server import GameServer


class Client:
    def __init__(self, port, name):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=5)
        self.file = self.sock.makefile("r", encoding="utf-8")
        self.view = ClientView()
        self.send({"t": "hello", "name": name})

    def send(self, msg):
        self.sock.sendall(protocol.encode(msg))

    def read_until(self, pred, timeout=5.0):
        end = time.time() + timeout
        while time.time() < end:
            msg = protocol.decode(self.file.readline())
            self.view.apply(msg)
            if pred(msg):
                return msg
        raise AssertionError("timed out")

    def close(self):
        self.file.close()  # the socket stays open while its file object does
        self.sock.close()


class NetworkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.loop = asyncio.new_event_loop()
        cls.world = World(seed=3)
        game = GameServer(cls.world)
        cls.server = cls.loop.run_until_complete(game.start("127.0.0.1", 0))
        cls.port = cls.server.sockets[0].getsockname()[1]
        threading.Thread(target=cls.loop.run_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        async def shutdown():
            cls.server.close()
            for task in asyncio.all_tasks():
                if task is not asyncio.current_task():
                    task.cancel()
            await asyncio.sleep(0.05)
        asyncio.run_coroutine_threadsafe(shutdown(), cls.loop).result(5)
        cls.loop.call_soon_threadsafe(cls.loop.stop)

    def test_two_players(self):
        a = Client(self.port, "Alice")
        a.read_until(lambda m: m["t"] == "state")
        self.assertIsNotNone(a.view.levels.get(1))
        self.assertTrue(a.view.visible.any())
        b = Client(self.port, "Bob")
        b.read_until(lambda m: m["t"] == "state")
        st = a.read_until(lambda m: m["t"] == "state" and len(m["party"]) == 2)
        me = next(e for e in st["ents"] if e["id"] == st["you"])
        lvl = self.world.levels[1]
        taken = {(e["x"], e["y"]) for e in st["ents"]}
        dx, dy = next(d for d in ((1, 0), (-1, 0), (0, 1), (0, -1))
                      if lvl.walkable[me["x"] + d[0], me["y"] + d[1]]
                      and (me["x"] + d[0], me["y"] + d[1]) not in taken)

        # Alice walks there and back twice while Bob never touches a key.
        for n, sign in enumerate((1, -1, 1, -1), start=1):
            a.send({"t": "act", "a": "move", "dx": dx * sign, "dy": dy * sign})
            st = a.read_until(lambda m: m["t"] == "state" and m["turns"] == n)
        self.assertEqual(st["status"][0], "go")

        # The world keeps running by itself: states arrive with nobody acting,
        # and the server's clock moves in step with real time.
        start = self.world.clock
        time.sleep(0.3)
        self.assertGreater(self.world.clock - start, TICKS_PER_SECOND * 0.2)

        b.send({"t": "chat", "text": "hello there"})
        a.read_until(lambda m: m["t"] == "msg" and m["text"] == "Bob: hello there")

        frame = a.view.draw()
        self.assertEqual(frame.shape, (100, 34))
        b.close()
        a.read_until(lambda m: m["t"] == "msg" and m["text"] == "Bob leaves.")
        a.close()


if __name__ == "__main__":
    unittest.main()
