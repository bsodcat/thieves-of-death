"""Bot teammates for testing, added and removed with the test console's `enable bot` and
`disable bot`. They live inside the server, so they need no connection and work in the exe.

A bot follows the player who added it, or any other real player if that one has gone, and
fights with auto attack: it hits monsters fighting it and leaves the rest alone. If it falls
behind on another floor, or can't find a way to its player, it's brought to their side.

A rover (`enable rover`) plays more like a person. It stays within reach of its player but
wanders around them, picks up gear and wears whatever is better than what it has, goes after
the monsters it sees, drinks a healing potion when it's hurt, and runs from a fight it's
losing when it has nothing to drink. Once it has run, it keeps by its player, fighting only
what comes at it, until its health is back up.
"""
from __future__ import annotations

import random

from . import algo
from .constants import PACK_SIZE, TICKS_PER_SECOND, TICKS_PER_TURN
from .entities import PLAYER_STATS

MAX_BOTS = 5      # at once, whoever added them, rovers included
FOLLOW = 2        # how close a bot keeps to its player
CATCH_UP = 3      # seconds between bringing a bot that can't walk to its player
NAME = "Bot"
DIRS = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]

ROVER = "Rover"
LEASH = 10        # steps from its player that a rover roams, fights and loots
WANDER = 7        # how far from its player a rover picks somewhere to wander to
WANDER_SECONDS = 8  # it gives up on a wander spot it can't reach in this long
LOW_HEALTH = 0.35   # below this share of health a rover drinks, or runs
RECOVERED = 0.7     # and once it has run, it stays by its player till it's back up to this
THREAT_RANGE = 8    # monsters this close that are after it count when it's running
HITS_TO_RUN = 2     # it also runs once this many of the biggest nearby monster's hits could kill it
STEP = algo.CARDINAL_COST


def free_name(w, base: str = NAME) -> str:
    """Bot, Bot2, Bot3...: one no player has, here or away, so no one's character is taken."""
    taken = {q.name for q in w.players.values()} | set(w.offline)
    n = 1
    while (name := base if n == 1 else f"{base}{n}") in taken:
        n += 1
    return name


def add(w, owner, count: int = 1, mode: str = "follow") -> list:
    """Adds up to `count` bots beside `owner`. `mode` is "follow" or "rover". Returns the ones added."""
    added = []
    for _ in range(min(count, MAX_BOTS - len(w.bots))):
        p = w.join(free_name(w, ROVER if mode == "rover" else NAME))
        p.auto_attack = True
        w.bots[p.id] = {"owner": owner.id, "brought": -10**9, "mode": mode}
        if owner.alive and p.alive and p.depth != owner.depth:
            w.bring(p, owner)
        added.append(p)
    return added


def remove(w, mode: str | None = None) -> list[str]:
    """Takes every bot, or just those of one mode, out of the game. Returns their names."""
    names = []
    for pid in list(w.bots):
        if mode is not None and w.bots[pid].get("mode", "follow") != mode:
            continue
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
        if w.bots[pid].get("mode") == "rover" and lead.alive:
            rove(w, bot, lead)
        else:
            follow(w, bot, lead)


def follow(w, bot, lead) -> None:
    """Keeps close to its player, fighting only what fights it."""
    if max(abs(lead.x - bot.x), abs(lead.y - bot.y)) <= (FOLLOW if lead.alive else 1):
        return  # close enough: stand still, so auto attack can fight, or a revive can happen
    if w._auto_choice(bot):
        return  # something is fighting it: deal with that first
    move = toward(w, bot, lead)
    if move is None:
        catch_up(w, bot, lead)  # walled off or stuck on an island: catch up
    elif move != (0, 0):
        walk(w, bot, move)


def walk(w, bot, move) -> None:
    w.submit(bot, {"t": "act", "a": "move", "dx": move[0], "dy": move[1]})


def toward(w, bot, lead) -> tuple[int, int] | None:
    """The step that brings a bot closest to its leader on foot, (0, 0) to wait for the way
    to clear, or None if there's no way there at all."""
    return step_to(w, bot, lead.x, lead.y)


def step_to(w, bot, x: int, y: int, dist=None) -> tuple[int, int] | None:
    """The step that brings a bot closest to (x, y) on foot, (0, 0) to wait for the way to
    clear, or None if there's no way there. Walking onto (x, y) itself is allowed even if
    someone is there, which is how a bot attacks a monster. Fire and gas are stepped around."""
    lvl = w.levels[bot.depth]
    dist = lvl.distances_to(x, y) if dist is None else dist
    here = dist[bot.x, bot.y]
    if here >= algo.INF:
        return None
    best, best_d = (0, 0), here
    for dx, dy in DIRS:
        nx, ny = bot.x + dx, bot.y + dy
        if not lvl.in_bounds(nx, ny) or lvl.diagonal_blocked(bot.x, bot.y, nx, ny):
            continue
        if (nx, ny) != (x, y) and (lvl.occupant.get((nx, ny)) is not None or not safe(lvl, nx, ny)):
            continue
        if dist[nx, ny] < best_d:
            best, best_d = (dx, dy), dist[nx, ny]
    return best


