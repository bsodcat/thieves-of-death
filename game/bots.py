"""Bot teammates for testing, added and removed with the test console's `enable bot` and
`disable bot`. They live inside the server, so they need no connection and work in the exe.

A bot follows the player who added it, or any other real player if that one has gone, and
fights with auto attack: it hits monsters fighting it and leaves the rest alone. If it falls
behind on another floor, or can't find a way to its player, it's brought to their side.
"""
from __future__ import annotations

from . import algo
from .constants import TICKS_PER_SECOND

MAX_BOTS = 5      # at once, whoever added them
FOLLOW = 2        # how close a bot keeps to its player
CATCH_UP = 3      # seconds between bringing a bot that can't walk to its player
NAME = "Bot"
DIRS = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]


def free_name(w) -> str:
    """Bot, Bot2, Bot3...: one no player has, here or away, so no one's character is taken."""
    taken = {q.name for q in w.players.values()} | set(w.offline)
    n = 1
    while (name := NAME if n == 1 else f"{NAME}{n}") in taken:
        n += 1
    return name


def add(w, owner, count: int = 1) -> list:
    """Adds up to `count` bots beside `owner`. Returns the ones added."""
    added = []
    for _ in range(min(count, MAX_BOTS - len(w.bots))):
        p = w.join(free_name(w))
        p.auto_attack = True
        w.bots[p.id] = {"owner": owner.id, "brought": -10**9}
        if owner.alive and p.alive and p.depth != owner.depth:
            w.bring(p, owner)
        added.append(p)
    return added


def remove(w) -> list[str]:
    """Takes every bot out of the game. Returns their names."""
    names = []
    for pid in list(w.bots):
        del w.bots[pid]
        p = w.players.get(pid)
        if p is None:
            continue
        w.leave(p)
        w.offline.pop(p.name, None)  # gone for good, not waiting to rejoin
        names.append(p.name)
    return names


def humans(w) -> list:
    return [q for q in w.players.values() if q.id not in w.bots]


def leader(w, bot):
    """Who a bot follows: the player who added it, or else any living real player, or else
    one who is down, to revive them."""
    owner = w.players.get(w.bots[bot.id]["owner"])
    if owner is not None and owner.alive:
        return owner
    people = humans(w)
    return next((q for q in people if q.alive), None) or next((q for q in people if q.downed), None)


def catch_up(w, bot, lead) -> None:
    """Brings a bot to its leader, but not more than once every few seconds."""
    info = w.bots[bot.id]
    if w.clock - info["brought"] >= CATCH_UP * TICKS_PER_SECOND:
        info["brought"] = w.clock
        w.bring(bot, lead)


def step(w) -> None:
    """Gives every idle bot its next move. Call it each server tick."""
    if not w.bots:
        return
    people = humans(w)
    if not people:  # everyone real has left: the bots go too
        remove(w)
        return
    if not w.wiped() and not any(q.alive or q.downed for q in people):
        for pid in list(w.bots):  # nobody left to follow or revive: bots don't play on alone
            bot = w.players.get(pid)
            if bot is not None and bot.alive:
                w._kill(bot, None, "Fell with the party.")
        return
    for pid in list(w.bots):
        bot = w.players.get(pid)
        if bot is None:
            del w.bots[pid]
            continue
        if w.wiped():
            w._ready(bot)  # bots never hold up a fresh dungeon
            continue
        lead = leader(w, bot) if bot.alive else None
        if lead is None:
            continue
        if lead.depth != bot.depth:  # even mid-fight: it follows its player off the floor
            catch_up(w, bot, lead)
            continue
        if bot.pending is not None or bot.next_time > w.clock:
            continue
        if max(abs(lead.x - bot.x), abs(lead.y - bot.y)) <= (FOLLOW if lead.alive else 1):
            continue  # close enough: stand still, so auto attack can fight, or a revive can happen
        if w._auto_choice(bot):
            continue  # something is fighting it: deal with that first
        move = toward(w, bot, lead)
        if move is None:
            catch_up(w, bot, lead)  # walled off or stuck on an island: catch up
        elif move != (0, 0):
            w.submit(bot, {"t": "act", "a": "move", "dx": move[0], "dy": move[1]})


def toward(w, bot, lead) -> tuple[int, int] | None:
    """The step that brings a bot closest to its leader on foot, (0, 0) to wait for the way
    to clear, or None if there's no way there at all."""
    lvl = w.levels[bot.depth]
    dist = lvl.distances_to(lead.x, lead.y)
    here = dist[bot.x, bot.y]
    if here >= algo.INF:
        return None
    best, best_d = (0, 0), here
    for dx, dy in DIRS:
        nx, ny = bot.x + dx, bot.y + dy
        if not lvl.in_bounds(nx, ny) or lvl.diagonal_blocked(bot.x, bot.y, nx, ny):
            continue
        if lvl.occupant.get((nx, ny)) is not None:
            continue
        if dist[nx, ny] < best_d:
            best, best_d = (dx, dy), dist[nx, ny]
    return best
