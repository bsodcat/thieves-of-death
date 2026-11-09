"""Game server. Holds the one true copy of the world; clients only send input.

    python server.py                      # listen on 0.0.0.0:5555
    python server.py --port 6000 --seed 42
    python server.py --password hunter2   # only players who know it can join

The app starts the same server on a background thread with ServerRunner.
"""
from __future__ import annotations

import argparse
import asyncio
import hmac
import logging
import threading
import time
import traceback
from collections import deque

from game import algo, bots, commands, protocol, seasons
from game.constants import (CHAT_BURST, CHAT_RATE, DEFAULT_DIFFICULTY, DEFAULT_PORT, DIFFICULTIES, FLOOD_FORGIVE,
                            FLOOD_STRIKES, JOIN_BURST, JOIN_RATE, MAX_LINE, MAX_PLAYERS, MSG_BURST, MSG_RATE,
                            PING_SECONDS, PING_TIMEOUT, PROTOCOL_VERSION, TICK_RATE, TICKS_PER_SECOND,
                            WRONG_PASSWORD_WAIT)
from game.ledger import Ledger
from game.version import NAME, VERSION
from game.world import World

log = logging.getLogger("server")

# A client this far behind skips states until it catches up; states replace each other.
MAX_BACKLOG = 1 << 20


def is_local(peer) -> bool:
    """Whether a connection comes from this computer. The console needs this: anyone
    who can reach the server can connect, but only the host should be able to cheat."""
    return bool(peer) and peer[0] in ("127.0.0.1", "::1", "::ffff:127.0.0.1")


def password_matches(given, wanted: str) -> bool:
    """Whether a hello's password is right. Takes as long whatever the guess."""
    return hmac.compare_digest(str(given or "").encode("utf-8"), wanted.encode("utf-8"))


