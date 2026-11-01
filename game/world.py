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

Lakes and pits aren't `walkable`, so monsters and the party's items stay out of them.
Water can leave islands: walkable tiles outside `Level.mainland`, which is everything
that can be walked to from the stairs. Items can lie on them, but nothing that the
game needs does, and nothing but a player's own choice ever puts anyone there.
A levitating player can cross anything in `Level.hover`. Walking into a pit drops you
a floor; see `_fall`. A locked room's floor isn't in `floor_cells`, so nothing spawns
or lands there, and its key is placed by `_place_keys`.

The server is single-threaded: call `submit`, `chat`, `join`, `leave` and
`advance`, then drain `outbox` and send `state_for(player)` to everyone.
"""
from __future__ import annotations

import itertools
import random
import time
from collections import deque
from dataclasses import dataclass

import numpy as np

from . import algo, mapgen, protocol, seasons
from .constants import (ARCHER_RANGE, ARCHER_RELOAD, OGRE_PEAK, OGRE_PEAK_WEIGHT, SLIME_COUNT, SLIME_FLOORS, SLIME_TRAIL,
                        SLOW_FACTOR, SLOW_SECONDS, TOXIN_DAMAGE, TOXIN_SECONDS, ARROW_PILE, ATRIUM_FLOOR, ATTACK_STAMINA, BONES_GLYPH, BREATH_DAMAGE, BREATH_RANGE, BREATH_SECONDS,
                        CLOAK_FLOORS, CRIT_DAMAGE, CRIT_STEALTH, CULT_CHANCE, CULT_FIRST,
                        DRAGON_FLOOR, HOARD_GOLD, HOARD_PILES, POTION_ROOM, TOWER_FIRST, TOWER_MONSTERS, GAS_COOLDOWN, GAS_DAMAGE, GAS_REACH, GAS_SECONDS, GAS_TRIGGER, LAST_FLOOR,
                        REFLECT_SECONDS, SCORE_STEPS,
                        SUMMON_SECONDS, SUMMON_SIZE, TIDE_MAX, TIDE_SECONDS, TIDE_SIZE, VICTORY_SECONDS, WIN_POINTS,
                        MONSTER_SWING, WEAPON_DRAIN, WEAPON_FREEZE_CHANCE, WEAPON_FREEZE_SECONDS, WOLF_CHANCE, WOLF_FIRST, WOLF_SIZE,
                        CULT_SIZE, DEEPEST_TABLE, DEFENSE_FACTOR, FALL_DAMAGE, GOLD_DROP, LAVA_DAMAGE, SNEAK_DAMAGE,
                        WAND_BURN, WAND_BURN_TURNS, WAND_DAMAGE, WAND_RANGE,
                        KEY_DISTANCE, SPRINT_MOVE_COST, SPRINT_STAMINA, STAMINA_FILL_SECONDS, STAMINA_MAX,
                        STAMINA_REST_SECONDS, TELEPORT_STEPS, TIRED_ATTACK, TORCH_NOTICE, TORCH_RADIUS,
                        LEVITATION_STOCK_CHANCE, LOCKED_ROOM_CHANCE, LOCKED_ROOM_FLOORS, MAP_H, MAP_W,
                        MERCHANT_CHANCE, MERCHANT_EVERY, MERCHANT_STOCK, MONSTER_TIME, NOTICE_RANGE_AWAKE,
                        NOTICE_RANGE_SLEEPING, PACK_SIZE, REGEN_TURNS, RESET_DELAY, REVIVE_HEALTH,
                        REVIVE_SECONDS, SCORE_PER_GOLD, STEALTH_FILL_SECONDS,
                        STEALTH_MAX, STEALTH_MOVE_DRAIN, STEALTH_RANGE_MIN, TICKS_PER_SECOND,
                        TICKS_PER_TURN)
from .entities import (MONSTERS, PLAYER_COLOR_NAMES, PLAYER_COLORS, PLAYER_GLYPHS, Merchant, Monster, Player, apply_gear,
                       danger, make_merchant, make_monster, make_player, reset_player)
from .items import (AUTO_PICKUP, ITEMS, Item, enhance_weapon, make_amulet, make_cloak, make_gold, make_item, make_key,
                    make_wand)
from .tiles import (ALTAR, ALTAR_SPENT, DEEP, DOOR, FLOOR, FOLIAGE, GRASS, HOVER, LAVA, LOCK_COLORS, LOCKED, PIT, POND,
                    SHALLOW, STAIRS_DOWN, STAIRS_UP, TRAMPLED, TRANSPARENT,
                    WALKABLE)

DIRS8 = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]

WHITE = (230, 230, 230)
BONE = (225, 220, 195)
GRAY = (160, 160, 160)
RED = (255, 100, 100)
ORANGE = (255, 170, 80)
GOLD = (255, 215, 90)
PURPLE = (225, 140, 255)
TEAL = (150, 255, 240)

PACK_KINDS = ("cultist", "cult_leader", "wolf")
AMULET_FROM_DOORS, AMULET_FROM_STAIRS = 15, 20  # steps' walk
PATH_MAPS = 256  # distance maps a level keeps before starting over
WEAR_OFF = (("levitate_until", "You drift back down to the ground."),
            ("waterwalk_until", "Your feet stop feeling so light."),
            ("lavawalk_until", "The heat starts to reach your feet."))


def cheb(a, b) -> int:
    return max(abs(a.x - b.x), abs(a.y - b.y))


def _article(name: str) -> str:
    return ("an " if name[:1] in "aeiou" else "a ") + name


def appears_on(entry: dict, depth: int) -> bool:
    """Whether a monster or item turns up at this depth. Entries running to the end of
    the lists keep turning up on the floors past it."""
    first, last = entry["depths"]
    return first <= depth and (depth <= last or last == DEEPEST_TABLE) and entry["weight"] > 0


def line_between(a: tuple[int, int], b: tuple[int, int]) -> list[tuple[int, int]]:
    """The tiles a bolt crosses, after `a` up to and including `b`."""
    steps = max(abs(b[0] - a[0]), abs(b[1] - a[1]))
    return [(round(a[0] + (b[0] - a[0]) * i / steps), round(a[1] + (b[1] - a[1]) * i / steps))
            for i in range(1, steps + 1)]


@dataclass
class Point:
    x: int
    y: int


@dataclass
class LockedRoom:
    depth: int
    key_depth: int
    color: str


def plan_locked_rooms(seed: int) -> dict[int, LockedRoom]:
    """Settled for the whole run up front, because a key can be found before its door."""
    rng = random.Random(f"{seed}:locked")
    colors = list(LOCK_COLORS)
    rng.shuffle(colors)
    rooms = {}
    for depth in range(LOCKED_ROOM_FLOORS[0], LOCKED_ROOM_FLOORS[1] + 1):
        if colors and rng.random() < LOCKED_ROOM_CHANCE:
            rooms[depth] = LockedRoom(depth, depth + rng.choice((-KEY_DISTANCE, KEY_DISTANCE)), colors.pop())
    return rooms


class Level:
    def __init__(self, depth: int, gen: mapgen.GeneratedLevel):
        self.depth = depth
        self.tiles = gen.tiles
        self.up, self.up_front = gen.up, gen.up_front
        self.down, self.down_front = gen.down, gen.down_front
        self.walkable = WALKABLE[self.tiles]
        self.hover = HOVER[self.tiles]
        self.is_door = self.tiles == DOOR
        self.plants = (self.tiles == GRASS) | (self.tiles == FOLIAGE)
        self.changes: list[list[int]] = []  # tiles to tell the players about
        self.gas: dict[tuple[int, int], int] = {}  # toxic gas, and the tick each tile clears
        self.slime: dict[tuple[int, int], int] = {}  # slime trails, the same way
        self.lair, self.side_rooms = gen.lair, gen.side_rooms
        self._base_transparent = TRANSPARENT[self.tiles]
        self.vault, self.lock = gen.vault, gen.lock
        open_floor = self.walkable if gen.vault is None else self.walkable & ~gen.vault
        self.floor_cells = [(int(x), int(y)) for x, y in np.argwhere(open_floor)]
        self.lava_cells = [(int(x), int(y)) for x, y in np.argwhere(self.tiles == LAVA)]
        self.mainland = algo.dijkstra(self.walkable, [gen.up_front]) < algo.INF
        self.land_cells = [(int(x), int(y)) for x, y in np.argwhere(self.mainland)]
        self.torch_light = [self._torch_map(*t) for t in gen.torches]  # one brightness map, 0 to 1, per torch
        self.light = np.max(self.torch_light, axis=0) if self.torch_light else np.zeros((MAP_W, MAP_H))
        self.occupant: dict[tuple[int, int], object] = {}
        self.monsters: list[Monster] = []
        self.items: dict[tuple[int, int], Item] = {}   # one item per tile
        self.downed: list[Player] = []                 # Revive mode: bones on this level
        self.merchant: Merchant | None = None
        self.door_version = 0  # bumps whenever someone enters or leaves a doorway
        self._paths: dict[tuple[int, int], np.ndarray] = {}
        self._transparent = None
        self._transparent_version = -1

    def _torch_map(self, torch: tuple[int, int], front: tuple[int, int]) -> np.ndarray:
        """Bright at the torch and fading to nothing at its radius. Walls and shut doors stop it."""
        reach = algo.compute_fov(self._base_transparent, front[0], front[1], TORCH_RADIUS)
        xs, ys = np.indices((MAP_W, MAP_H))
        glow = reach * np.clip(1 - np.hypot(xs - torch[0], ys - torch[1]) / TORCH_RADIUS, 0, 1)
        glow[torch] = 1.0
        return glow

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < MAP_W and 0 <= y < MAP_H

    def actor_at(self, x: int, y: int):
        return self.occupant.get((x, y))

    def place(self, a, x: int, y: int) -> None:
        a.x, a.y, a.depth = x, y, self.depth
        self.occupant[(x, y)] = a
        if self.is_door[x, y]:
            self.door_version += 1
        if self.plants[x, y]:
            self._trample(x, y)

    def remove(self, a) -> None:
        if self.occupant.get((a.x, a.y)) is a:
            del self.occupant[(a.x, a.y)]
            if self.is_door[a.x, a.y]:
                self.door_version += 1

    def move(self, a, x: int, y: int) -> None:
        self.remove(a)
        self.place(a, x, y)

    def _trample(self, x: int, y: int) -> None:
        """Anyone walking through plants flattens them for good, which opens up the view."""
        self.tiles[x, y] = TRAMPLED
        self.plants[x, y] = False
        self._base_transparent[x, y] = True
        self.door_version += 1
        self.changes.append([x, y, TRAMPLED])

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
        """Brogue rule: no cutting diagonally past a wall corner. Water and pits aren't corners."""
        if x == nx or y == ny:
            return False
        return not self.hover[nx, y] or not self.hover[x, ny]

    def _closest_free(self, x: int, y: int, taken: dict, ground: np.ndarray) -> tuple[int, int]:
        queue, seen = deque([(x, y)]), {(x, y)}
        while queue:
            cx, cy = queue.popleft()
            if self.walkable[cx, cy] and ground[cx, cy] and (cx, cy) not in taken:
                return cx, cy
            for dx, dy in DIRS8:
                n = (cx + dx, cy + dy)
                if self.in_bounds(*n) and n not in seen and self.hover[n]:
                    seen.add(n)
                    queue.append(n)
        return self.nearest_floor(x, y, taken)  # shut in by walls: a player without collision

    def nearest_floor(self, x: int, y: int, taken: dict) -> tuple[int, int]:
        """The closest open floor as the crow flies, whatever lies between."""
        return min((c for c in self.land_cells if c not in taken),
                   key=lambda c: (max(abs(c[0] - x), abs(c[1] - y)), c), default=(x, y))

    def free_near(self, x: int, y: int) -> tuple[int, int]:
        """The closest tile to (x, y) with nobody on it that has a way to the stairs."""
        return self._closest_free(x, y, self.occupant, self.mainland)

    def free_item_spot(self, x: int, y: int) -> tuple[int, int]:
        """The closest walkable tile to (x, y) with no item on it."""
        return self._closest_free(x, y, self.items, self.walkable)

    def distances_to(self, x: int, y: int) -> np.ndarray:
        """How far every tile is from (x, y) on foot. Monsters share these, since a party draws
        many of them to the same tiles, and only unlocking a door changes the answers."""
        if (x, y) not in self._paths:
            if len(self._paths) >= PATH_MAPS:
                self._paths.clear()
            self._paths[(x, y)] = algo.dijkstra(self.walkable, [(x, y)])
        return self._paths[(x, y)]

    def random_floor(self, rng: random.Random) -> tuple[int, int]:
        return rng.choice(self.land_cells)

    def landing(self, x: int, y: int) -> tuple[int, int]:
        """Where someone falling in from above comes down: the closest open floor tile, or
        lava, which nobody up there could have seen."""
        spots = [c for c in self.land_cells + self.lava_cells if c not in self.occupant]
        return min(spots, key=lambda c: (max(abs(c[0] - x), abs(c[1] - y)), c))

    def open_all_round(self, x: int, y: int) -> bool:
        return all(self.walkable[x + dx, y + dy] for dx, dy in DIRS8)

    def add_altar(self, x: int, y: int) -> None:
        """Altars stand in the open and you can't walk over them, but you can see past them."""
        self.tiles[x, y] = ALTAR
        self.walkable[x, y] = self.hover[x, y] = self.mainland[x, y] = self.plants[x, y] = False
        self._base_transparent[x, y] = True
        self.door_version += 1
        self.floor_cells.remove((x, y))
        self.land_cells.remove((x, y))
        self._paths.clear()
        self.changes.append([x, y, ALTAR])

    def drain_pond(self, x: int, y: int) -> list[tuple[int, int]]:
        """Uses up a whole pond, leaving ordinary shallow water. Returns its tiles."""
        pond, queue = {(x, y)}, deque([(x, y)])
        while queue:
            cx, cy = queue.popleft()
            for dx, dy in DIRS8:
                n = (cx + dx, cy + dy)
                if n not in pond and self.tiles[n] == POND:
                    pond.add(n)
                    queue.append(n)
        for cx, cy in pond:
            self.tiles[cx, cy] = SHALLOW
            self.changes.append([cx, cy, SHALLOW])
        return sorted(pond)

    def room_around(self, x: int, y: int) -> dict[tuple[int, int], int]:
        """The open tiles within GAS_REACH of a spot, each with how many steps off it is.
        Doors and walls end it, so it spreads around corners but not through them."""
        room, queue = {(x, y): 0}, deque([(x, y)])
        while queue:
            cx, cy = queue.popleft()
            for dx, dy in DIRS8:
                n = (cx + dx, cy + dy)
                if n in room or max(abs(n[0] - x), abs(n[1] - y)) > GAS_REACH:
                    continue
                if self.in_bounds(*n) and self.hover[n] and not self.is_door[n]:
                    room[n] = room[(cx, cy)] + 1
                    queue.append(n)
        return room

    def spend_altar(self, x: int, y: int) -> None:
        self.tiles[x, y] = ALTAR_SPENT
        self.changes.append([x, y, ALTAR_SPENT])

    def unlock(self) -> None:
        self.tiles[self.lock] = DOOR
        self.walkable[self.lock] = self.hover[self.lock] = self.is_door[self.lock] = True
        self.mainland[self.lock] = True
        self.mainland[self.vault] = True
        self.lock = None
        self.door_version += 1
        self._paths.clear()


