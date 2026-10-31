"""The authoritative game state: levels, actors, the clock, combat and AI.

Real time
---------
There is one clock, counted in ticks; the server runs it forward with
`advance(ticks)` many times a second. Every actor has a `next_time`, the tick
it may act again, so an action costs a cooldown rather than a turn. Nobody
waits for anybody: a player's queued action runs as soon as their own cooldown
is over, and monsters act whether or not anyone is pressing keys.

In Revive mode a fallen player stays on the level as bones, kept in `Level.downed`
rather than `occupant`, so nothing bumps into them. A teammate within reach brings
them back; see `_tick_revives`.

Monsters only run on levels with a living player. The rest stay frozen until
someone arrives.

The server is single-threaded: call `submit`, `chat`, `join`, `leave` and
`advance`, then drain `outbox` and send `state_for(player)` to everyone.
"""
from __future__ import annotations

import itertools
import random
import time
from collections import deque

import numpy as np

from . import algo, mapgen, protocol
from .constants import (BONES_GLYPH, DEEPEST_TABLE, DEFENSE_FACTOR, GOLD_DROP, MAP_H, MAP_W, MONSTER_TIME, NOTICE_RANGE_AWAKE,
                        NOTICE_RANGE_SLEEPING, PACK_SIZE, REGEN_TURNS, RESET_DELAY, REVIVE_HEALTH,
                        REVIVE_SECONDS, SCORE_PER_GOLD, SCORE_PER_MOVE, STEALTH_FILL_SECONDS,
                        STEALTH_MAX, STEALTH_MOVE_DRAIN, STEALTH_RANGE_MIN, TICKS_PER_SECOND,
                        TICKS_PER_TURN)
from .entities import (MONSTERS, PLAYER_COLOR_NAMES, PLAYER_COLORS, PLAYER_GLYPHS, Monster, Player, apply_gear, danger,
                       make_monster, make_player, reset_player)
from .items import AUTO_PICKUP, ITEMS, Item, make_gold, make_item
from .tiles import DOOR, STAIRS_DOWN, STAIRS_UP, TRANSPARENT, WALKABLE

DIRS8 = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]

WHITE = (230, 230, 230)
BONE = (225, 220, 195)
GRAY = (160, 160, 160)
RED = (255, 100, 100)
ORANGE = (255, 170, 80)
GOLD = (255, 215, 90)


def cheb(a, b) -> int:
    return max(abs(a.x - b.x), abs(a.y - b.y))


def _article(name: str) -> str:
    return ("an " if name[:1] in "aeiou" else "a ") + name


class Level:
    def __init__(self, depth: int, gen: mapgen.GeneratedLevel):
        self.depth = depth
        self.tiles = gen.tiles
        self.up, self.up_front = gen.up, gen.up_front
        self.down, self.down_front = gen.down, gen.down_front
        self.walkable = WALKABLE[self.tiles]
        self.is_door = self.tiles == DOOR
        self._base_transparent = TRANSPARENT[self.tiles]
        self.floor_cells = [(int(x), int(y)) for x, y in np.argwhere(self.walkable)]
        self.occupant: dict[tuple[int, int], object] = {}
        self.monsters: list[Monster] = []
        self.items: dict[tuple[int, int], Item] = {}   # one item per tile
        self.downed: list[Player] = []                 # Revive mode: bones on this level
        self.door_version = 0  # bumps whenever someone enters or leaves a doorway
        self._transparent = None
        self._transparent_version = -1

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < MAP_W and 0 <= y < MAP_H

    def actor_at(self, x: int, y: int):
        return self.occupant.get((x, y))

    def place(self, a, x: int, y: int) -> None:
        a.x, a.y, a.depth = x, y, self.depth
        self.occupant[(x, y)] = a
        if self.is_door[x, y]:
            self.door_version += 1

    def remove(self, a) -> None:
        if self.occupant.get((a.x, a.y)) is a:
            del self.occupant[(a.x, a.y)]
            if self.is_door[a.x, a.y]:
                self.door_version += 1

    def move(self, a, x: int, y: int) -> None:
        self.remove(a)
        self.place(a, x, y)

    def transparency(self) -> np.ndarray:
        """Like Brogue, a door is see-through only while someone stands in it."""
        if self._transparent_version != self.door_version:
            t = self._base_transparent.copy()
            for x, y in self.occupant:
                if self.is_door[x, y]:
                    t[x, y] = True
            self._transparent, self._transparent_version = t, self.door_version
        return self._transparent

    def diagonal_blocked(self, x: int, y: int, nx: int, ny: int) -> bool:
        """Brogue rule: no cutting diagonally past a wall corner."""
        if x == nx or y == ny:
            return False
        return not self.walkable[nx, y] or not self.walkable[x, ny]

    def free_near(self, x: int, y: int) -> tuple[int, int]:
        queue, seen = deque([(x, y)]), {(x, y)}
        while queue:
            cx, cy = queue.popleft()
            if self.walkable[cx, cy] and (cx, cy) not in self.occupant:
                return cx, cy
            for dx, dy in DIRS8:
                n = (cx + dx, cy + dy)
                if self.in_bounds(*n) and n not in seen and (self.walkable[n] or n == (x, y)):
                    seen.add(n)
                    queue.append(n)
        return x, y

    def free_item_spot(self, x: int, y: int) -> tuple[int, int]:
        """The closest walkable tile to (x, y) with no item on it."""
        queue, seen = deque([(x, y)]), {(x, y)}
        while queue:
            cx, cy = queue.popleft()
            if self.walkable[cx, cy] and (cx, cy) not in self.items:
                return cx, cy
            for dx, dy in DIRS8:
                n = (cx + dx, cy + dy)
                if self.in_bounds(*n) and n not in seen and self.walkable[n]:
                    seen.add(n)
                    queue.append(n)
        return x, y

    def random_floor(self, rng: random.Random) -> tuple[int, int]:
        return rng.choice(self.floor_cells)


