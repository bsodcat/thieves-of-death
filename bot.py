"""A headless test player, so you can try multiplayer on your own.

It follows the first other player on its depth, attacks adjacent monsters,
and otherwise wanders.

    python bot.py                        # connects to localhost as "Bot"
    python bot.py --name Rex --delay 0.3
"""
from __future__ import annotations

import argparse
import random
import socket
import threading
import queue
import time

from game import protocol
from game.constants import DEFAULT_PORT, PROTOCOL_VERSION

DIRS = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]


def sign(v: int) -> int:
    return (v > 0) - (v < 0)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--name", default="Bot")
    ap.add_argument("--delay", type=float, default=0.4, help="seconds between moves")
    args = ap.parse_args()

    sock = socket.create_connection((args.host, args.port))
    sock.sendall(protocol.encode({"t": "hello", "name": args.name, "version": PROTOCOL_VERSION}))
    inbox: queue.Queue = queue.Queue()

    def reader() -> None:
        with sock.makefile("r", encoding="utf-8") as f:
            for line in f:
                inbox.put(protocol.decode(line))
        inbox.put(None)

    threading.Thread(target=reader, daemon=True).start()
    state, my_id, last_pos, heading = None, None, None, random.choice(DIRS)
    last_act = 0.0
    while True:
        try:
            msg = inbox.get(timeout=0.05)
            if msg is None:
                print("disconnected")
                return
            if msg["t"] == "welcome":
                my_id = msg["id"]
                print(f"joined as {msg['name']}")
            elif msg["t"] == "state":
                state = msg
            elif msg["t"] == "msg":
                print(msg["text"])
            elif msg["t"] == "ping":
                sock.sendall(protocol.encode({"t": "pong", "n": msg["n"]}))
        except queue.Empty:
            pass
        if not state or not state["alive"] or state["status"][0] != "go":
            continue
        if time.monotonic() - last_act < args.delay:
            continue
        me = next(e for e in state["ents"] if e["id"] == my_id)
        foes = [e for e in state["ents"] if not e["p"] and e["seen"]
                and max(abs(e["x"] - me["x"]), abs(e["y"] - me["y"])) == 1]
        friends = [e for e in state["ents"] if e["p"] and e["id"] != my_id]
        if foes:
            dx, dy = foes[0]["x"] - me["x"], foes[0]["y"] - me["y"]
        elif friends and max(abs(friends[0]["x"] - me["x"]), abs(friends[0]["y"] - me["y"])) > 2 \
                and (me["x"], me["y"]) != last_pos:
            dx, dy = sign(friends[0]["x"] - me["x"]), sign(friends[0]["y"] - me["y"])
        else:
            if (me["x"], me["y"]) == last_pos or random.random() < 0.15:
                heading = random.choice(DIRS)
            dx, dy = heading
        last_pos = (me["x"], me["y"])
        sock.sendall(protocol.encode({"t": "act", "a": "move", "dx": dx, "dy": dy}))
        last_act = time.monotonic()


if __name__ == "__main__":
    main()