class World:
    def __init__(self, seed: int | None = None, monster_time: float = MONSTER_TIME, mode: str = "Classic",
                 season_fn=lambda: None):
        self.seed = seed if seed is not None else random.randrange(1, 2 ** 31)
        self.monster_time = monster_time
        self.mode = mode
        self.season_fn = season_fn             # checked once a run, so looks never change mid-dungeon
        self.season = season_fn()
        self.rng = random.Random(self.seed * 7919 + 1)
        self.locked_rooms = plan_locked_rooms(self.seed)
        self.necromancer: Monster | None = None
        self.necro_awake = False
        self.tide_at = 0                       # tick when the next zombies come for anyone chased
        self.victory = ""                      # who got out with the Amulet
        self.cloaks = 0                        # handed out so far this run
        self.cloak_floors: list[int] = []      # floors not built yet that have one waiting
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
            room = self.locked_rooms.get(depth)
            lvl = Level(depth, mapgen.generate(self.seed, depth, LOCKED[room.color] if room else None))
            self.levels[depth] = lvl
            self._populate(lvl)
        return lvl

    def _populate(self, lvl: Level) -> None:
        rng = random.Random(f"{self.seed}:{lvl.depth}:monsters")
        dist = algo.dijkstra(lvl.walkable, [lvl.up_front])
        spots = [(int(x), int(y)) for x, y in np.argwhere(lvl.walkable & (dist > 24) & (dist < algo.INF))]
        quiet = lvl.depth in (ATRIUM_FLOOR, LAST_FLOOR)  # nothing else lives in the atrium or the lair
        if quiet:
            spots = []
        kinds = [(k, t["weight"]) for k, t in MONSTERS.items() if appears_on(t, lvl.depth)]
        if lvl.depth >= TOWER_FIRST:  # still has archers at the very top
            kinds = list(TOWER_MONSTERS) + [(k, w) for k, w in kinds if k == "skeleton_archer"]
        if OGRE_PEAK[0] <= lvl.depth <= OGRE_PEAK[1]:
            kinds = [(k, w * OGRE_PEAK_WEIGHT if k == "ogre" else w) for k, w in kinds]
        rng.shuffle(spots)
        for x, y in spots[:4 + lvl.depth // 2 + rng.randint(0, 3)]:
            kind = rng.choices([k for k, _ in kinds], [w for _, w in kinds])[0]
            m = seasons.dress_monster(make_monster(kind, next(self._ids)), self.season)
            m.state = "sleeping" if rng.random() < 0.6 else "wandering"
            m.lag = m.next_time = rng.randrange(TICKS_PER_TURN)
            lvl.place(m, x, y)
            lvl.monsters.append(m)
        if not quiet:
            self._add_cult(lvl)
            self._add_wolves(lvl)
            self._add_slimes(lvl)
        if lvl.depth == DRAGON_FLOOR:
            self._add_dragon(lvl)
        self._add_items(lvl)
        self._stock_vault(lvl)
        self._place_keys(lvl)
        if lvl.lair:
            self._add_lair(lvl)
        rng = random.Random(f"{self.seed}:{lvl.depth}:cloaks")
        for _ in range(self.cloak_floors.count(lvl.depth)):
            lvl.items[self._empty_floor(lvl, rng)] = self._cloak()
        if lvl.depth % MERCHANT_EVERY == 0:
            self._add_merchant(lvl)

    def _add_cult(self, lvl: Level, force: bool = False) -> bool:
        rng = random.Random(f"{self.seed}:{lvl.depth}:cult")
        if not force and (lvl.depth < CULT_FIRST or rng.random() >= CULT_CHANCE):
            return False
        return self._add_pack(lvl, rng, "cult_leader", "cultist", CULT_SIZE, altar=True)

    def _add_wolves(self, lvl: Level) -> bool:
        rng = random.Random(f"{self.seed}:{lvl.depth}:wolves")
        if lvl.depth < WOLF_FIRST or rng.random() >= WOLF_CHANCE:
            return False
        return self._add_pack(lvl, rng, "wolf", "wolf", WOLF_SIZE)

    def _add_slimes(self, lvl: Level) -> None:
        """Scattered about, not in a group, and out of reach of the stairs."""
        if not SLIME_FLOORS[0] <= lvl.depth <= SLIME_FLOORS[1]:
            return
        rng = random.Random(f"{self.seed}:{lvl.depth}:slimes")
        from_stairs = lvl.distances_to(*lvl.up_front)
        spots = [c for c in lvl.land_cells if c not in lvl.occupant and 24 < from_stairs[c] < algo.INF]
        for spot in rng.sample(spots, min(len(spots), rng.randint(*SLIME_COUNT))):
            m = seasons.dress_monster(make_monster("slime", next(self._ids)), self.season)
            m.state = "wandering"
            m.lag = m.next_time = rng.randrange(TICKS_PER_TURN)
            lvl.place(m, *spot)
            lvl.monsters.append(m)

    def _add_pack(self, lvl: Level, rng: random.Random, lead: str, kind: str, size: tuple, altar: bool = False) -> bool:
        """A tight group, well away from the stairs. With an altar, it stands around that."""
        from_stairs = lvl.distances_to(*lvl.up_front)
        spots = [c for c in lvl.floor_cells if c not in lvl.occupant and 24 < from_stairs[c] < algo.INF]
        if len(spots) < size[1]:
            return False
        center = rng.choice(spots)
        if altar:
            room = [c for c in spots if c not in lvl.items and lvl.open_all_round(*c)]
            if not room:
                return False
            center = rng.choice(room)
            lvl.add_altar(*center)
            spots.remove(center)
        middle = lvl.distances_to(*center)
        spots.sort(key=lambda c: (middle[c], c))
        state = "sleeping" if rng.random() < 0.5 else "wandering"
        leader = None
        for spot in spots[:rng.randint(*size)]:
            m = seasons.dress_monster(make_monster(kind if leader else lead, next(self._ids)), self.season)
            m.state, m.leader, m.post = state, leader, center if altar else None
            m.lag = m.next_time = rng.randrange(TICKS_PER_TURN)
            lvl.place(m, *spot)
            lvl.monsters.append(m)
            leader = leader or m
        return True

    def _add_dragon(self, lvl: Level) -> None:
        """Asleep as far as it can get from the stairs."""
        from_stairs = lvl.distances_to(*lvl.up_front)
        spot = max((c for c in lvl.land_cells if c not in lvl.occupant), key=lambda c: (from_stairs[c], c))
        m = seasons.dress_monster(make_monster("dragon", next(self._ids)), self.season)
        m.state, m.next_time = "sleeping", 0
        lvl.place(m, *spot)
        lvl.monsters.append(m)

    def _add_lair(self, lvl: Level) -> None:
        """The necromancer, asleep, and the Amulet across the room from it: close enough to
        be in its sight, but with the stealth to do it, far enough to creep to and back."""
        rng = random.Random(f"{self.seed}:lair")
        m = seasons.dress_monster(make_monster("necromancer", next(self._ids)), self.season)
        m.state, m.next_time = "sleeping", rng.randrange(TICKS_PER_TURN)
        m.lag = m.next_time
        x, y = lvl.free_near(*lvl.lair)
        if (x, y) in lvl.occupant:
            lvl.remove(lvl.occupant[(x, y)])
        lvl.place(m, x, y)
        lvl.monsters.append(m)
        self.necromancer = m
        sight = algo.compute_fov(lvl._base_transparent, x, y, 0)
        walk = lvl.distances_to(x, y) // algo.CARDINAL_COST
        spots = [c for c in lvl.land_cells if c not in lvl.occupant and c not in lvl.items]
        near = [c for c in spots if sight[c] and 7 <= max(abs(c[0] - x), abs(c[1] - y)) <= 9 and walk[c] <= 13]
        # Well away from the ways in, so getting to it means going around the necromancer.
        doors = [(int(dx), int(dy)) for dx, dy in np.argwhere(lvl.is_door)]
        from_doors = algo.dijkstra(lvl.walkable, doors) // algo.CARDINAL_COST
        from_stairs = lvl.distances_to(*lvl.up_front) // algo.CARDINAL_COST
        far = [c for c in near if from_doors[c] >= AMULET_FROM_DOORS and from_stairs[c] >= AMULET_FROM_STAIRS]
        lvl.items[rng.choice(far or near) if near else min(spots, key=lambda c: abs(walk[c] - 8))] = make_amulet()
        self._fill_side_rooms(lvl, rng)

    def _fill_side_rooms(self, lvl: Level, rng: random.Random) -> None:
        hoard, potions = rng.sample(list(lvl.side_rooms), 2)
        for spot in rng.sample(hoard, min(HOARD_PILES, len(hoard))):
            lvl.items[spot] = self._gold(rng.randint(*HOARD_GOLD))
        kinds = [k for k, t in ITEMS.items() if t["category"] == "potion"]
        for spot in rng.sample(potions, min(POTION_ROOM, len(potions))):
            lvl.items[spot] = self._item(rng.choice(kinds))

    def _add_merchant(self, lvl: Level) -> None:
        rng = random.Random(f"{self.seed}:{lvl.depth}:merchant")
        if rng.random() >= MERCHANT_CHANCE:
            return
        dist = algo.dijkstra(lvl.walkable, [lvl.up_front])
        spots = [c for c in lvl.floor_cells if lvl.tiles[c] == FLOOR and 8 <= dist[c] < algo.INF
                 and c not in lvl.occupant and c not in lvl.items]
        if not spots:
            return
        m = make_merchant(next(self._ids), seasons.merchant_name(self.season))
        gear = [k for k, t in ITEMS.items() if t["category"] in ("weapon", "armor") and appears_on(t, lvl.depth)]
        kinds = rng.sample(gear, min(len(gear), rng.randint(*MERCHANT_STOCK)))
        if rng.random() < LEVITATION_STOCK_CHANCE:
            kinds.append("levitation")
        m.stock = {i: self._item(kind) for i, kind in enumerate(kinds)}
        lvl.place(m, *rng.choice(spots))
        lvl.merchant = m

    def _add_items(self, lvl: Level) -> None:
        rng = random.Random(f"{self.seed}:{lvl.depth}:items")
        spots = rng.sample(lvl.floor_cells, 12)
        kinds = [(k, t["weight"]) for k, t in ITEMS.items() if appears_on(t, lvl.depth)]
        for _ in range(3 + rng.randint(0, 2)):
            kind = rng.choices([k for k, _ in kinds], [w for _, w in kinds])[0]
            item = self._item(kind)
            if item.category == "ammo":
                item.count = rng.randint(*ARROW_PILE)
            lvl.items[spots.pop()] = item
        for _ in range(2 + rng.randint(0, 2)):
            lvl.items[spots.pop()] = self._gold(rng.randint(5, 15) * lvl.depth + 5)

    def _stock_vault(self, lvl: Level) -> None:
        """Better gear than the floor it's on, a potion and a good pile of gold."""
        if lvl.vault is None:
            return
        rng = random.Random(f"{self.seed}:{lvl.depth}:vault")
        cells = [(int(x), int(y)) for x, y in np.argwhere(lvl.vault)]
        rng.shuffle(cells)
        depth = lvl.depth + 3
        gear = [k for k, t in ITEMS.items() if t["category"] in ("weapon", "armor") and appears_on(t, depth)]
        potions = [k for k, t in ITEMS.items() if t["category"] == "potion" and appears_on(t, depth)]
        for kind in rng.sample(gear, 2) + [rng.choice(potions)]:
            lvl.items[cells.pop()] = self._item(kind)
        lvl.items[cells.pop()] = self._gold(rng.randint(30, 60) * lvl.depth)

    def _place_keys(self, lvl: Level) -> None:
        rng = random.Random(f"{self.seed}:{lvl.depth}:keys")
        for room in self.locked_rooms.values():
            if room.key_depth == lvl.depth:
                lvl.items[self._empty_floor(lvl, rng)] = self._key(room)

    @staticmethod
    def _empty_floor(lvl: Level, rng: random.Random) -> tuple[int, int]:
        return rng.choice([c for c in lvl.land_cells if c not in lvl.items and c not in lvl.occupant])

    def _promise_cloak(self, near: int) -> None:
        """One new cloak for one new player, on a random floor within reach of where they are."""
        rng = random.Random(f"{self.seed}:cloak:{self.cloaks}")
        self.cloaks += 1
        depth = rng.randint(near, near + CLOAK_FLOORS - 1)
        if depth in self.levels:
            lvl = self.levels[depth]
            lvl.items[self._empty_floor(lvl, rng)] = self._cloak()
        else:
            self.cloak_floors.append(depth)

    def _cloak(self) -> Item:
        return seasons.dress_item(make_cloak(), self.season)

    def _key(self, room: LockedRoom) -> Item:
        return seasons.dress_item(make_key(room.color, room.depth), self.season)

    def _item(self, kind: str) -> Item:
        return seasons.dress_item(make_item(kind), self.season)

    def _gold(self, amount: int) -> Item:
        return seasons.dress_item(make_gold(amount), self.season)

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
        self._promise_cloak(depth)
        self.players[p.id] = p
        self.dirty = True
        self.broadcast(f"{p.name} enters the dungeon.", p.color)
        if self.season:
            self.tell(p, seasons.joined_message(self.season), GOLD)
        return p

    def leave(self, p: Player) -> None:
        if self.players.pop(p.id, None) is None:
            return
        p.connected, p.pending, p.hold, p.ping, p.sprinting = False, None, None, None, False
        for item in [i for i in p.pack if i.category == "amulet"]:  # or nobody could ever win
            self._take_one(p, item)
            self.levels[p.depth].items[self.levels[p.depth].free_item_spot(p.x, p.y)] = item
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
        a = msg.get("a")
        if a == "sprint":  # kept even while down, or a held Shift would be lost on revival
            p.sprinting = bool(msg.get("on"))
            return
        if not p.alive or not p.connected:
            return
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
        elif a == "enhance":
            x, y = msg.get("x"), msg.get("y")
            if type(x) is not int or type(y) is not int or not (0 <= x < MAP_W and 0 <= y < MAP_H):
                return
            p.pending = {"a": "enhance", "x": x, "y": y}
        elif a == "buy":
            if not isinstance(msg.get("id"), int) or isinstance(msg.get("id"), bool):
                return
            p.pending = {"a": "buy", "id": msg["id"]}
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
        for lvl in self.levels.values():
            if lvl.changes:
                msg = {"t": "tiles", "depth": lvl.depth, "cells": lvl.changes}
                lvl.changes = []
                self.outbox += [(p.id, msg) for p in self.players.values() if p.depth == lvl.depth]
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
                    self._fill_stamina(p, ticks)
                    for effect, text in WEAR_OFF:
                        ends = getattr(p, effect)
                        if ends and self.clock >= ends and p.alive:
                            setattr(p, effect, 0)
                            self.dirty = True
                            self._touch_down(p, text)
            self._tick_revives(ticks)
            self._tick_gas(ticks)
            self._tick_tide()

    def _tick_gas(self, ticks: int) -> None:
        for lvl in self.levels.values():
            if lvl.slime:
                lvl.slime = {c: end for c, end in lvl.slime.items() if end > self.clock}
                self.dirty = True
            if lvl.gas:
                lvl.gas = {c: end for c, end in lvl.gas.items() if end > self.clock}
                self.dirty = True
                for p in self._living_on(lvl.depth):
                    if (p.x, p.y) in lvl.gas:
                        self._breathe_gas(p, ticks)
        for p in [p for p in self.players.values() if p.alive and p.toxin_until > self.clock]:
            self._suffer_toxin(p, ticks)

    def _breathe_gas(self, p: Player, ticks: int) -> None:
        p.gas_ticks += ticks
        if p.gas_ticks < TICKS_PER_SECOND or p.god:
            return
        p.gas_ticks -= int(TICKS_PER_SECOND)
        p.hp -= GAS_DAMAGE
        self.tell(p, "You choke on the gas.", ORANGE)
        if p.hp <= 0:
            self._kill(p, None, f"Choked on toxic gas on depth {p.depth}.")

    def _suffer_toxin(self, p: Player, ticks: int) -> None:
        p.toxin_ticks += ticks
        if p.toxin_ticks < TICKS_PER_SECOND or p.god:
            return
        p.toxin_ticks -= int(TICKS_PER_SECOND)
        p.hp -= TOXIN_DAMAGE
        self.dirty = True
        if p.hp <= 0:
            self._kill(p, None, f"Poisoned by a slime on depth {p.depth}.")

    def _slimed(self, p: Player) -> None:
        """A slime's touch, or stepping in what it left behind."""
        if p.god or self._levitating(p):
            return
        if p.toxin_until <= self.clock:
            self.tell(p, "Slime clings to you. It burns, and you can hardly move.", ORANGE)
        p.toxin_until = self.clock + int(TOXIN_SECONDS * TICKS_PER_SECOND)
        p.slow_until = self.clock + int(SLOW_SECONDS * TICKS_PER_SECOND)

    def _tick_tide(self) -> None:
        """While the necromancer is awake, the dead keep coming for anyone who ran from it."""
        if not self.necro_awake or self.clock < self.tide_at:
            return
        self.tide_at = self.clock + int(TIDE_SECONDS * TICKS_PER_SECOND)
        for p in [p for p in self.players.values() if p.alive and p.chased and p.depth < LAST_FLOOR]:
            lvl = self.levels[p.depth]
            if sum(m.kind == "zombie" for m in lvl.monsters) >= TIDE_MAX:
                continue
            walk, sight = lvl.distances_to(p.x, p.y), self.fov(p)
            spots = [c for c in lvl.land_cells if c not in lvl.occupant and not sight[c] and 10 <= walk[c] <= 40]
            for spot in self.rng.sample(spots, min(TIDE_SIZE, len(spots))):
                self._raise_zombie(lvl, spot, p)

    def _raise_zombie(self, lvl: Level, spot: tuple[int, int], target: Player) -> None:
        z = seasons.dress_monster(make_monster("zombie", next(self._ids)), self.season)
        z.next_time = self.clock + TICKS_PER_TURN
        lvl.place(z, *spot)
        lvl.monsters.append(z)
        self._hunt(z, target)

    def _touch_down(self, p: Player, text: str) -> None:
        """A potion has worn off. Says so, or deals with whatever it was holding them over."""
        lvl = self.levels[p.depth]
        if self._can_be_at(p, lvl, p.x, p.y):
            self.tell(p, text, GRAY)
        elif lvl.tiles[p.x, p.y] == PIT:
            self._fall(p, lvl)
        elif lvl.tiles[p.x, p.y] == LAVA:
            self._burn(p, lvl)
        else:
            lvl.move(p, *lvl.free_near(p.x, p.y))
            self.tell(p, "You splash down and scramble ashore.", GRAY)

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

    def _fill_stamina(self, p: Player, ticks: int) -> None:
        if self.clock < p.stamina_rest:
            return
        before = int(p.stamina)
        p.stamina = min(STAMINA_MAX, p.stamina + ticks * STAMINA_MAX / (STAMINA_FILL_SECONDS * TICKS_PER_SECOND))
        if int(p.stamina) != before:
            self.dirty = True

    def _spend_stamina(self, p: Player, amount: int) -> None:
        p.stamina = max(0.0, p.stamina - amount)
        p.stamina_rest = self.clock + int(STAMINA_REST_SECONDS * TICKS_PER_SECOND)

    def _stride(self, p: Player) -> int:
        """What a step costs: less while sprinting, which also uses up stealth twice as fast."""
        cost = p.move_cost * (SLOW_FACTOR if p.slow_until > self.clock else 1)
        if not p.sprinting or p.stamina < SPRINT_STAMINA:
            return cost
        self._spend_stamina(p, SPRINT_STAMINA)
        if not self._levitating(p):
            p.stealth = max(0.0, p.stealth - STEALTH_MOVE_DRAIN)
        return int(cost * SPRINT_MOVE_COST)

    def _swing_cost(self, p: Player) -> int:
        """What an attack costs: stamina, or twice the time if there's too little of it."""
        tired = p.stamina < ATTACK_STAMINA
        self._spend_stamina(p, ATTACK_STAMINA)
        return p.attack_cost * TIRED_ATTACK if tired else p.attack_cost

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
        elif a == "buy":
            cost = self._buy(p, lvl, act["id"])
        elif a == "enhance":
            cost = self._enhance(p, lvl, act["x"], act["y"])
        if cost > 0 and p.alive:
            if p.haste_until > self.clock:
                cost //= 2
            p.next_time = self.clock + cost
            p.turns += 1
            if a in ("move", "descend", "ascend") and not self._levitating(p):
                p.stealth = max(0.0, p.stealth - STEALTH_MOVE_DRAIN)

    def _player_move(self, p: Player, lvl: Level, dx: int, dy: int) -> int:
        nx, ny = p.x + dx, p.y + dy
        if not lvl.in_bounds(nx, ny):
            return 0
        tile = lvl.tiles[nx, ny]
        if p.noclip and tile not in (STAIRS_DOWN, STAIRS_UP):
            return self._ghost_step(p, lvl, dx, dy)
        if lvl.diagonal_blocked(p.x, p.y, nx, ny):
            return 0
        if tile == STAIRS_DOWN:
            return self._take_stairs(p, +1)
        if tile == STAIRS_UP:
            return self._take_stairs(p, -1)
        other = lvl.actor_at(nx, ny)
        if other is not None:
            if isinstance(other, Merchant):
                self.outbox.append((p.id, self._shop_msg(other)))
                self.tell(p, f"The {other.name} shows you what's for sale.", GOLD)
                return 0
            if other.is_player:  # swap places with an ally, as in Brogue
                ox, oy = p.x, p.y
                if not (self._can_be_at(p, lvl, nx, ny) and self._can_be_at(other, lvl, ox, oy)):
                    return 0
                lvl.remove(p)
                lvl.remove(other)
                lvl.place(p, nx, ny)
                lvl.place(other, ox, oy)
                self.tell(other, f"{p.name} swaps places with you.", GRAY)
                self._step_onto(p, lvl)
                return self._stride(p)
            self._attack(p, other)
            return self._swing_cost(p)
        if tile == ALTAR:
            return self._offer(p, nx, ny)
        if tile == PIT and not self._levitating(p):
            self._fall(p, lvl, (nx, ny))
            return p.move_cost
        if (nx, ny) == lvl.lock:
            return self._open_lock(p, lvl)
        if not self._can_be_at(p, lvl, nx, ny):
            if tile == DEEP and not lvl.mainland[p.x, p.y]:
                return self._swim(p, lvl, nx, ny)  # stranded, or already in it
            if tile == DEEP:
                self.tell(p, "That water is too deep to wade through.", GRAY)
            elif tile == LAVA:
                self.tell(p, "That lava would burn you alive.", ORANGE)
            return 0  # bumping a wall costs no time
        lvl.move(p, nx, ny)
        self._step_onto(p, lvl)
        return self._stride(p)

    def _offer(self, p: Player, x: int, y: int) -> int:
        if p.weapon is None:
            self.tell(p, "The altar hums. It wants a weapon in your hand.", PURPLE)
        else:
            self.outbox.append((p.id, {"t": "prompt", "text": "Would you like to enhance your weapon?", "x": x, "y": y}))
        return 0

    def _enhance(self, p: Player, lvl: Level, x: int, y: int) -> int:
        """Each altar works once, and what it does is the weapon's for good, whoever holds it."""
        if lvl.tiles[x, y] != ALTAR or max(abs(p.x - x), abs(p.y - y)) > 1:
            self.tell(p, "There's no altar within reach.", GRAY)
            return 0
        if p.weapon is None:
            self.tell(p, "You're not holding a weapon.", GRAY)
            return 0
        result = enhance_weapon(p.weapon, self.rng)
        lvl.spend_altar(x, y)
        apply_gear(p)
        p.pack_dirty = True
        self.tell(p, f"Purple fire sinks into your {p.weapon.name}: {result}.", PURPLE)
        self._narrate(lvl, [(x, y)], set(), lambda v: (f"The altar's light goes out around {p.name}.", PURPLE), exclude=p)
        return TICKS_PER_TURN

    def _swim(self, p: Player, lvl: Level, x: int, y: int) -> int:
        """Water can't be crossed from the mainland, but a potion running out mustn't leave
        anyone stuck on an island for good, so from there it's a slow swim."""
        if lvl.walkable[p.x, p.y]:
            self.tell(p, "With no other way off, you swim for it.", GRAY)
        lvl.move(p, x, y)
        return p.move_cost * 2

    def _ghost_step(self, p: Player, lvl: Level, dx: int, dy: int) -> int:
        """Console: a step with no collision. A tile holds one actor at a time,
        so walking through someone takes you out the far side of them."""
        x, y = p.x + dx, p.y + dy
        while lvl.in_bounds(x, y) and (x, y) in lvl.occupant:
            x, y = x + dx, y + dy
        if not lvl.in_bounds(x, y):
            return 0
        lvl.move(p, x, y)
        self._step_onto(p, lvl)
        return self._stride(p)

    def _can_be_at(self, p: Player, lvl: Level, x: int, y: int) -> bool:
        tile = lvl.tiles[x, y]
        return bool(p.noclip or lvl.walkable[x, y] or (self._levitating(p) and lvl.hover[x, y])
                    or (tile == DEEP and p.waterwalk_until > self.clock)
                    or (tile == LAVA and p.lavawalk_until > self.clock))

    def _open_lock(self, p: Player, lvl: Level) -> int:
        room = self.locked_rooms[lvl.depth]
        key = next((i for i in p.pack if i.opens == lvl.depth), None)
        if key is None:
            self.tell(p, f"The {room.color} door is locked. Its key is {KEY_DISTANCE} floors away.", GRAY)
            return 0
        self._take_one(p, key)
        lvl.unlock()
        for q in self._living_on(lvl.depth):
            q.needs_level = True
        self.dirty = True
        self.tell(p, f"The {room.color} key turns, and the door swings open.", GOLD)
        return TICKS_PER_TURN

    def _fall(self, p: Player, lvl: Level, at: tuple[int, int] | None = None) -> None:
        """Drops a player to the floor below, near the same spot. It hurts but can't kill."""
        x, y = at or (p.x, p.y)
        self._narrate(lvl, [(p.x, p.y)], set(), lambda v: (f"{p.name} falls into the pit!", ORANGE), exclude=p)
        lvl.remove(p)
        below = self.level(p.depth + 1)
        below.place(p, *below.landing(x, y))
        if not p.god:
            p.hp = max(1, p.hp - self.rng.randint(*FALL_DAMAGE))
        p.pending, p.hold, p.needs_level = None, None, True
        self.tell(p, f"You fall into the pit and land hard on depth {p.depth}!", ORANGE)
        self._hear_merchant(p, below)
        if not self._can_be_at(p, below, p.x, p.y):
            self._burn(p, below)

    def _burn(self, p: Player, lvl: Level) -> None:
        """Lava. It's a long way from fatal only at good health."""
        self.tell(p, "You're in lava!", RED)
        if not p.god:
            p.hp -= LAVA_DAMAGE
        if p.hp <= 0:
            self._kill(p, None, f"Burned in lava on depth {p.depth}.")
        else:
            lvl.move(p, *lvl.free_near(p.x, p.y))
            self.tell(p, "You drag yourself out, badly burned.", ORANGE)

    def _hear_merchant(self, p: Player, lvl: Level) -> None:
        if lvl.merchant is not None:
            self.tell(p, f"You hear a {lvl.merchant.name} calling out somewhere on this floor.", GOLD)

    # -------------------------------------------------------------- items

    def _step_onto(self, p: Player, lvl: Level) -> None:
        """Potions and gold are collected on contact; anything else waits for the pickup key."""
        if lvl.tiles[p.x, p.y] == POND and not self._levitating(p):
            self._bathe(p, lvl)
        if (p.x, p.y) in lvl.slime:
            self._slimed(p)
        item = lvl.items.get((p.x, p.y))
        if item is None:
            return
        if item.category in AUTO_PICKUP:
            self._pick_up(p, lvl)
        else:
            self.tell(p, f"You see {self._a(item)} here. Press g to pick it up.", GRAY)

    def _bathe(self, p: Player, lvl: Level) -> None:
        """A pond heals you fully and wards you, and that's the end of the pond."""
        sparkle = {"t": "fx", "kind": "sparkle", "cells": lvl.drain_pond(p.x, p.y)}
        for v in self._living_on(p.depth):
            self.outbox.append((v.id, sparkle))
        p.hp = p.max_hp
        p.reflect_until = self.clock + int(REFLECT_SECONDS * TICKS_PER_SECOND)
        self.tell(p, "The water sparkles around you. You feel whole, and warded against magic.", TEAL)

    def _reflecting(self, p: Player) -> bool:
        return p.reflect_until > self.clock or (p.armor is not None and p.armor.reflect)

    def _pick_up(self, p: Player, lvl: Level) -> bool:
        item = lvl.items.get((p.x, p.y))
        if item is None:
            return False
        if item.category == "gold":
            p.gold += item.count
        elif not self._stash(p, item):
            self.tell(p, f"Your pack is full. {item.label.capitalize()} lies here.", GRAY)
            return False
        del lvl.items[(p.x, p.y)]
        if item.category == "amulet":
            self.broadcast(f"{p.name} has the Amulet! Get it to the stairs on floor 1!", GOLD)
        p.pack_dirty = True
        self.tell(p, f"You pick up {self._a(item)}.", GOLD)
        self._narrate(lvl, [(p.x, p.y)], set(), lambda v: (f"{p.name} picks up {self._a(item)}.", GRAY), exclude=p)
        return True

    @staticmethod
    def _stash(p: Player, item: Item) -> bool:
        """Puts an item in the pack. False if there's no room."""
        stack = next((i for i in p.pack if i.stacks and i.kind == item.kind), None)
        if stack is not None:
            stack.count += item.count
        elif len(p.pack) < PACK_SIZE:
            p.pack.append(item)
        else:
            return False
        return True

    def _shop_msg(self, m: Merchant) -> dict:
        stock = [{"id": i, "name": item.label, "g": item.glyph, "c": list(item.color), "info": item.info,
                  "price": item.price} for i, item in m.stock.items()]
        return {"t": "shop", "name": m.name, "x": m.x, "y": m.y, "stock": stock}

    def _buy(self, p: Player, lvl: Level, stock_id: int) -> int:
        m = lvl.merchant
        if m is None or cheb(p, m) > 1:
            self.tell(p, "There's nobody here to buy from.", GRAY)
            return 0
        item = m.stock.get(stock_id)
        if item is None:
            self.tell(p, "That's already been sold.", GRAY)
            return 0
        if p.gold < item.price:
            self.tell(p, f"You can't afford that. It's {item.price} and you have {p.gold}.", GRAY)
            return 0
        if not self._stash(p, item):
            self.tell(p, "Your pack is full.", GRAY)
            return 0
        del m.stock[stock_id]
        p.gold -= item.price
        p.pack_dirty = True
        self.tell(p, f"You buy {self._a(item)} for {item.price}.", GOLD)
        for q in self._living_on(p.depth):  # everyone at the shop sees it sell out
            if cheb(q, m) <= 1:
                self.outbox.append((q.id, self._shop_msg(m)))
        return TICKS_PER_TURN

    def _levitating(self, p: Player) -> bool:
        return p.levitate_until > self.clock

    @staticmethod
    def _a(item: Item) -> str:
        return item.label if item.category == "gold" or item.count > 1 else _article(item.label)

    def _use(self, p: Player, slot: int) -> int:
        if slot >= len(p.pack):
            return 0
        item = p.pack[slot]
        if item.category == "key":
            self.tell(p, f"Walk into the {item.name.replace(' key', '')} locked door to use it.", GRAY)
            return 0
        if item.category == "wand":
            return self._zap(p, item)
        if item.category == "ranged":
            return self._shoot(p, item)
        if item.category == "ammo":
            self.tell(p, "Use a bow to fire these.", GRAY)
            return 0
        if item.category == "amulet":
            self.tell(p, "It's your way out. Carry it up the stairs on floor 1.", GRAY)
            return 0
        if item.category == "weapon":
            p.weapon = None if p.weapon is item else item
        elif item.category == "armor":
            p.armor = None if p.armor is item else item
        elif item.category == "cloak":
            p.cloak = None if p.cloak is item else item
        elif item.heal and p.hp >= p.max_hp:
            self.tell(p, "You are already at full health.", GRAY)
            return 0
        else:
            p.hp = min(p.max_hp, p.hp + item.heal)
            if item.haste:
                p.haste_until = self.clock + int(item.haste * TICKS_PER_SECOND)
            if item.levitate:
                p.levitate_until = self.clock + int(item.levitate * TICKS_PER_SECOND)
            if item.teleport:
                self._teleport_floor(p)
            if item.waterwalk:
                p.waterwalk_until = self.clock + int(item.waterwalk * TICKS_PER_SECOND)
            if item.lavawalk:
                p.lavawalk_until = self.clock + int(item.lavawalk * TICKS_PER_SECOND)
            self.tell(p, "You feel better." if item.heal else "You rise off the ground!" if item.levitate
                      else f"The world lurches, and you're on floor {p.depth}!" if item.teleport
                      else "Your feet feel strangely light." if item.waterwalk
                      else "Your feet stop feeling the heat." if item.lavawalk
                      else "Everything around you slows down.", GOLD)
            self._take_one(p, item)
            return TICKS_PER_TURN
        apply_gear(p)
        p.pack_dirty = True
        equipped = item in (p.weapon, p.armor, p.cloak)
        self.tell(p, f"You {'equip' if equipped else 'remove'} the {item.name}.", WHITE)
        return TICKS_PER_TURN

    def _teleport_floor(self, p: Player) -> None:
        """The potion: a random spot on a random other floor, from the first to the last."""
        old = self.levels[p.depth]
        fx = {"t": "fx", "kind": "blink", "cells": [(p.x, p.y)]}
        for v in self._living_on(p.depth):
            self.outbox.append((v.id, fx))
        if old.depth == LAST_FLOOR and self.necro_awake:
            p.chased = True
        depth = self.rng.choice([d for d in range(1, LAST_FLOOR + 1) if d != p.depth])
        old.remove(p)
        lvl = self.level(depth)
        lvl.place(p, *self._empty_floor(lvl, self.rng))
        p.hold, p.needs_level = None, True
        self._step_onto(p, lvl)
        self._hear_merchant(p, lvl)

    def teleport(self, p: Player) -> None:
        """The console: a random open spot on this floor, somewhere well away from here."""
        lvl = self.levels[p.depth]
        walk = lvl.distances_to(p.x, p.y)
        spots = [c for c in lvl.land_cells if c not in lvl.occupant]
        far = [c for c in spots if TELEPORT_STEPS * algo.CARDINAL_COST <= walk[c] < algo.INF]
        spot = self.rng.choice(far or spots)
        fx = {"t": "fx", "kind": "blink", "cells": [(p.x, p.y), spot]}
        for v in self._living_on(p.depth):
            self.outbox.append((v.id, fx))
        p.hold = None
        lvl.move(p, *spot)
        self._step_onto(p, lvl)

    def warp(self, p: Player, depth: int) -> None:
        """Console: straight to the top of any floor."""
        self.levels[p.depth].remove(p)
        lvl = self.level(depth)
        lvl.place(p, *lvl.free_near(*lvl.up_front))
        p.pending, p.hold, p.needs_level = None, None, True

    def _target(self, p: Player, lvl: Level, reach: int) -> Monster | None:
        """What ranged weapons aim at: whatever is fighting first, then the strongest or the
        weakest, as this player has chosen, and the nearest of any that are equal."""
        sight = self.fov(p)
        near = [m for m in lvl.monsters if sight[m.x, m.y] and cheb(p, m) <= reach]
        fighting = [m for m in near if m.state == "hunting"] or near
        if not fighting:
            return None
        order = 1 if p.aim == "Weakest" else -1
        return min(fighting, key=lambda m: (order * danger(m.kind), cheb(p, m), m.id))

    def _shoot(self, p: Player, weapon: Item) -> int:
        """A bow or boomerang. A sneak shot works like a sneak attack."""
        lvl = self.levels[p.depth]
        ammo = next((i for i in p.pack if i.category == "ammo"), None)
        if weapon.fires and ammo is None:
            self.tell(p, f"You have no {weapon.fires}s.", GRAY)
            return 0
        m = self._target(p, lvl, weapon.reach)
        if m is None:
            self.tell(p, "There's nothing in range to aim at.", GRAY)
            return 0
        if weapon.fires:
            self._take_one(p, ammo)
        shot = {"t": "fx", "kind": weapon.kind, "cells": line_between((p.x, p.y), (m.x, m.y))}
        for v in self._living_on(p.depth):
            self.outbox.append((v.id, shot))
        p.stealth = 0.0
        self._note_fight(p, m)
        sneak = m.state != "hunting"
        where = [(p.x, p.y), (m.x, m.y)]
        if sneak or self.rng.random() * 100 < p.accuracy * DEFENSE_FACTOR ** m.defense:
            m.hp -= self.rng.randint(*weapon.damage) * (SNEAK_DAMAGE if sneak else 1)
            self._narrate(lvl, where, {p}, lambda v: (
                f"{self._n(p, v, True)} {self._verb(p, v, ('hits', 'hit'))} {self._n(m, v)}.", WHITE))
        else:
            self._narrate(lvl, where, {p}, lambda v: (
                f"{self._n(p, v, True)} {self._verb(p, v, ('misses', 'miss'))} {self._n(m, v)}.", GRAY))
        if m.hp <= 0:
            self._kill(m, p)
        else:
            self._hunt(m, p)
        return TICKS_PER_TURN

    def _zap(self, p: Player, wand: Item) -> int:
        """Fires at a monster in sight. After its last use the wand breaks."""
        lvl = self.levels[p.depth]
        m = self._target(p, lvl, WAND_RANGE)
        if m is None:
            self.tell(p, "There's nothing in range to aim at.", GRAY)
            return 0
        bolt = {"t": "fx", "kind": "frost" if wand.freeze else "fire", "cells": line_between((p.x, p.y), (m.x, m.y))}
        for v in self._living_on(p.depth):
            self.outbox.append((v.id, bolt))
        p.stealth = 0.0
        self._note_fight(p, m)
        if wand.freeze:  # it never knew what hit it, so nothing wakes
            m.frozen_until = self.clock + int(wand.freeze * TICKS_PER_SECOND)
            self._narrate(lvl, [(m.x, m.y)], {p}, lambda v: (
                f"{self._n(p, v, True)} {self._verb(p, v, ('freezes', 'freeze'))} {self._n(m, v)} solid.", WHITE))
        else:
            m.hp -= self.rng.randint(*WAND_DAMAGE)
            m.burning, m.burned_by = WAND_BURN_TURNS, p
            self._narrate(lvl, [(m.x, m.y)], {p}, lambda v: (
                f"{self._n(p, v, True)} {self._verb(p, v, ('burns', 'burn'))} {self._n(m, v)}.", ORANGE))
            if m.hp <= 0:
                self._kill(m, p)
            else:
                self._hunt(m, p)
        wand.charges -= 1
        p.pack_dirty = True
        if wand.charges <= 0:
            self._take_one(p, wand)
            self.tell(p, f"The {wand.name} crumbles to ash.", ORANGE)
        return TICKS_PER_TURN

    def _take_one(self, p: Player, item: Item) -> Item:
        """Removes one of `item` from the pack and returns it."""
        p.pack_dirty = True
        if item.count > 1:
            item.count -= 1
            return self._item(item.kind)
        p.pack.remove(item)
        if item is p.weapon:
            p.weapon = None
        if item is p.armor:
            p.armor = None
        if item is p.cloak:
            p.cloak = None
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
        item = self._gold(amount)
        lvl.items[lvl.free_item_spot(p.x, p.y)] = item
        self.tell(p, f"You drop {item.label}.", WHITE)
        self._narrate(lvl, [(p.x, p.y)], set(), lambda v: (f"{p.name} drops {item.label}.", GRAY), exclude=p)
        return TICKS_PER_TURN

    def _scatter_belongings(self, p: Player, lvl: Level) -> None:
        """A fallen player's gear lands around them for the party to collect."""
        loot = p.pack + ([self._gold(p.gold)] if p.gold else [])
        for item in loot:
            lvl.items[lvl.free_item_spot(p.x, p.y)] = item
        p.pack, p.gold, p.weapon, p.armor, p.cloak, p.pack_dirty = [], 0, None, None, None, True
        apply_gear(p)

    def _take_stairs(self, p: Player, step: int) -> int:
        new_depth = p.depth + step
        if new_depth < 1:
            if any(i.category == "amulet" for i in p.pack):
                self._win(p)
            else:
                self.tell(p, "The way out is sealed. Only the Amulet from the last floor opens it.", GRAY)
            return 0
        old = self.levels[p.depth]
        if old.depth == LAST_FLOOR and self.necro_awake and step < 0 and not p.chased:
            p.chased = True
            self.tell(p, "Behind you, the dead begin to rise...", RED)
        verb = "descends" if step > 0 else "climbs"
        self._narrate(old, [(p.x, p.y)], set(), lambda v: (f"{p.name} {verb} the stairs.", GRAY), exclude=p)
        old.remove(p)
        lvl = self.level(new_depth)
        lvl.place(p, *lvl.free_near(*(lvl.up_front if step > 0 else lvl.down_front)))
        p.needs_level = True
        self.tell(p, f"You {'descend' if step > 0 else 'ascend'} to depth {new_depth}.", WHITE)
        self._hear_merchant(p, lvl)
        return p.move_cost

    def _win(self, p: Player) -> None:
        """The whole party wins, and a new dungeon starts once they've seen the scores."""
        if self.victory:
            return
        self.victory = p.name
        self.reset_at = time.monotonic() + VICTORY_SECONDS
        self.broadcast(f"{p.name} carries the Amulet out of the dungeon. The party wins!", GOLD)
        for q in sorted(self.players.values(), key=self.score_of, reverse=True):
            self.broadcast(f"{q.name}: {self.score_of(q)} points, {q.kills} kills", GOLD)

    def _regen(self, p: Player, cost: int) -> None:
        if p.hp >= p.max_hp:
            p.regen_acc = 0
            return
        if p.toxin_until > self.clock:  # poison stops you healing
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
        hidden = att.is_player and att.stealth >= CRIT_STEALTH  # as they struck, not after
        if att.is_player:
            att.stealth = 0.0  # fighting is loud
            for v in self._living_on(att.depth):
                self.outbox.append((v.id, {"t": "fx", "kind": "hit", "cells": [(dfn.x, dfn.y)]}))
            self._note_fight(att, dfn)
        elif dfn.is_player:
            self._note_fight(dfn, att)
            if self._levitating(dfn) or dfn.god:
                self._narrate(lvl, [(att.x, att.y), (dfn.x, dfn.y)], {dfn}, lambda v: (
                    f"{self._n(att, v, True)} can't reach {self._n(dfn, v)}.", GRAY))
                return
        sneak = isinstance(dfn, Monster) and dfn.state != "hunting"
        crit = sneak and hidden and dfn.state == "sleeping"
        prob = 100.0 if sneak else att.accuracy * DEFENSE_FACTOR ** dfn.defense
        where = [(att.x, att.y), (dfn.x, dfn.y)]
        if self.rng.random() * 100 < prob:
            dmg = self.rng.randint(*att.damage) * (CRIT_DAMAGE if crit else SNEAK_DAMAGE if sneak else 1)
            dfn.hp -= dmg

            def hit(v):
                tail = " with a critical hit!" if crit else " by surprise!" if sneak else "."
                color = RED if v is dfn else (WHITE if v is att else GRAY)
                return f"{self._n(att, v, True)} {self._verb(att, v, att.verbs)} {self._n(dfn, v)}{tail}", color
            self._narrate(lvl, where, {att, dfn}, hit)
            if att.is_player and att.weapon is not None:
                self._weapon_magic(att, dfn, dmg)
            if isinstance(att, Monster) and att.kind == "slime" and dfn.hp > 0:
                self._slimed(dfn)
        else:
            self._narrate(lvl, where, {att, dfn}, lambda v: (
                f"{self._n(att, v, True)} {self._verb(att, v, ('misses', 'miss'))} {self._n(dfn, v)}.", GRAY))
        if isinstance(dfn, Monster) and dfn.hp > 0:
            self._hunt(dfn, att)
        if dfn.hp <= 0:
            self._kill(dfn, att)

    def _weapon_magic(self, p: Player, m: Monster, damage: int) -> None:
        spells = p.weapon.magic
        if "fire" in spells:
            m.burning, m.burned_by = WAND_BURN_TURNS, p
        if "frost" in spells and self.rng.random() < WEAPON_FREEZE_CHANCE:
            m.frozen_until = self.clock + int(WEAPON_FREEZE_SECONDS * TICKS_PER_SECOND)
            self.tell(p, f"The {m.name} freezes solid!", WHITE)
        if "drain" in spells:
            p.hp = min(p.max_hp, p.hp + max(1, damage // WEAPON_DRAIN))

    @staticmethod
    def _note_fight(p: Player, m: Monster) -> None:
        if m.kind and (not p.hardest or danger(m.kind) > danger(p.hardest)):
            p.hardest = m.kind

    def _kill(self, victim, killer, cause: str = "") -> None:
        lvl = self.levels[victim.depth]
        where = [(victim.x, victim.y)]
        if isinstance(victim, Monster):
            if victim is self.necromancer:
                self.necromancer, self.necro_awake = None, False
                for p in self.players.values():
                    p.chased = False
                self.broadcast(f"The {victim.name} is destroyed, and the dead lie still!", GOLD)
            self._narrate(lvl, where, {killer, victim}, lambda v: (
                f"{self._n(killer, v, True)} {self._verb(killer, v, ('kills', 'kill'))} {self._n(victim, v)}.",
                WHITE if v is killer else GRAY))
            lvl.remove(victim)
            lvl.monsters.remove(victim)
            if victim.kind == "cult_leader":
                lvl.items[lvl.free_item_spot(victim.x, victim.y)] = seasons.dress_item(make_wand(), self.season)
                self._narrate(lvl, where, {killer}, lambda v: (f"The {victim.name} drops a wand!", GOLD))
            if killer is not None and killer.is_player:
                killer.kills += 1
                killer.kill_tally[victim.name] = killer.kill_tally.get(victim.name, 0) + 1
            return
        revivable = self.mode == "Revive"
        self._narrate(lvl, where, {victim}, lambda v: (
            ("You are down..." if revivable else "You die...") if v is victim
            else f"{victim.name} {'is down' if revivable else 'dies'}!", RED))
        victim.alive, victim.hp, victim.pending, victim.hold = False, 0, None, None
        victim.levitate_until = victim.waterwalk_until = victim.lavawalk_until = victim.reflect_until = 0
        victim.toxin_until = victim.slow_until = 0
        if not lvl.mainland[victim.x, victim.y]:  # over water or on an island: land where the party can reach
            lvl.move(victim, *lvl.free_near(victim.x, victim.y))
        victim.final_gold = victim.gold
        victim.death = cause or (f"Killed by {_article(killer.name)} on depth {victim.depth}." if killer else "Died.")
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
        """Gold, and winning, are what score. Every move divides them down."""
        points = self.carried_gold(p) * SCORE_PER_GOLD + (WIN_POINTS if self.victory else 0)
        return points * SCORE_STEPS // (p.turns + SCORE_STEPS)

    def _check_all_dead(self) -> None:
        if self.players and not any(p.alive for p in self.players.values()) and self.reset_at is None:
            self.reset_at = time.monotonic() + RESET_DELAY
            self.broadcast("The whole party has fallen. A new dungeon takes shape...", RED)
            for p in sorted(self.players.values(), key=self.score_of, reverse=True):
                self.broadcast(f"{p.name}: {self.score_of(p)} points, {p.kills} kills", GOLD)

    def reset_run(self) -> None:
        self.seed = random.randrange(1, 2 ** 31)
        self.rng = random.Random(self.seed * 7919 + 1)
        self.locked_rooms = plan_locked_rooms(self.seed)
        self.levels, self.offline = {}, {}
        self.necromancer, self.necro_awake, self.tide_at, self.victory = None, False, 0, ""
        self.cloaks, self.cloak_floors = 0, []
        for _ in self.players:
            self._promise_cloak(1)
        self.season = self.season_fn()
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
        if m is self.necromancer and not self.necro_awake:
            self.necro_awake = True
            self.broadcast(f"The {m.name} has woken!", RED)
        if m.kind in PACK_KINDS:  # one sees you and they all come
            head = m.leader or m
            for other in self.levels[m.depth].monsters:
                if (other is head or other.leader is head) and other.state != "hunting":
                    other.state, other.target_id, other.last_seen = "hunting", target.id, (target.x, target.y)

    def _lit(self, p: Player) -> float:
        return float(self.levels[p.depth].light[p.x, p.y])

    def _notice_range(self, p: Player, base: int) -> float:
        """How far away a monster can notice this player: stealth shrinks it, torchlight widens it."""
        hush = 1 - p.cloak.hush if p.cloak else 1  # a cloak halves it
        return base * hush * (1 - (1 - STEALTH_RANGE_MIN) * p.stealth / STEALTH_MAX) * (1 + TORCH_NOTICE * self._lit(p))

    def _monster_act(self, m: Monster) -> None:
        if m.frozen_until > self.clock:
            m.next_time = m.frozen_until
            return
        if m.burning:
            m.burning -= 1
            m.hp -= self.rng.randint(*WAND_BURN)
            if m.hp <= 0:
                self._kill(m, m.burned_by)
                return
        cost = max(1, self._monster_turn(m, self.levels[m.depth]))
        m.next_time = self.clock + int(cost * self.monster_time)

    def _release_gas(self, m: Monster, lvl: Level) -> int:
        """Mushrooms stay put. They wait for someone to come close, however quietly."""
        close = [p for p in self._living_on(m.depth) if cheb(m, p) <= GAS_TRIGGER and self.fov(p)[m.x, m.y]]
        if close and self.clock >= m.ready_at:
            m.ready_at = self.clock + int(GAS_COOLDOWN * TICKS_PER_SECOND)
            room = lvl.room_around(m.x, m.y)
            furthest = max(room.values())
            for cell, away in room.items():  # it thins out from the edges of the room inward
                share = 1 - 0.5 * away / furthest - 0.15 * self.rng.random()
                lvl.gas[cell] = self.clock + int(share * GAS_SECONDS * TICKS_PER_SECOND)
            self._narrate(lvl, [(m.x, m.y)], set(), lambda v: (f"The {m.name} bursts into a cloud of toxic gas!", ORANGE))
        return TICKS_PER_TURN

    def _step_away(self, m: Monster, lvl: Level, target: Player) -> int:
        """One step further from someone on foot, if there's anywhere to go."""
        walk = lvl.distances_to(target.x, target.y)
        best, best_d = None, walk[m.x, m.y]
        dirs = DIRS8[:]
        self.rng.shuffle(dirs)
        for dx, dy in dirs:
            n = (m.x + dx, m.y + dy)
            if (lvl.in_bounds(*n) and lvl.walkable[n] and n not in lvl.occupant and best_d < walk[n] < algo.INF
                    and not lvl.diagonal_blocked(m.x, m.y, *n)):
                best, best_d = n, walk[n]
        if best is None:
            return 0
        lvl.move(m, *best)
        return m.move_cost

    def _archer(self, m: Monster, lvl: Level, target: Player) -> int:
        """Holds off at bowshot: backs away from anyone close, and only shoots from the
        right distance, or when it's cornered."""
        away = cheb(m, target)
        if away < ARCHER_RANGE[0]:
            cost = self._step_away(m, lvl, target)
            if cost:
                return cost
        elif away > ARCHER_RANGE[1]:
            return self._step_toward(m, lvl, target.x, target.y) or TICKS_PER_TURN
        if self.clock < m.ready_at:
            return TICKS_PER_TURN
        m.ready_at = self.clock + int(ARCHER_RELOAD * TICKS_PER_SECOND)
        arrow = {"t": "fx", "kind": "bow", "cells": line_between((m.x, m.y), (target.x, target.y))}
        for v in self._living_on(m.depth):
            self.outbox.append((v.id, arrow))
        self._note_fight(target, m)
        where = [(m.x, m.y), (target.x, target.y)]
        if self.rng.random() * 100 >= m.accuracy * DEFENSE_FACTOR ** target.defense:
            self._narrate(lvl, where, {target}, lambda v: (f"The {m.name}'s arrow misses {self._n(target, v)}.", GRAY))
            return m.attack_cost
        self._narrate(lvl, where, {target}, lambda v: (f"The {m.name}'s arrow hits {self._n(target, v)}!", RED))
        if not target.god:
            target.hp -= self.rng.randint(*m.damage)
            if target.hp <= 0:
                self._kill(target, m)
        return m.attack_cost

    def _breathe(self, m: Monster, lvl: Level, target: Player) -> None:
        """Fire along a line. Magic like this comes straight back off anyone warded."""
        m.ready_at = self.clock + int(BREATH_SECONDS * TICKS_PER_SECOND)
        cells = line_between((m.x, m.y), (target.x, target.y))
        fire = {"t": "fx", "kind": "fire", "cells": cells}
        for v in self._living_on(m.depth):
            self.outbox.append((v.id, fire))
        self._narrate(lvl, [(m.x, m.y)], {target}, lambda v: (f"The {m.name} breathes fire!", ORANGE))
        for p in [p for p in self._living_on(m.depth) if (p.x, p.y) in cells]:
            damage = self.rng.randint(*BREATH_DAMAGE)
            if self._reflecting(p):
                m.hp -= damage
                self._narrate(lvl, [(p.x, p.y)], {p}, lambda v: (f"The flames rebound off {self._n(p, v)}!", TEAL))
                if m.hp <= 0:
                    self._kill(m, p)
                    return
            elif not p.god:
                p.hp -= damage
                self.tell(p, "The flames wash over you!", RED)
                if p.hp <= 0:
                    self._kill(p, m)

    def _summon(self, m: Monster, lvl: Level, target: Player) -> None:
        m.ready_at = self.clock + int(SUMMON_SECONDS * TICKS_PER_SECOND)
        room = TIDE_MAX - sum(z.kind == "zombie" for z in lvl.monsters)
        for _ in range(min(room, self.rng.randint(*SUMMON_SIZE))):
            self._raise_zombie(lvl, lvl.free_near(m.x, m.y), target)
        self._narrate(lvl, [(m.x, m.y)], set(), lambda v: (f"The {m.name} raises the dead!", RED))

    def _monster_turn(self, m: Monster, lvl: Level) -> int:
        if m.kind == "mushroom":
            return self._release_gas(m, lvl)
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
            if m.kind == "necromancer" and self.clock >= m.ready_at:
                self._summon(m, lvl, t)
                return m.attack_cost
            if m.kind == "skeleton_archer":
                return self._archer(m, lvl, t)
            if m.kind == "dragon" and self.clock >= m.ready_at and 2 <= cheb(m, t) <= BREATH_RANGE:
                self._breathe(m, lvl, t)
                return m.attack_cost
            if cheb(m, t) == 1 and not lvl.diagonal_blocked(m.x, m.y, t.x, t.y):
                self._attack(m, t)
                return m.attack_cost * MONSTER_SWING
            return self._step_toward(m, lvl, t.x, t.y) or TICKS_PER_TURN

        if m.state == "hunting":  # lost sight: go to where the prey was last seen
            if m.last_seen and (m.x, m.y) != m.last_seen:
                cost = self._step_toward(m, lvl, *m.last_seen)
                if cost:
                    return cost
            m.state, m.target_id, m.last_seen = "wandering", None, None

        if m.post is not None and m.leader is None:  # keep watch over the altar
            return (cheb(m, Point(*m.post)) > 2 and self._step_toward(m, lvl, *m.post)) or TICKS_PER_TURN
        if m.leader is not None and m.leader.hp > 0:  # stay with the group
            return (cheb(m, m.leader) > 2 and self._step_toward(m, lvl, m.leader.x, m.leader.y)) or TICKS_PER_TURN
        if m.wander_target is None or (m.x, m.y) == m.wander_target:
            m.wander_target = lvl.random_floor(self.rng)
        cost = self._step_toward(m, lvl, *m.wander_target)
        if not cost:
            m.wander_target = None
        return cost or TICKS_PER_TURN

    def _step_toward(self, m: Monster, lvl: Level, tx: int, ty: int) -> int:
        dist = lvl.distances_to(tx, ty)
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
        if m.kind == "slime":
            lvl.slime[(m.x, m.y)] = self.clock + int(SLIME_TRAIL * TICKS_PER_SECOND)
            self.dirty = True
        lvl.move(m, *best)
        return m.move_cost

    # ------------------------------------------------------------- views

    def level_msg(self, depth: int) -> dict:
        lvl = self.level(depth)
        return {"t": "level", "depth": depth, "run": self.run, "w": MAP_W, "h": MAP_H,
                "tiles": protocol.pack_u8(lvl.tiles),
                "lights": [protocol.pack_u8(m * 255) for m in lvl.torch_light]}

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

    def _windup(self, m, lvl: Level) -> dict:
        """For a monster about to land a melee hit: seconds until it can, and how long its
        swing takes. The client turns these into a warning, so it stays smooth between states."""
        if (not isinstance(m, Monster) or m.state != "hunting" or not m.damage[1] or m.frozen_until > self.clock
                or m.kind == "skeleton_archer"  # it shoots rather than swings
                or not any(cheb(m, p) <= 1 and not lvl.diagonal_blocked(m.x, m.y, p.x, p.y)
                           for p in self._living_on(m.depth))):
            return {}
        return {"strike": max(0.0, (m.next_time - self.clock) / TICKS_PER_SECOND),
                "swing": m.attack_cost * MONSTER_SWING * self.monster_time / TICKS_PER_SECOND}

    def _hardest_name(self, p: Player) -> str:
        if not p.hardest:
            return ""
        return seasons.monster_name(p.hardest, self.season, MONSTERS[p.hardest]["name"])

    def pack_msg(self, p: Player) -> dict:
        pack = [{"name": i.label, "g": i.glyph, "c": list(i.color), "info": i.info,
                 "eq": i in (p.weapon, p.armor, p.cloak)} for i in p.pack]
        return {"t": "pack", "pack": pack, "gold": p.gold, "defense": p.defense,
                "dmg": f"{p.damage[0]}-{p.damage[1]}", "stealth_cap": p.stealth_cap}

    def state_for(self, p: Player) -> dict:
        lvl = self.level(p.depth)
        gas_span = int(GAS_SECONDS * TICKS_PER_SECOND)
        vis = self.fov(p) if p.alive or p.downed else np.zeros((MAP_W, MAP_H), dtype=bool)
        ents = []
        for a in lvl.occupant.values():
            seen = bool(vis[a.x, a.y])
            if seen or a.is_player or p.reveal:  # allies on your depth are always shown
                ents.append({"id": a.id, "g": a.glyph, "c": list(a.color), "x": a.x, "y": a.y,
                             "name": a.name, "hp": a.hp, "mhp": a.max_hp, "p": a.is_player,
                             "seen": seen or p.reveal, "hl": p.reveal and not a.is_player, "st": "merchant" if isinstance(a, Merchant) else getattr(a, "state", ""),
                             "kind": getattr(a, "kind", ""), "lev": a.is_player and self._levitating(a),
                             "burn": getattr(a, "burning", 0) > 0,
                             "frozen": getattr(a, "frozen_until", 0) > self.clock,
                             "ward": a.is_player and a.reflect_until > self.clock,
                             "aura": a.is_player and a.armor is not None and a.armor.reflect,
                             "wet": a.is_player and a.waterwalk_until > self.clock, **self._windup(a, lvl)})
        for a in lvl.downed:
            ents.append({"id": a.id, "g": BONES_GLYPH, "c": list(BONE), "x": a.x, "y": a.y, "name": a.name,
                         "hp": 0, "mhp": a.max_hp, "p": True, "seen": bool(vis[a.x, a.y]), "st": "down"})
        items = [{"x": x, "y": y, "g": i.glyph, "c": list(i.color), "name": i.label, "info": i.info,
                  "auto": i.category in AUTO_PICKUP, "hl": p.reveal}
                 for (x, y), i in lvl.items.items() if vis[x, y] or p.reveal]
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
                "levitate": self._levitating(p), "victory": self.victory, "slowed": p.slow_until > self.clock,
                "toxin": p.toxin_until > self.clock, "slime": [c for c in lvl.slime if vis[c]], "bright": p.bright, "reveal": p.reveal,
                "gas": [[*c, max(1, 9 * (end - self.clock) // gas_span)] for c, end in lvl.gas.items() if vis[c]],
                "waterwalk": p.waterwalk_until > self.clock,
                "lavawalk": p.lavawalk_until > self.clock, "stamina": int(p.stamina), "lit": self._lit(p) > 0,
                "detect": round(self._notice_range(p, NOTICE_RANGE_AWAKE)),
                "status": status, "turns": p.turns, "kills": p.kills, "death": p.death,
                "score": self.score_of(p), "score_gold": self.carried_gold(p), "tally": p.kill_tally,
                "hardest": self._hardest_name(p), "season": self.season}