class World:
    def __init__(self, seed: int | None = None, monster_time: float = MONSTER_TIME, mode: str = "Classic"):
        self.seed = seed if seed is not None else random.randrange(1, 2 ** 31)
        self.monster_time = monster_time
        self.mode = mode
        self.rng = random.Random(self.seed * 7919 + 1)
        self.levels: dict[int, Level] = {}
        self.players: dict[int, Player] = {}   # connected players
        self.offline: dict[str, Player] = {}   # disconnected, keyed by name, restored on rejoin
        self.clock = 0
        self.dirty = True                      # something changed since the last state was sent
        self.outbox: list[tuple[int | None, dict]] = []
        self.run = 1
        self.run_start = 0                     # the tick this run began, for the UI clock
        self.reset_at: float | None = None
        self._ids = itertools.count(1)

    # ------------------------------------------------------------ levels

    def level(self, depth: int) -> Level:
        lvl = self.levels.get(depth)
        if lvl is None:
            lvl = Level(depth, mapgen.generate(self.seed, depth))
            self.levels[depth] = lvl
            self._populate(lvl)
        return lvl

    def _populate(self, lvl: Level) -> None:
        rng = random.Random(f"{self.seed}:{lvl.depth}:monsters")
        dist = algo.dijkstra(lvl.walkable, [lvl.up_front])
        spots = [(int(x), int(y)) for x, y in np.argwhere(lvl.walkable & (dist > 24) & (dist < algo.INF))]
        depth = min(lvl.depth, DEEPEST_TABLE)
        kinds = [(k, t["weight"]) for k, t in MONSTERS.items() if t["depths"][0] <= depth <= t["depths"][1]]
        rng.shuffle(spots)
        for x, y in spots[:4 + lvl.depth // 2 + rng.randint(0, 3)]:
            kind = rng.choices([k for k, _ in kinds], [w for _, w in kinds])[0]
            m = make_monster(kind, next(self._ids))
            m.state = "sleeping" if rng.random() < 0.6 else "wandering"
            m.lag = m.next_time = rng.randrange(TICKS_PER_TURN)
            lvl.place(m, x, y)
            lvl.monsters.append(m)
        self._add_items(lvl)

    def _add_items(self, lvl: Level) -> None:
        rng = random.Random(f"{self.seed}:{lvl.depth}:items")
        spots = rng.sample(lvl.floor_cells, 12)
        depth = min(lvl.depth, DEEPEST_TABLE)
        kinds = [(k, t["weight"]) for k, t in ITEMS.items() if t["depths"][0] <= depth <= t["depths"][1]]
        for _ in range(3 + rng.randint(0, 2)):
            kind = rng.choices([k for k, _ in kinds], [w for _, w in kinds])[0]
            lvl.items[spots.pop()] = make_item(kind)
        for _ in range(2 + rng.randint(0, 2)):
            lvl.items[spots.pop()] = make_gold(rng.randint(5, 15) * lvl.depth + 5)

    # ----------------------------------------------------------- players

    def _clean_name(self, name: str) -> str:
        name = "".join(c for c in str(name) if c.isprintable()).strip()[:16]
        return name or "Adventurer"

    def _next_color(self) -> tuple:
        used = {p.color for p in self.players.values()}
        for c in PLAYER_COLORS:
            if c not in used:
                return c
        return PLAYER_COLORS[len(self.players) % len(PLAYER_COLORS)]

    @staticmethod
    def _dress(p: Player, glyph, color) -> None:
        """Applies a character's chosen look, ignoring anything not on the lists."""
        if glyph in PLAYER_GLYPHS:
            p.glyph = glyph
        if isinstance(color, str) and color in PLAYER_COLOR_NAMES:
            p.color = PLAYER_COLOR_NAMES[color]

    def join(self, name: str, glyph=None, color=None) -> Player:
        name = self._clean_name(name)
        if name in self.offline:
            p = self.offline.pop(name)
            p.connected, p.pending, p.needs_level, p.pack_dirty = True, None, True, True
            self._dress(p, glyph, color)
            if p.alive:
                lvl = self.level(p.depth)
                lvl.place(p, *lvl.free_near(p.x, p.y))
            elif p.downed:
                self.level(p.depth).downed.append(p)
            self.players[p.id] = p
            self.dirty = True
            self.broadcast(f"{p.name} returns.", p.color)
            self._check_all_dead()
            return p
        taken = {q.name for q in self.players.values()}
        base, n = name, 2
        while name in taken:
            name, n = f"{base[:13]}{n}", n + 1
        p = make_player(next(self._ids), name, self._next_color())
        self._dress(p, glyph, color)
        anchor = next((q for q in self.players.values() if q.alive), None)
        if anchor:  # drop newcomers next to the party
            depth, start = anchor.depth, (anchor.x, anchor.y)
        else:
            depth = 1
            start = self.level(1).up_front
        lvl = self.level(depth)
        lvl.place(p, *lvl.free_near(*start))
        self.players[p.id] = p
        self.dirty = True
        self.broadcast(f"{p.name} enters the dungeon.", p.color)
        return p

    def leave(self, p: Player) -> None:
        if self.players.pop(p.id, None) is None:
            return
        p.connected, p.pending, p.hold, p.ping = False, None, None, None
        self.dirty = True
        if p.alive:
            self.levels[p.depth].remove(p)
        elif p.downed:
            self.levels[p.depth].downed.remove(p)
            p.revive_ticks = 0
        self.offline[p.name] = p
        self.broadcast(f"{p.name} leaves.", GRAY)
        self._check_all_dead()

    def submit(self, p: Player, msg: dict) -> None:
        """Queue a player's action (replacing any earlier queued one). It runs now, or
        when their cooldown ends."""
        if not p.alive or not p.connected:
            return
        a = msg.get("a")
        if a in ("move", "hold"):
            try:
                dx, dy = int(msg.get("dx", 0)), int(msg.get("dy", 0))
            except (TypeError, ValueError):
                return
            if dx not in (-1, 0, 1) or dy not in (-1, 0, 1):
                return
            moving = bool(dx or dy)
            if a == "hold":
                p.hold = (dx, dy) if moving else None
            if not moving:
                return
            # A press is buffered, so a quick tap during a cooldown still counts. The rest
            # of a hold isn't: it steps only while held, so releasing stops you dead.
            if a == "move" or msg.get("press"):
                if p.pending is not None and p.pending["a"] != "move":
                    return  # don't let walking replace a potion or a drop
                p.pending = {"a": "move", "dx": dx, "dy": dy}
        elif a in ("use", "drop"):
            slot = msg.get("slot")
            if not isinstance(slot, int) or isinstance(slot, bool) or not 0 <= slot < PACK_SIZE:
                return
            p.pending = {"a": a, "slot": slot}
        elif a in ("descend", "ascend", "pickup", "dropgold"):
            p.pending = {"a": a}
        else:
            return
        self.advance()

    def record_ping(self, p: Player, ms: float) -> None:
        p.ping = ms if p.ping is None else p.ping * 0.7 + ms * 0.3  # smoothed, so it doesn't flicker
        self.dirty = True

    def chat(self, p: Player, text: str) -> None:
        text = "".join(c for c in str(text) if c.isprintable()).strip()[:200]
        if text:
            self.broadcast(f"{p.name}: {text}", p.color)

    # ---------------------------------------------------------- messages

    def tell(self, p: Player, text: str, color: tuple = WHITE) -> None:
        self.outbox.append((p.id, {"t": "msg", "text": text, "c": list(color)}))

    def broadcast(self, text: str, color: tuple = WHITE) -> None:
        self.outbox.append((None, {"t": "msg", "text": text, "c": list(color)}))

    def drain_outbox(self) -> list[tuple[int | None, dict]]:
        out, self.outbox = self.outbox, []
        return out

    def _narrate(self, lvl: Level, positions, involved, fn, exclude=None) -> None:
        """Send fn(viewer) -> (text, color) to every player who can see one of `positions`."""
        for v in self.players.values():
            if not v.alive or v.depth != lvl.depth or v is exclude:
                continue
            if v in involved or any(self.fov(v)[x, y] for x, y in positions):
                text, color = fn(v)
                self.tell(v, text, color)

    def _n(self, a, viewer, cap: bool = False) -> str:
        s = "you" if a is viewer else (a.name if a.is_player else f"the {a.name}")
        return s[:1].upper() + s[1:] if cap else s

    @staticmethod
    def _verb(a, viewer, pair: tuple) -> str:
        return pair[1] if a is viewer else pair[0]

    # ------------------------------------------------------------ vision

    def fov(self, p: Player) -> np.ndarray:
        lvl = self.levels[p.depth]
        key = (self.run, p.depth, p.x, p.y, lvl.door_version)
        if p.fov_key != key:
            p.fov = algo.compute_fov(lvl.transparency(), p.x, p.y, 0)
            p.fov_key = key
        return p.fov

    def _living_on(self, depth: int) -> list[Player]:
        return [p for p in self.players.values() if p.alive and p.depth == depth]

    # -------------------------------------------------------------- clock

    def _next_due(self, target: int):
        """The actor with the earliest action at or before tick `target`, and when it falls."""
        best, best_key = None, None
        living = [p for p in self.players.values() if p.alive]
        for p in living:
            if p.pending is not None or p.hold is not None:
                key = (max(p.next_time, self.clock), 0, p.id)
                if best_key is None or key < best_key:
                    best, best_key = p, key
        for depth in {p.depth for p in living}:
            for m in self.levels[depth].monsters:
                if m.next_time < self.clock:  # was frozen; the lag keeps a level from waking in step
                    m.next_time = self.clock + m.lag
                key = (m.next_time, 1, m.id)
                if best_key is None or key < best_key:
                    best, best_key = m, key
        if best_key is None or best_key[0] > target:
            return None, 0
        return best, best_key[0]

    def advance(self, ticks: int = 0, max_steps: int = 20000) -> None:
        """Run the clock forward, resolving everything that falls due, in time order."""
        target = self.clock + ticks
        for _ in range(max_steps):
            actor, when = self._next_due(target)
            if actor is None:
                break
            self.clock = max(self.clock, when)
            self.dirty = True
            if actor.is_player:
                self._player_turn(actor)
            else:
                self._monster_act(actor)
        self.clock = target
        if ticks:
            for p in self.players.values():
                if p.alive:
                    self._regen(p, ticks)
                    self._fill_stealth(p, ticks)
            self._tick_revives(ticks)

    def _player_turn(self, p: Player) -> None:
        act, p.pending = p.pending, None
        if act is None:
            act = {"a": "move", "dx": p.hold[0], "dy": p.hold[1]}
        moves = p.turns
        self._perform(p, act)
        if act["a"] == "move" and p.turns == moves:
            p.hold = None  # walked into a wall: stop, or this would retry forever

    def _rescuer_of(self, p: Player):
        """A living teammate close enough to revive this downed player."""
        return next((q for q in self._living_on(p.depth) if cheb(q, p) <= 1), None)

    def _tick_revives(self, ticks: int) -> None:
        for lvl in self.levels.values():
            for p in list(lvl.downed):
                rescuer = self._rescuer_of(p)
                progress = p.revive_ticks + ticks if rescuer else 0
                if progress != p.revive_ticks:
                    self.dirty = True
                p.revive_ticks = progress
                if rescuer and progress >= REVIVE_SECONDS * TICKS_PER_SECOND:
                    self._revive(p, rescuer, lvl)

    def _revive(self, p: Player, rescuer: Player, lvl: Level) -> None:
        lvl.downed.remove(p)
        p.alive, p.downed, p.revive_ticks, p.death, p.final_gold = True, False, 0, "", None
        p.hp = max(1, int(p.max_hp * REVIVE_HEALTH))
        p.next_time = self.clock
        lvl.place(p, *lvl.free_near(p.x, p.y))
        self.broadcast(f"{rescuer.name} revives {p.name}!", GOLD)

    def _revive_percent(self, p: Player) -> int:
        return int(100 * p.revive_ticks / (REVIVE_SECONDS * TICKS_PER_SECOND))

    def _fill_stealth(self, p: Player, ticks: int) -> None:
        before = int(p.stealth)
        rate = STEALTH_MAX / (STEALTH_FILL_SECONDS * TICKS_PER_SECOND)
        p.stealth = min(p.stealth_cap, p.stealth + ticks * rate)
        if int(p.stealth) != before:
            self.dirty = True

    def check_reset(self, now: float) -> bool:
        """Start a fresh dungeon once the wipe delay is over. Returns True if it did."""
        if self.reset_at is None or now < self.reset_at:
            return False
        self.reset_run()
        return True

    # ----------------------------------------------------------- actions

    def _perform(self, p: Player, act: dict) -> None:
        lvl = self.levels[p.depth]
        a = act["a"]
        cost = 0
        if a == "move":
            cost = self._player_move(p, lvl, act["dx"], act["dy"])
        elif a == "descend":
            if (p.x, p.y) == lvl.down_front:
                cost = self._take_stairs(p, +1)
            else:
                self.tell(p, "There is no downward staircase next to you.", GRAY)
        elif a == "ascend":
            if (p.x, p.y) == lvl.up_front:
                cost = self._take_stairs(p, -1)
            else:
                self.tell(p, "There is no upward staircase next to you.", GRAY)
        elif a == "pickup":
            if self._pick_up(p, lvl):
                cost = TICKS_PER_TURN
            elif (p.x, p.y) not in lvl.items:
                self.tell(p, "There is nothing here to pick up.", GRAY)
        elif a == "use":
            cost = self._use(p, act["slot"])
        elif a == "drop":
            cost = self._drop(p, lvl, act["slot"])
        elif a == "dropgold":
            cost = self._drop_gold(p, lvl)
        if cost > 0 and p.alive:
            if p.haste_until > self.clock:
                cost //= 2
            p.next_time = self.clock + cost
            p.turns += 1
            if a in ("move", "descend", "ascend"):
                p.stealth = max(0.0, p.stealth - STEALTH_MOVE_DRAIN)

    def _player_move(self, p: Player, lvl: Level, dx: int, dy: int) -> int:
        nx, ny = p.x + dx, p.y + dy
        if not lvl.in_bounds(nx, ny) or lvl.diagonal_blocked(p.x, p.y, nx, ny):
            return 0
        tile = lvl.tiles[nx, ny]
        if tile == STAIRS_DOWN:
            return self._take_stairs(p, +1)
        if tile == STAIRS_UP:
            return self._take_stairs(p, -1)
        other = lvl.actor_at(nx, ny)
        if other is not None:
            if other.is_player:  # swap places with an ally, as in Brogue
                ox, oy = p.x, p.y
                lvl.remove(p)
                lvl.remove(other)
                lvl.place(p, nx, ny)
                lvl.place(other, ox, oy)
                self.tell(other, f"{p.name} swaps places with you.", GRAY)
                self._step_onto(p, lvl)
                return p.move_cost
            self._attack(p, other)
            return p.attack_cost
        if not lvl.walkable[nx, ny]:
            return 0  # bumping a wall costs no time
        lvl.move(p, nx, ny)
        self._step_onto(p, lvl)
        return p.move_cost

    # -------------------------------------------------------------- items

    def _step_onto(self, p: Player, lvl: Level) -> None:
        """Potions and gold are collected on contact; anything else waits for the pickup key."""
        item = lvl.items.get((p.x, p.y))
        if item is None:
            return
        if item.category in AUTO_PICKUP:
            self._pick_up(p, lvl)
        else:
            self.tell(p, f"You see {self._a(item)} here. Press g to pick it up.", GRAY)

    def _pick_up(self, p: Player, lvl: Level) -> bool:
        item = lvl.items.get((p.x, p.y))
        if item is None:
            return False
        stack = next((i for i in p.pack if i.stacks and i.kind == item.kind), None)
        if item.category == "gold":
            p.gold += item.count
        elif stack is not None:
            stack.count += item.count
        elif len(p.pack) < PACK_SIZE:
            p.pack.append(item)
        else:
            self.tell(p, f"Your pack is full. {item.label.capitalize()} lies here.", GRAY)
            return False
        del lvl.items[(p.x, p.y)]
        p.pack_dirty = True
        self.tell(p, f"You pick up {self._a(item)}.", GOLD)
        self._narrate(lvl, [(p.x, p.y)], set(), lambda v: (f"{p.name} picks up {self._a(item)}.", GRAY), exclude=p)
        return True

    @staticmethod
    def _a(item: Item) -> str:
        return item.label if item.category == "gold" or item.count > 1 else _article(item.label)

    def _use(self, p: Player, slot: int) -> int:
        if slot >= len(p.pack):
            return 0
        item = p.pack[slot]
        if item.category == "weapon":
            p.weapon = None if p.weapon is item else item
        elif item.category == "armor":
            p.armor = None if p.armor is item else item
        elif item.heal and p.hp >= p.max_hp:
            self.tell(p, "You are already at full health.", GRAY)
            return 0
        else:
            p.hp = min(p.max_hp, p.hp + item.heal)
            if item.haste:
                p.haste_until = self.clock + int(item.haste * TICKS_PER_SECOND)
            self.tell(p, "You feel better." if item.heal else "Everything around you slows down.", GOLD)
            self._take_one(p, item)
            return TICKS_PER_TURN
        apply_gear(p)
        p.pack_dirty = True
        equipped = item is p.weapon or item is p.armor
        self.tell(p, f"You {'equip' if equipped else 'remove'} the {item.name}.", WHITE)
        return TICKS_PER_TURN

    def _take_one(self, p: Player, item: Item) -> Item:
        """Removes one of `item` from the pack and returns it."""
        p.pack_dirty = True
        if item.count > 1:
            item.count -= 1
            return make_item(item.kind)
        p.pack.remove(item)
        if item is p.weapon:
            p.weapon = None
        if item is p.armor:
            p.armor = None
        apply_gear(p)
        return item

    def _drop(self, p: Player, lvl: Level, slot: int) -> int:
        if slot >= len(p.pack):
            return 0
        item = self._take_one(p, p.pack[slot])
        lvl.items[lvl.free_item_spot(p.x, p.y)] = item
        self.tell(p, f"You drop {self._a(item)}.", WHITE)
        self._narrate(lvl, [(p.x, p.y)], set(), lambda v: (f"{p.name} drops {self._a(item)}.", GRAY), exclude=p)
        return TICKS_PER_TURN

    def _drop_gold(self, p: Player, lvl: Level) -> int:
        amount = min(GOLD_DROP, p.gold)
        if amount == 0:
            self.tell(p, "You have no gold.", GRAY)
            return 0
        p.gold -= amount
        p.pack_dirty = True
        lvl.items[lvl.free_item_spot(p.x, p.y)] = make_gold(amount)
        self.tell(p, f"You drop {amount} gold.", WHITE)
        self._narrate(lvl, [(p.x, p.y)], set(), lambda v: (f"{p.name} drops {amount} gold.", GRAY), exclude=p)
        return TICKS_PER_TURN

    def _scatter_belongings(self, p: Player, lvl: Level) -> None:
        """A fallen player's gear lands around them for the party to collect."""
        loot = p.pack + ([make_gold(p.gold)] if p.gold else [])
        for item in loot:
            lvl.items[lvl.free_item_spot(p.x, p.y)] = item
        p.pack, p.gold, p.weapon, p.armor, p.pack_dirty = [], 0, None, None, True
        apply_gear(p)

    def _take_stairs(self, p: Player, step: int) -> int:
        new_depth = p.depth + step
        if new_depth < 1:
            self.tell(p, "The way out is sealed. The only way is down.", GRAY)
            return 0
        old = self.levels[p.depth]
        verb = "descends" if step > 0 else "climbs"
        self._narrate(old, [(p.x, p.y)], set(), lambda v: (f"{p.name} {verb} the stairs.", GRAY), exclude=p)
        old.remove(p)
        lvl = self.level(new_depth)
        lvl.place(p, *lvl.free_near(*(lvl.up_front if step > 0 else lvl.down_front)))
        p.needs_level = True
        self.tell(p, f"You {'descend' if step > 0 else 'ascend'} to depth {new_depth}.", WHITE)
        return p.move_cost

    def _regen(self, p: Player, cost: int) -> None:
        if p.hp >= p.max_hp:
            p.regen_acc = 0
            return
        p.regen_acc += cost * p.max_hp
        need = REGEN_TURNS * TICKS_PER_TURN
        while p.regen_acc >= need and p.hp < p.max_hp:
            p.hp += 1
            p.regen_acc -= need
            self.dirty = True

    # ------------------------------------------------------------ combat

    def _attack(self, att, dfn) -> None:
        lvl = self.levels[att.depth]
        if att.is_player:
            att.stealth = 0.0  # fighting is loud
            self._note_fight(att, dfn)
        elif dfn.is_player:
            self._note_fight(dfn, att)
        sneak = isinstance(dfn, Monster) and dfn.state != "hunting"
        prob = 100.0 if sneak else att.accuracy * DEFENSE_FACTOR ** dfn.defense
        where = [(att.x, att.y), (dfn.x, dfn.y)]
        if self.rng.random() * 100 < prob:
            dmg = self.rng.randint(*att.damage) * (3 if sneak else 1)  # Brogue-style sneak attack
            dfn.hp -= dmg

            def hit(v):
                tail = " by surprise!" if sneak else "."
                color = RED if v is dfn else (WHITE if v is att else GRAY)
                return f"{self._n(att, v, True)} {self._verb(att, v, att.verbs)} {self._n(dfn, v)}{tail}", color
            self._narrate(lvl, where, {att, dfn}, hit)
        else:
            self._narrate(lvl, where, {att, dfn}, lambda v: (
                f"{self._n(att, v, True)} {self._verb(att, v, ('misses', 'miss'))} {self._n(dfn, v)}.", GRAY))
        if isinstance(dfn, Monster) and dfn.hp > 0:
            self._hunt(dfn, att)
        if dfn.hp <= 0:
            self._kill(dfn, att)

    @staticmethod
    def _note_fight(p: Player, m: Monster) -> None:
        if m.kind and (not p.hardest or danger(m.kind) > danger(p.hardest)):
            p.hardest = m.kind

    def _kill(self, victim, killer) -> None:
        lvl = self.levels[victim.depth]
        where = [(victim.x, victim.y)]
        if isinstance(victim, Monster):
            self._narrate(lvl, where, {killer, victim}, lambda v: (
                f"{self._n(killer, v, True)} {self._verb(killer, v, ('kills', 'kill'))} {self._n(victim, v)}.",
                WHITE if v is killer else GRAY))
            lvl.remove(victim)
            lvl.monsters.remove(victim)
            if killer is not None and killer.is_player:
                killer.kills += 1
                killer.kill_tally[victim.name] = killer.kill_tally.get(victim.name, 0) + 1
            return
        revivable = self.mode == "Revive"
        self._narrate(lvl, where, {victim}, lambda v: (
            ("You are down..." if revivable else "You die...") if v is victim
            else f"{victim.name} {'is down' if revivable else 'dies'}!", RED))
        victim.alive, victim.hp, victim.pending, victim.hold = False, 0, None, None
        victim.final_gold = victim.gold
        victim.death = f"Killed by {_article(killer.name)} on depth {victim.depth}." if killer else "Died."
        lvl.remove(victim)
        if revivable:  # they keep their gear; it comes back with them
            victim.downed, victim.revive_ticks = True, 0
            lvl.downed.append(victim)
            if any(p.alive for p in self.players.values()):
                for p in self.players.values():
                    if p is not victim:
                        self.tell(p, f"{victim.name} is down on floor {victim.depth}! Stand by the {BONES_GLYPH} "
                                     f"for {REVIVE_SECONDS:.0f} seconds to revive.", ORANGE)
        else:
            self._scatter_belongings(victim, lvl)
        self._check_all_dead()

    @staticmethod
    def carried_gold(p: Player) -> int:
        return p.gold if p.final_gold is None else p.final_gold

    def score_of(self, p: Player) -> int:
        return p.turns * SCORE_PER_MOVE + self.carried_gold(p) * SCORE_PER_GOLD

    def _check_all_dead(self) -> None:
        if self.players and not any(p.alive for p in self.players.values()) and self.reset_at is None:
            self.reset_at = time.monotonic() + RESET_DELAY
            self.broadcast("The whole party has fallen. A new dungeon takes shape...", RED)
            for p in sorted(self.players.values(), key=self.score_of, reverse=True):
                self.broadcast(f"{p.name}: {self.score_of(p)} points, {p.kills} kills", GOLD)

    def reset_run(self) -> None:
        self.seed = random.randrange(1, 2 ** 31)
        self.rng = random.Random(self.seed * 7919 + 1)
        self.levels, self.offline = {}, {}
        self.run += 1
        self.run_start = self.clock
        self.reset_at = None
        lvl = self.level(1)
        for p in self.players.values():
            reset_player(p)
            lvl.place(p, *lvl.free_near(*lvl.up_front))
            p.needs_level = True
        self.dirty = True
        self.broadcast(f"Run {self.run} begins. Good luck!", GOLD)

    # ---------------------------------------------------------------- AI

    def _hunt(self, m: Monster, target) -> None:
        m.state, m.target_id, m.last_seen = "hunting", target.id, (target.x, target.y)

    @staticmethod
    def _notice_range(p: Player, base: int) -> float:
        """How far away a monster can notice this player; stealth shrinks it."""
        return base * (1 - (1 - STEALTH_RANGE_MIN) * p.stealth / STEALTH_MAX)

    def _monster_act(self, m: Monster) -> None:
        cost = max(1, self._monster_turn(m, self.levels[m.depth]))
        m.next_time = self.clock + int(cost * self.monster_time)

    def _monster_turn(self, m: Monster, lvl: Level) -> int:
        seen_by = [p for p in self._living_on(m.depth) if self.fov(p)[m.x, m.y]]  # FOV is symmetric
        if m.state == "sleeping":
            for p in sorted(seen_by, key=lambda p: cheb(m, p)):
                if cheb(m, p) <= self._notice_range(p, NOTICE_RANGE_SLEEPING) and self.rng.random() < 0.33:
                    self._hunt(m, p)
                    self._narrate(lvl, [(m.x, m.y)], set(), lambda v: (f"The {m.name} wakes up!", ORANGE))
                    break
            return TICKS_PER_TURN

        targets = [p for p in seen_by
                   if m.state == "hunting" or cheb(m, p) <= self._notice_range(p, NOTICE_RANGE_AWAKE)]
        if targets:
            t = min(targets, key=lambda p: (cheb(m, p), p.id))
            self._hunt(m, t)
            if cheb(m, t) == 1 and not lvl.diagonal_blocked(m.x, m.y, t.x, t.y):
                self._attack(m, t)
                return m.attack_cost
            return self._step_toward(m, lvl, t.x, t.y) or TICKS_PER_TURN

        if m.state == "hunting":  # lost sight: go to where the prey was last seen
            if m.last_seen and (m.x, m.y) != m.last_seen:
                cost = self._step_toward(m, lvl, *m.last_seen)
                if cost:
                    return cost
            m.state, m.target_id, m.last_seen = "wandering", None, None

        if m.wander_target is None or (m.x, m.y) == m.wander_target:
            m.wander_target = lvl.random_floor(self.rng)
        cost = self._step_toward(m, lvl, *m.wander_target)
        if not cost:
            m.wander_target = None
        return cost or TICKS_PER_TURN

    def _step_toward(self, m: Monster, lvl: Level, tx: int, ty: int) -> int:
        dist = algo.dijkstra(lvl.walkable, [(tx, ty)])
        best, best_d = None, dist[m.x, m.y]
        dirs = DIRS8[:]
        self.rng.shuffle(dirs)
        for dx, dy in dirs:
            nx, ny = m.x + dx, m.y + dy
            if not lvl.in_bounds(nx, ny) or not lvl.walkable[nx, ny]:
                continue
            if lvl.diagonal_blocked(m.x, m.y, nx, ny) or lvl.actor_at(nx, ny) is not None:
                continue
            if dist[nx, ny] < best_d:
                best, best_d = (nx, ny), dist[nx, ny]
        if best is None:
            return 0
        lvl.move(m, *best)
        return m.move_cost

    # ------------------------------------------------------------- views

    def level_msg(self, depth: int) -> dict:
        lvl = self.level(depth)
        return {"t": "level", "depth": depth, "run": self.run, "w": MAP_W, "h": MAP_H,
                "tiles": protocol.pack_u8(lvl.tiles)}

    def _status(self, p: Player) -> list[str]:
        if p.downed:
            if p.revive_ticks:
                return ["revive", f"You are being revived... {self._revive_percent(p)}%"]
            return ["dead", "You are down, waiting for a teammate."]
        if not p.alive:
            return ["dead", "You are dead. The run restarts when the whole party has fallen."]
        for other in self.levels[p.depth].downed:
            if cheb(p, other) <= 1:
                return ["revive", f"Reviving {other.name}... {self._revive_percent(other)}%"]
        return ["go", ""]

    def pack_msg(self, p: Player) -> dict:
        pack = [{"name": i.label, "g": i.glyph, "c": list(i.color), "info": i.info,
                 "eq": i is p.weapon or i is p.armor} for i in p.pack]
        return {"t": "pack", "pack": pack, "gold": p.gold, "defense": p.defense,
                "dmg": f"{p.damage[0]}-{p.damage[1]}", "stealth_cap": p.stealth_cap}

    def state_for(self, p: Player) -> dict:
        lvl = self.level(p.depth)
        vis = self.fov(p) if p.alive or p.downed else np.zeros((MAP_W, MAP_H), dtype=bool)
        ents = []
        for a in lvl.occupant.values():
            seen = bool(vis[a.x, a.y])
            if seen or a.is_player:  # allies on your depth are always shown
                ents.append({"id": a.id, "g": a.glyph, "c": list(a.color), "x": a.x, "y": a.y,
                             "name": a.name, "hp": a.hp, "mhp": a.max_hp, "p": a.is_player,
                             "seen": seen, "st": getattr(a, "state", "")})
        for a in lvl.downed:
            ents.append({"id": a.id, "g": BONES_GLYPH, "c": list(BONE), "x": a.x, "y": a.y, "name": a.name,
                         "hp": 0, "mhp": a.max_hp, "p": True, "seen": bool(vis[a.x, a.y]), "st": "down"})
        items = [{"x": x, "y": y, "g": i.glyph, "c": list(i.color), "name": i.label, "info": i.info,
                  "auto": i.category in AUTO_PICKUP}
                 for (x, y), i in lvl.items.items() if vis[x, y]]
        party = []
        for q in sorted(self.players.values(), key=lambda q: q.id):
            party.append({"id": q.id, "name": q.name, "c": list(q.color), "hp": q.hp, "mhp": q.max_hp,
                          "depth": q.depth, "alive": q.alive, "down": q.downed, "g": q.glyph,
                          "ping": None if q.ping is None else round(q.ping)})
        status = self._status(p)
        return {"t": "state", "you": p.id, "run": self.run, "depth": p.depth, "alive": p.alive,
                "visible": protocol.pack_bool(vis), "ents": ents, "items": items, "party": party,
                "time": (self.clock - self.run_start) / TICKS_PER_SECOND,
                "haste": p.haste_until > self.clock, "stealth": int(p.stealth), "downed": p.downed,
                "detect": round(self._notice_range(p, NOTICE_RANGE_AWAKE)),
                "status": status, "turns": p.turns, "kills": p.kills, "death": p.death,
                "score": self.score_of(p), "score_gold": self.carried_gold(p), "tally": p.kill_tally,
                "hardest": p.hardest}