def safe(lvl, x: int, y: int) -> bool:
    return (x, y) not in lvl.fire and (x, y) not in lvl.gas


# ------------------------------------------------------------------ rovers

def rove(w, bot, lead) -> None:
    """A rover's next move, most urgent first: heal, run, fight what's on it, gear up,
    loot, hunt, keep near its player, and otherwise wander."""
    info = w.bots[bot.id]
    lvl = w.levels[bot.depth]
    sight = w.fov(bot)
    threats = [m for m in lvl.monsters if sight[m.x, m.y] and m.state == "hunting"
               and max(abs(m.x - bot.x), abs(m.y - bot.y)) <= THREAT_RANGE]
    hurt = in_danger(bot, threats)
    if hurt:
        info["recovering"] = True
    elif bot.hp >= bot.max_hp * RECOVERED:
        info["recovering"] = False

    if hurt and bot.hp < bot.max_hp and any(i.heal for i in bot.pack):
        w.submit(bot, {"a": "quickheal"})
        return
    slot = potion_to_drink(w, bot)
    if slot is not None:
        w.submit(bot, {"a": "use", "slot": slot})
        return

    if hurt and threats:
        move = flee(w, bot, lead, threats)
        if move is not None:
            walk(w, bot, move)
            return
        # cornered: fall through and fight

    if w._auto_choice(bot):
        bot.pending = {"a": "auto"}  # swing at, or shoot, what's fighting it
        return

    slot = gear_to_change(bot)
    if slot is not None:
        w.submit(bot, {"a": "use", "slot": slot})
        return
    slot = gear_to_drop(bot)
    if slot is not None:
        w.submit(bot, {"a": "drop", "slot": slot})
        return
    here = lvl.items.get((bot.x, bot.y))
    if here is not None and wants(bot, here):
        w.submit(bot, {"a": "pickup"})
        return

    if info.get("recovering"):
        follow(w, bot, lead)  # hurt: stay by its player and let health come back
        return

    mine = algo.dijkstra(lvl.walkable, [(bot.x, bot.y)])
    leash = lvl.distances_to(lead.x, lead.y)

    def in_reach(x, y) -> bool:
        return mine[x, y] < algo.INF and leash[x, y] <= (LEASH + 2) * STEP

    foe = min((m for m in lvl.monsters if sight[m.x, m.y] and worth_fighting(w, m) and in_reach(m.x, m.y)),
              key=lambda m: (mine[m.x, m.y], m.id), default=None)
    if foe is not None:
        info["wander"] = None
        go(w, bot, lead, foe.x, foe.y)
        return

    loot = min(((x, y) for (x, y), item in lvl.items.items() if sight[x, y] and wants(bot, item)
                and in_reach(x, y) and lvl.occupant.get((x, y)) is None),
               key=lambda c: (mine[c], c), default=None)
    if loot is not None:
        info["wander"] = None
        go(w, bot, lead, *loot)
        return

    if leash[bot.x, bot.y] > LEASH * STEP:
        info["wander"] = None
        follow(w, bot, lead)
        return

    wander(w, bot, lead, info, mine, leash)


def go(w, bot, lead, x: int, y: int) -> None:
    move = step_to(w, bot, x, y)
    if move is None:
        follow(w, bot, lead)
    elif move != (0, 0):
        walk(w, bot, move)


def wander(w, bot, lead, info, mine, leash) -> None:
    """Strolls to somewhere a short walk from its player, then picks somewhere else."""
    lvl = w.levels[bot.depth]
    spot = info.get("wander")
    if (spot is None or max(abs(spot[0] - bot.x), abs(spot[1] - bot.y)) <= 1
            or w.clock >= info.get("wander_until", 0) or leash[spot] > (WANDER + 2) * STEP):
        near = [c for c in lvl.land_cells if leash[c] <= WANDER * STEP and mine[c] < algo.INF
                and c not in lvl.occupant and safe(lvl, *c)]
        if not near:
            follow(w, bot, lead)
            return
        spot = random.choice(near)
        info["wander"] = spot
        info["wander_until"] = w.clock + WANDER_SECONDS * TICKS_PER_SECOND
    move = step_to(w, bot, *spot)
    if move is None:
        info["wander"] = None
    elif move != (0, 0):
        walk(w, bot, move)