class Bucket:
    """A rate limit: holds up to `burst` tokens and gains `rate` a second. Each take uses one."""

    def __init__(self, rate: float, burst: float, now: float | None = None):
        self.rate, self.burst = rate, burst
        self.tokens = float(burst)
        self.at = time.monotonic() if now is None else now

    def take(self, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        self.tokens = min(self.burst, self.tokens + (now - self.at) * self.rate)
        self.at = now
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False


class GameServer:
    def __init__(self, world: World, ledger: Ledger | None = None, password: str = "",
                 max_players: int = MAX_PLAYERS):
        self.world = world
        self.ledger = ledger                            # a dedicated server's own action log
        self.password = password or ""                  # blank: anyone can join
        self.max_players = max_players
        self.joins: dict[str, Bucket] = {}              # address -> how often it may join
        self.writers: dict[int, asyncio.StreamWriter] = {}
        self.pings: dict[int, tuple[int, float]] = {}   # player -> (ping number, when sent)
        self.ping_count = 0
        self.status: dict = {"seed": world.seed, "run": world.run, "difficulty": world.difficulty, "players": []}

    async def start(self, host: str, port: int) -> asyncio.base_events.Server:
        server = await asyncio.start_server(self.handle, host, port, limit=MAX_LINE)
        asyncio.get_running_loop().create_task(self.tick_loop())
        return server

    # ------------------------------------------------------------------

    def send(self, pid: int, msg: dict) -> None:
        w = self.writers.get(pid)
        if w is not None and not w.is_closing():
            w.write(protocol.encode(msg))

    def send_ledger(self) -> None:
        for msg in self.world.drain_ledger():
            if self.ledger is not None:
                self.ledger.apply(msg)
            data = protocol.encode(msg)
            for w in self.writers.values():
                if not w.is_closing():
                    w.write(data)

    def flush(self) -> None:
        """Deliver queued messages, then a fresh state to every connected player."""
        self.send_ledger()
        for pid, msg in self.world.drain_outbox():
            if pid is None:
                data = protocol.encode(msg)
                for w in self.writers.values():
                    if not w.is_closing():
                        w.write(data)
            else:
                self.send(pid, msg)
        for p in self.world.players.values():
            w = self.writers.get(p.id)
            if w is None:
                continue
            if p.needs_level:
                self.send(p.id, self.world.level_msg(p.depth))
                p.needs_level = False
            if p.pack_dirty:
                self.send(p.id, self.world.pack_msg(p))
                p.pack_dirty = False
            if w.transport.get_write_buffer_size() < MAX_BACKLOG:
                self.send(p.id, self.world.state_for(p))
        self.world.dirty = False

    def send_pings(self, now: float) -> None:
        for pid in self.writers:
            sent = self.pings.get(pid)
            if sent is None or now - sent[1] >= PING_TIMEOUT:  # one at a time, so a slow reply still counts
                self.ping_count += 1
                self.pings[pid] = (self.ping_count, now)
                self.send(pid, {"t": "ping", "n": self.ping_count})

    def update_status(self) -> None:
        """A snapshot for the Server Tool, which reads it from another thread."""
        players = [{"name": p.name, "depth": p.depth, "hp": p.hp, "mhp": p.max_hp, "alive": p.alive,
                    "down": p.downed, "ping": None if p.ping is None else round(p.ping)}
                   for p in self.world.players.values()]
        self.status = {"seed": self.world.seed, "run": self.world.run, "difficulty": self.world.difficulty, "players": players}

    def on_pong(self, p, msg: dict) -> None:
        sent = self.pings.get(p.id)
        if sent is not None and msg.get("n") == sent[0]:
            del self.pings[p.id]
            self.world.record_ping(p, (time.monotonic() - sent[1]) * 1000)

    def note_error(self, depth: int) -> None:
        """A game bug, in the action log with whatever led up to it."""
        lines = traceback.format_exc().strip().splitlines()
        self.world.note("ERROR", " | ".join(s.strip() for s in lines[-3:]), depth)

    def may_join(self, peer) -> bool:
        """Whether this address may try to join now. Stops one address joining over and over."""
        if is_local(peer):
            return True
        if len(self.joins) > 1000:  # forget addresses that are back to a full allowance
            now = time.monotonic()
            self.joins = {a: b for a, b in self.joins.items() if b.tokens + (now - b.at) * b.rate < b.burst}
        bucket = self.joins.setdefault(peer[0] if peer else "", Bucket(JOIN_RATE, JOIN_BURST))
        return bucket.take()

    async def refuse(self, writer: asyncio.StreamWriter, text: str) -> None:
        """Tells a player why they can't stay, then hangs up."""
        writer.write(protocol.encode({"t": "reject", "text": text}))
        try:
            await writer.drain()
        except ConnectionError:
            pass
        writer.close()

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        where = peer[0] if peer else "unknown"
        if not self.may_join(peer):
            log.info("refused %s: joining too often", where)
            writer.close()
            return
        try:
            hello = protocol.decode(await asyncio.wait_for(reader.readline(), 10))
            if hello.get("t") != "hello":
                raise ValueError("expected hello")
        except (asyncio.TimeoutError, ValueError, ConnectionError) as exc:
            log.info("rejected %s: %s", peer, exc)
            writer.close()
            return

        if hello.get("version", PROTOCOL_VERSION) != PROTOCOL_VERSION:
            log.info("refused %s: wrong version", where)
            await self.refuse(writer, f"This server runs {NAME} {VERSION}. You need the same version to join.")
            return
        if self.password and not password_matches(hello.get("password"), self.password):
            log.info("refused %s: wrong password", where)
            await asyncio.sleep(WRONG_PASSWORD_WAIT)
            await self.refuse(writer, "Wrong password. Ask the host for it." if hello.get("password")
                              else "This game has a password. Ask the host for it.")
            return
        if len(self.writers) >= self.max_players:
            log.info("refused %s: the game is full", where)
            await self.refuse(writer, f"The game is full ({self.max_players} players). Try again later.")
            return

        p = self.world.join(hello.get("name", ""), hello.get("glyph"), hello.get("color"))
        p.can_command = is_local(peer)
        p.aim = "Weakest" if hello.get("aim") == "Weakest" else "Strongest"
        p.auto_attack = hello.get("auto") == "On"
        p.pickup_key = self.world.clean_key(hello.get("pickup"))
        self.writers[p.id] = writer
        log.info("%s joined from %s", p.name, peer[0] if peer else "unknown")
        self.send(p.id, {"t": "welcome", "id": p.id, "name": p.name, "version": PROTOCOL_VERSION,
                         "difficulty": self.world.difficulty, "revive": self.world.revive_seconds})
        self.send(p.id, self.world.ledger_head())
        self.flush()
        # Each message sends everyone a fresh state, so a flood would slow the game for all.
        messages, strikes = Bucket(MSG_RATE, MSG_BURST), Bucket(FLOOD_FORGIVE, FLOOD_STRIKES)
        chats = Bucket(CHAT_RATE, CHAT_BURST)
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                if not messages.take():
                    if not strikes.take():
                        log.info("dropped %s (%s): sending too much", p.name, where)
                        await self.refuse(writer, "Disconnected for sending too many messages.")
                        break
                    continue
                try:
                    msg = protocol.decode(line)
                except ValueError:
                    continue
                kind = msg.get("t")
                try:
                    if kind == "act":
                        self.world.submit(p, msg)
                    elif kind == "chat":
                        if not chats.take():
                            self.world.tell(p, "You're chatting too fast. Wait a moment.", (255, 170, 80))
                            self.flush()
                            continue
                        self.world.chat(p, msg.get("text", ""))
                    elif kind == "cmd":
                        commands.run(self.world, p, msg.get("text", ""))
                    elif kind == "pong":
                        self.on_pong(p, msg)
                except Exception:  # a game bug shouldn't drop the connection
                    log.exception("error handling %r from %s", msg, p.name)
                    self.note_error(p.depth)
                self.flush()
                await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            pass
        except ValueError:  # readline's answer to a line longer than MAX_LINE
            log.info("dropped %s (%s): message too long", p.name, where)
        finally:
            self.writers.pop(p.id, None)
            self.pings.pop(p.id, None)
            self.world.leave(p)
            self.flush()
            writer.close()
            log.info("%s left", p.name)

    async def tick_loop(self) -> None:
        """Runs the game clock in step with real time."""
        last = next_ping = time.monotonic()
        while True:
            await asyncio.sleep(1 / TICK_RATE)
            now = time.monotonic()
            if now >= next_ping:
                self.send_pings(now)
                self.update_status()
                next_ping = now + PING_SECONDS
            ticks = int((now - last) * TICKS_PER_SECOND)
            last += ticks / TICKS_PER_SECOND  # keep the remainder for the next update
            try:
                bots.step(self.world)
                self.world.advance(ticks)
                self.world.check_reset(now)
                if self.world.dirty or self.world.outbox or self.world.ledger:
                    self.flush()
            except Exception:  # keep the server alive if a game bug slips through
                log.exception("error in tick loop")
                self.note_error(0)


class _RunnerLog(logging.Handler):
    def __init__(self, lines: deque):
        super().__init__(logging.INFO)
        self.lines = lines

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(f"{time.strftime('%H:%M:%S')}  {record.getMessage()}")


class ServerRunner:
    """Runs a server on a background thread, for the app's Host Game and Server Tool."""

    def __init__(self, port: int, seed: int | None = None, host: str = "0.0.0.0",
                 difficulty: str = DEFAULT_DIFFICULTY, season_fn=seasons.current, password: str = "",
                 max_players: int = MAX_PLAYERS):
        self.host, self.port = host, port
        self.world = World(seed, difficulty, season_fn)
        self.game = GameServer(self.world, password=password, max_players=max_players)
        self.log: deque = deque(maxlen=200)
        self.loop = asyncio.new_event_loop()
        self.error: OSError | None = None
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._handler = _RunnerLog(self.log)

    @property
    def status(self) -> dict:
        return self.game.status

    def start(self) -> None:
        """Returns once the server is listening. Raises OSError if the port can't be used."""
        log.setLevel(logging.INFO)
        log.addHandler(self._handler)
        self._thread.start()
        self._ready.wait(10)
        if self.error is not None:
            log.removeHandler(self._handler)
            raise self.error

    def stop(self) -> None:
        if self._thread.is_alive():
            self.loop.call_soon_threadsafe(self.loop.stop)
            self._thread.join(5)
        log.removeHandler(self._handler)

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        try:
            server = self.loop.run_until_complete(self.game.start(self.host, self.port))
        except OSError as exc:
            self.error = exc
            self._ready.set()
            self.loop.close()
            return
        self.port = server.sockets[0].getsockname()[1]
        log.info("Server started on port %d (seed %d)", self.port, self.world.seed)
        if self.world.season:
            log.info("%s", seasons.greeting(self.world.season))
        self._ready.set()
        self.loop.run_forever()
        server.close()
        for task in asyncio.all_tasks(self.loop):
            task.cancel()
        self.loop.run_until_complete(asyncio.sleep(0.05))
        self.loop.close()


async def main() -> None:
    ap = argparse.ArgumentParser(description=f"{NAME} server")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--difficulty", choices=tuple(DIFFICULTIES), default=DEFAULT_DIFFICULTY)
    ap.add_argument("--season", choices=("auto", "none", *seasons.SEASONS), default="auto",
                    help="auto follows the date; the others are for previewing a season")
    ap.add_argument("--password", default="", help="players must give this to join; blank lets anyone in")
    ap.add_argument("--max-players", type=int, default=MAX_PLAYERS, help="players connected at once")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    fixed = None if args.season == "none" else args.season
    world = World(args.seed, args.difficulty, season_fn=seasons.current if args.season == "auto" else lambda: fixed)
    game = GameServer(world, Ledger(), password=args.password, max_players=args.max_players)
    server = await game.start(args.host, args.port)
    log.info("listening on %s:%d (seed %d, %s FOV/pathing, up to %d players, %s)", args.host, args.port,
             world.seed, algo.BACKEND, args.max_players, "password needed" if args.password else "no password")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