def in_danger(bot, threats) -> bool:
    """Low on health, or close enough to dying that two more hits from what's beside it
    could do it. Big hitters like ogres take a lot in one blow, so a share alone isn't enough."""
    if bot.hp <= bot.max_hp * LOW_HEALTH:
        return True
    near = [m.damage[1] for m in threats if max(abs(m.x - bot.x), abs(m.y - bot.y)) <= 2]
    return bool(near) and bot.hp <= HITS_TO_RUN * max(near)


def worth_fighting(w, m) -> bool:
    """A monster a rover will go after: not a monkey nobody has bothered yet, and not one
    out of reach in the air."""
    if m.kind == "monkey" and not m.provoked:
        return False
    return not w._floating(m) and not w._levitating(m)


def flee(w, bot, lead, threats) -> tuple[int, int] | None:
    """The step that gets furthest from the monsters after it, leaning toward its player.
    None if every way out is no better than staying put."""
    lvl = w.levels[bot.depth]
    away = algo.dijkstra(lvl.walkable, [(m.x, m.y) for m in threats])
    friend = lvl.distances_to(lead.x, lead.y)
    here = away[bot.x, bot.y]
    best, best_key = None, None
    for dx, dy in DIRS:
        nx, ny = bot.x + dx, bot.y + dy
        if (not lvl.in_bounds(nx, ny) or lvl.diagonal_blocked(bot.x, bot.y, nx, ny)
                or not lvl.walkable[nx, ny] or lvl.occupant.get((nx, ny)) is not None or not safe(lvl, nx, ny)):
            continue
        if away[nx, ny] <= here:
            continue
        key = (away[nx, ny], -friend[nx, ny])
        if best_key is None or key > best_key:
            best, best_key = (dx, dy), key
    return best


# ----------------------------------------------------------------- gear

def weapon_score(item) -> float:
    """Damage per normal turn, which is what a weapon is worth to a rover."""
    damage = item.damage if item is not None else PLAYER_STATS["damage"]
    cost = item.attack_cost if item is not None else TICKS_PER_TURN
    return sum(damage) / 2 * TICKS_PER_TURN / cost + (item.accuracy / 20 if item is not None else 0)


def armor_score(item) -> int:
    return item.armor if item is not None else 0


def has_room(bot, item) -> bool:
    return len(bot.pack) < PACK_SIZE or (item.stacks and any(i.kind == item.kind for i in bot.pack))


def ranged_ready(bot, item) -> bool:
    """A ranged weapon or staff it could fire right now."""
    if item.category == "wand":
        return item.unlimited
    return item.category == "ranged" and (not item.fires or any(i.category == "ammo" for i in bot.pack))


def wants(bot, item) -> bool:
    """Whether a rover picks this up: gold, the potions it knows how to use, and gear better
    than what it has. Keys, the Amulet and the like are left for the people."""
    c = item.category
    if c == "gold":
        return True
    if not has_room(bot, item):
        return False
    if c == "potion":
        return bool(item.heal or item.cure or item.strength)
    if c == "weapon":
        return weapon_score(item) > weapon_score(bot.weapon)
    if c == "armor":
        return armor_score(item) > armor_score(bot.armor)
    if c == "ammo":
        return any(i.category == "ranged" and i.fires for i in bot.pack)
    if c in ("ranged", "wand"):
        return (item.category == "ranged" or item.unlimited) and not any(
            i.category in ("ranged", "wand") for i in bot.pack)
    return False


def gear_to_change(bot) -> int | None:
    """The pack slot of something better to wear or ready, if there is one."""
    for i, item in enumerate(bot.pack):
        if item.category == "weapon" and item is not bot.weapon and weapon_score(item) > weapon_score(bot.weapon):
            return i
        if item.category == "armor" and item is not bot.armor and armor_score(item) > armor_score(bot.armor):
            return i
    if bot.ranged is None or bot.ranged not in bot.pack or not ranged_ready(bot, bot.ranged):
        for i, item in enumerate(bot.pack):
            if item is not bot.ranged and ranged_ready(bot, item):
                return i
        if bot.ranged is not None and bot.ranged in bot.pack:
            return bot.pack.index(bot.ranged)  # out of arrows: put the bow away
    return None


def gear_to_drop(bot) -> int | None:
    """A weapon or armor it has outgrown, set down for someone else."""
    for i, item in enumerate(bot.pack):
        if item.category == "weapon" and item is not bot.weapon and weapon_score(item) <= weapon_score(bot.weapon):
            return i
        if item.category == "armor" and item is not bot.armor and armor_score(item) <= armor_score(bot.armor):
            return i
    return None


def potion_to_drink(w, bot) -> int | None:
    """Strength right away, and an antidote once poisoned."""
    poisoned = bot.toxin_until > w.clock or bot.venom_until > w.clock
    for i, item in enumerate(bot.pack):
        if item.strength or (item.cure and poisoned):
            return i
    return None
