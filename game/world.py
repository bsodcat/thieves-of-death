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
import math
import random
import time
from collections import deque
from dataclasses import dataclass

import numpy as np

from . import algo, mapgen, protocol, seasons
from .constants import (OGRE_LATE_SHARE, MUSHROOM_MOST, MUSHROOM_SHARE, GHOST_DISTANCE, GHOST_FLOORS, UNDEAD_BONUS, ARCHER_RANGE, ARCHER_RELOAD, OGRE_PEAK, OGRE_PEAK_WEIGHT, SLIME_COUNT, SLIME_FLOORS, SLIME_TRAIL,
                        SLOW_FACTOR, SLOW_SECONDS, TOXIN_DAMAGE, TOXIN_SECONDS, ARROW_PILE, ATRIUM_FLOOR, ATTACK_STAMINA, BONES_GLYPH, BREATH_DAMAGE, BREATH_RANGE, BREATH_SECONDS,
                        CLOAK_FLOORS, CRIT_DAMAGE, CRIT_STEALTH, CULT_CHANCE, CULT_FIRST,
                        DRAGON_FLOOR, HOARD_GOLD, HOARD_PILES, POTION_ROOM, TOWER_FIRST, TOWER_MONSTERS, GAS_COOLDOWN, GAS_DAMAGE, GAS_REACH, GAS_SECONDS, GAS_TRIGGER, LAST_FLOOR,
                        REFLECT_SECONDS, SCORE_SCALE, BOOMERANG_TILE_SECONDS, BOOMERANG_WAIT, FISHER_FLOORS, FOOD_SECONDS, FOOD_HEAL,
                        FOOD_ROOM_MOST, FIRE_SECONDS, GRASS_FIRE_SECONDS, FIRE_SPREAD_SECONDS, FIRE_SPREAD_CHANCE,
                        FIRE_DAMAGE, FLEE_HEALTH, BOMB_SECONDS, BOMB_RADIUS, BOMB_DAMAGE, HIDDEN_ROOM_CHANCE,
                        FAIRY_BOOST, SKELETON_FLOORS, SKELETON_EVERY, SKELETON_GROUP, SKELETON_MOST, MAGE_FLOAT,
                        MAGE_CYCLE, MAGE_BOLT, MAGE_RANGE, LIGHTNING_DAMAGE, STAFF_RANGE, KOBOLD_RAT_CHANCE,
                        KOBOLD_ALONE, KOBOLD_ROCK_CHANCE, KOBOLD_ROCK_RANGE, ROCK_DAMAGE, KOBOLD_LEADER_FLOORS,
                        KOBOLD_LEADER_CHANCE, KOBOLD_SCOUT_FLOORS, KOBOLD_SCOUT_CHANCE, KOBOLD_SCOUT_MOST,
                        SCOUT_RELOAD, SCOUT_RANGE, FIREBALL_DAMAGE, LEADER_RANGE, LEADER_VOLLEY, LEADER_REST,
                        LEADER_FIRE_DAMAGE, SPIDER_FLOORS, SPIDER_CHANCE, SPIDER_BROOD, WEB_SHARE, WEB_SPIT_RANGE,
                        WEB_SPIT_REACH, WEB_SPIT_SECONDS, WEB_FACTOR, WEB_SECONDS, LEAP_RANGE, LEAP_SECONDS,
                        LEAP_RETREAT, VENOM_PER_BITE, VENOM_MOST, VENOM_DAMAGE, VENOM_EVERY,
                        SUMMON_SECONDS, SUMMON_SIZE, TIDE_MAX, TIDE_SECONDS, TIDE_SIZE, VICTORY_SECONDS,
                        MONSTER_SWING, WEAPON_DRAIN, WEAPON_FREEZE_CHANCE, WEAPON_FREEZE_SECONDS, WOLF_CHANCE, WOLF_FIRST, WOLF_SIZE,
                        CULT_SIZE, DEEPEST_TABLE, DEFENSE_FACTOR, FALL_DAMAGE, GOLD_DROP, LAVA_DAMAGE, SNEAK_DAMAGE,
                        WAND_BURN, WAND_BURN_TURNS, WAND_DAMAGE, WAND_RANGE,
                        KEY_DISTANCE, SPRINT_MOVE_COST, SPRINT_STAMINA, STAMINA_FILL_SECONDS, STAMINA_MAX,
                        STAMINA_REST_SECONDS, TELEPORT_STEPS, TIRED_ATTACK, TORCH_NOTICE, TORCH_RADIUS,
                        LEVITATION_STOCK_CHANCE, LOCKED_ROOM_CHANCE, LOCKED_ROOM_FLOORS, MAP_H, MAP_W,
                        MERCHANT_CHANCE, MERCHANT_EVERY, MERCHANT_STOCK, NOTICE_RANGE_AWAKE,
                        NOTICE_RANGE_SLEEPING, PACK_SIZE, REGEN_TURNS, RESET_DELAY, REVIVE_HEALTH,
                        DEFAULT_DIFFICULTY, DIFFICULTIES, STEALTH_FILL_SECONDS,
                        STEALTH_MAX, STEALTH_MOVE_DRAIN, STEALTH_RANGE_MIN, TICKS_PER_SECOND,
                        TICKS_PER_TURN)
from .constants import SPEAR_REST, SPEAR_REST_DISTANCE, SPEAR_THRUSTS
from .constants import KOBOLD_ROCKS, WOLF_FLEE_CHANCE, WOLF_FLEE_HEALTH, WOLF_PACK_HURT, WOLF_PACK_SHARE
from .constants import (MONKEY_DEATH_GOLD, MONKEY_DRINK_CHANCE, MONKEY_FLEE, MONKEY_FLEE_CHANCE, MONKEY_FLEE_HEALTH,
                        MONKEY_GOLD)
from .entities import (UNDEAD, MONSTERS, PLAYER_COLOR_NAMES, PLAYER_COLORS, PLAYER_GLYPHS, Merchant, Monster, Npc, Player,
                       apply_gear, danger, make_merchant, make_monster, make_npc, make_player, reset_player)
from .items import (AUTO_PICKUP, ITEMS, Item, enhance_weapon, make_amulet, make_barrel, make_cloak, make_gold, make_item,
                    make_key, make_staff, make_wand)
from .tiles import (ALTAR, ALTAR_SPENT, ASH, CRACKED, DEEP, DOOR, FLOOR, FOLIAGE, GRASS, HOVER, LAVA, LOCK_COLORS, LOCKED,
                    PIT, POND, SHALLOW, STAIRS_DOWN, STAIRS_UP, TORCH, TRAMPLED, TRANSPARENT,
                    WALKABLE, WALL)
from .version import VERSION

DIRS8 = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]


def beside(mask: np.ndarray) -> np.ndarray:
    """Every tile touching one in `mask`, diagonals included."""
    w, h = mask.shape
    near = np.zeros_like(mask)
    for dx, dy in DIRS8:
        near[max(dx, 0):w + min(dx, 0), max(dy, 0):h + min(dy, 0)] |= \
            mask[max(-dx, 0):w + min(-dx, 0), max(-dy, 0):h + min(-dy, 0)]
    return near

WHITE = (230, 230, 230)
BONE = (225, 220, 195)
GRAY = (160, 160, 160)
RED = (255, 100, 100)
ORANGE = (255, 170, 80)
GOLD = (255, 215, 90)
PURPLE = (225, 140, 255)
TEAL = (150, 255, 240)

VIOLET = (190, 140, 255)

PACK_KINDS = ("cultist", "cult_leader", "wolf", "kobold", "kobold_leader", "skeleton_warrior", "spider_queen", "spider")
AMULET_FROM_DOORS, AMULET_FROM_STAIRS = 15, 20  # steps' walk
PATH_MAPS = 256  # distance maps a level keeps before starting over
PACK_ORDER = ("potion", "wand", "ranged", "ammo", "bomb", "weapon", "armor", "cloak", "key", "hook", "amulet", "gold",
              "food")
FLAMMABLE = (GRASS, FOLIAGE, TRAMPLED)
BURNABLE = (FLOOR, GRASS, FOLIAGE, TRAMPLED, ASH)   # ground a wand's fire can catch on
# What a monster leaves on the floor where it dies. Anything not listed bleeds.
STAINS = {"slime": "goo", "skeleton_archer": "bones", "skeleton_warrior": "bones", "dragon": "bones",
          "necromancer": "bones", "zombie": "rot", "mushroom": "spores", "ghost": None,
          "spider_queen": "goo", "spider": "goo"}
SPIDERS = ("spider_queen", "spider")
STAY_PUT = ("mushroom", "necromancer", "dragon", "ghost")   # never run, even on fire
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
        self.hidden, self.cracks = gen.hidden, set(gen.cracks)
        self.cave = gen.cave                                 # the big cave the level grew from, if any
        self.webs: set[tuple[int, int]] = set()              # spider webs, which slow whoever walks in
        self.webs_changed = False                            # since the players were last told
        self.torches = gen.torches
        open_floor = self.walkable.copy()
        for room in (gen.vault, gen.hidden):
            if room is not None:
                open_floor &= ~room
        self.floor_cells = [(int(x), int(y)) for x, y in np.argwhere(open_floor)]
        self.fire: dict[tuple[int, int], int] = {}     # burning tiles, and the tick each goes out
        self.fire_at = 0                               # the tick fire next spreads
        self.fire_by: Player | None = None             # who started it
        self.stains: dict[tuple[int, int], str] = {}   # what monsters left where they died
        self.new_stains: list[list] = []               # stains to tell the players about
        self.bombs: list[dict] = []                    # lit bombs: x, y, the tick it goes off, and who lit it
        self.npcs: list[Npc] = []
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

    def _set_tile(self, x: int, y: int, tile: int) -> None:
        self.tiles[x, y] = tile
        self.walkable[x, y], self.hover[x, y] = WALKABLE[tile], HOVER[tile]
        self._base_transparent[x, y] = TRANSPARENT[tile]
        self.plants[x, y] = tile in (GRASS, FOLIAGE)
        self.door_version += 1
        self.changes.append([x, y, tile])

    def burn_out(self, x: int, y: int) -> None:
        """Grass that has burned leaves ash, which hides nothing and burns no more."""
        self._set_tile(x, y, ASH)

    def open_crack(self) -> None:
        """A bomb has broken the cracked wall, all of it: the room behind it joins the floor."""
        for c in self.cracks:
            self._set_tile(*c, FLOOR)
            self.mainland[c] = True
        self.mainland[self.hidden] = True
        self.land_cells = [(int(x), int(y)) for x, y in np.argwhere(self.mainland)]
        self.cracks = set()
        self._paths.clear()

    def unlock(self) -> None:
        self.tiles[self.lock] = DOOR
        self.walkable[self.lock] = self.hover[self.lock] = self.is_door[self.lock] = True
        self.mainland[self.lock] = True
        self.mainland[self.vault] = True
        self.lock = None
        self.door_version += 1
        self._paths.clear()


class World:
    def __init__(self, seed: int | None = None, difficulty: str = DEFAULT_DIFFICULTY, season_fn=lambda: None):
        self.seed = seed if seed is not None else random.randrange(1, 2 ** 31)
        self.difficulty = difficulty if difficulty in DIFFICULTIES else DEFAULT_DIFFICULTY
        rules = DIFFICULTIES[self.difficulty]
        self.monster_time = rules["monster_time"]       # how slow monsters are next to players
        self.toughness = rules["toughness"]             # monsters' health multiplier and extra defense
        self.regen = rules["regen"]                     # players heal over time on their own
        self.revive_seconds: float | None = rules["revive"]  # None: the fallen stay down
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
        self.maps: dict[tuple[int, int], mapgen.GeneratedLevel] = {}  # (seed, depth): looked at, not built yet
        self.fishers: dict[int, int | None] = {}  # seed: the fisherman's floor
        self.players: dict[int, Player] = {}   # connected players
        self.offline: dict[str, Player] = {}   # disconnected, keyed by name, restored on rejoin
        self.bots: dict[int, dict] = {}        # bot player -> who added it and more (see bots.py)
        self.clock = 0
        self.dirty = True                      # something changed since the last state was sent
        self.outbox: list[tuple[int | None, dict]] = []
        self.run = 1
        self.run_start = 0                     # the tick this run began, for the UI clock
        self.reset_at: float | None = None
        self.ready: set[int] = set()           # players who pressed Enter to skip the wipe wait
        self._ids = itertools.count(1)
        self.ledger: list[dict] = [self.ledger_head()]  # action log messages to send out

    # ------------------------------------------------------------ levels

    def level(self, depth: int) -> Level:
        lvl = self.levels.get(depth)
        if lvl is None:
            lvl = Level(depth, self.maps.pop((self.seed, depth), None) or self._map(depth))
            self.levels[depth] = lvl
            self._populate(lvl)
        return lvl

    def _map(self, depth: int) -> mapgen.GeneratedLevel:
        """A floor's layout, before anything lives on it."""
        room = self.locked_rooms.get(depth)
        hidden = (room is None and not self._cult_planned(depth)
                  and random.Random(f"{self.seed}:{depth}:hidden").random() < HIDDEN_ROOM_CHANCE)
        return mapgen.generate(self.seed, depth, LOCKED[room.color] if room else None, hidden)

    def _cult_planned(self, depth: int) -> bool:
        """Whether this floor's cult gathers around an altar. It's settled by the seed, the same
        way _add_cult settles it, so other floors can know before this one is built."""
        if depth < CULT_FIRST or depth in (ATRIUM_FLOOR, LAST_FLOOR) or depth > LAST_FLOOR:
            return False
        return random.Random(f"{self.seed}:{depth}:cult").random() < CULT_CHANCE

    def _mage_floor(self, cult_depth: int) -> int:
        """The floor next to a cult's where its mage waits: above or below, by the seed."""
        step = random.Random(f"{self.seed}:{cult_depth}:mage").choice((-1, 1))
        for depth in (cult_depth + step, cult_depth - step):
            if 1 <= depth < ATRIUM_FLOOR:
                return depth
        return cult_depth

    def fisher_floor(self) -> int | None:
        """A floor from FISHER_FLOORS with water to fish in, picked by the seed. None in the rare
        run with no water on any of them."""
        if self.seed not in self.fishers:
            floors = list(range(FISHER_FLOORS[0], FISHER_FLOORS[1] + 1))
            random.Random(f"{self.seed}:fisher").shuffle(floors)
            self.fishers[self.seed] = next((d for d in floors if self._shore(self._layout(d))), None)
        return self.fishers[self.seed]

    def _layout(self, depth: int) -> np.ndarray:
        """A floor's tiles, built or not. A floor looked at early keeps its map for when it's built."""
        if depth in self.levels:
            return self.levels[depth].tiles
        if (self.seed, depth) not in self.maps:
            self.maps[(self.seed, depth)] = self._map(depth)
        return self.maps[(self.seed, depth)].tiles

    @staticmethod
    def _shore(tiles: np.ndarray, cells=None) -> list[tuple[int, int]]:
        """Floor tiles beside water, of `cells` if given."""
        near = beside(np.isin(tiles, (SHALLOW, DEEP, POND))) & np.isin(tiles, (FLOOR, GRASS, TRAMPLED))
        return [c for c in cells if near[c]] if cells is not None else [tuple(map(int, c)) for c in np.argwhere(near)]

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
        mushrooms = 0
        for x, y in spots[:4 + lvl.depth // 2 + rng.randint(0, 3)] if kinds else ():  # some floors only have packs
            kind = rng.choices([k for k, _ in kinds], [w for _, w in kinds])[0]
            if kind == "ogre" and lvl.depth > OGRE_PEAK[1] and rng.random() >= OGRE_LATE_SHARE:
                continue
            if kind == "mushroom":
                if mushrooms >= MUSHROOM_MOST or rng.random() >= MUSHROOM_SHARE:
                    continue
                mushrooms += 1
            m = self._new_monster(kind)
            m.state = "sleeping" if rng.random() < 0.6 else "wandering"
            m.lag = m.next_time = rng.randrange(TICKS_PER_TURN)
            lvl.place(m, x, y)
            lvl.monsters.append(m)
        if not quiet:
            self._add_cult(lvl)
            self._add_wolves(lvl)
            self._add_slimes(lvl)
            self._add_skeletons(lvl)
            self._add_kobolds(lvl)
            self._add_mage(lvl)
            self._add_spiders(lvl)
            self._add_monkey(lvl)
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
        if FISHER_FLOORS[0] <= lvl.depth <= FISHER_FLOORS[1] and lvl.depth == self.fisher_floor():
            self._add_fisherman(lvl)
        if lvl.hidden is not None:
            self._add_fairy(lvl)
        self._add_barrel(lvl)

    def _new_monster(self, kind: str) -> Monster:
        """A monster dressed for the season, as tough as the difficulty makes it."""
        m = seasons.dress_monster(make_monster(kind, next(self._ids)), self.season)
        health, defense = self.toughness
        m.hp = m.max_hp = max(1, round(m.max_hp * health))
        m.defense = max(0, m.defense + defense)
        return m

    def _add_npc(self, lvl: Level, role: str, spot: tuple[int, int]) -> Npc:
        npc = make_npc(next(self._ids), role)
        lvl.place(npc, *spot)
        lvl.npcs.append(npc)
        return npc

    def _add_fisherman(self, lvl: Level) -> None:
        """On the shore, away from the stairs if he can be. His floor was picked for its water."""
        rng = random.Random(f"{self.seed}:{lvl.depth}:fisher")
        from_stairs = lvl.distances_to(*lvl.up_front)
        shore = self._shore(lvl.tiles, [c for c in lvl.floor_cells if c not in lvl.occupant and c not in lvl.items
                                        and lvl.mainland[c] and from_stairs[c] < algo.INF])
        away = [c for c in shore if from_stairs[c] >= 8 * algo.CARDINAL_COST]
        if shore:
            self._add_npc(lvl, "fisherman", rng.choice(away or shore))

    def _add_fairy(self, lvl: Level) -> None:
        cells = sorted((int(x), int(y)) for x, y in np.argwhere(lvl.hidden))
        self._add_npc(lvl, "fairy", random.Random(f"{self.seed}:{lvl.depth}:fairy").choice(cells))

    def _quiet_room(self, lvl: Level, front: tuple[int, int]) -> list[tuple[int, int]] | None:
        """The room a torch lights, if doors close it off and there's nothing else in it."""
        room, queue, doors = {front}, deque([front]), 0
        while queue:
            cx, cy = queue.popleft()
            for dx, dy in ((0, 1), (1, 0), (0, -1), (-1, 0)):
                n = (cx + dx, cy + dy)
                if n in room or not lvl.in_bounds(*n) or not lvl.walkable[n]:
                    continue
                if lvl.is_door[n]:
                    doors += 1
                    continue
                room.add(n)
                queue.append(n)
                if len(room) > FOOD_ROOM_MOST:
                    return None
        stairs = {lvl.up_front, lvl.down_front}
        torches = sum(1 for _, f in lvl.torches if f in room)
        busy = any(c in lvl.occupant or c in lvl.items or c in stairs or lvl.tiles[c] != FLOOR for c in room)
        return sorted(room) if doors and torches == 1 and not busy else None

    def _add_barrel(self, lvl: Level) -> None:
        """One at most on a floor, in a room with a door and nothing in it but a torch."""
        rng = random.Random(f"{self.seed}:{lvl.depth}:barrel")
        for _, front in lvl.torches:
            room = self._quiet_room(lvl, front)
            if room:
                spots = [c for c in room if c != front] or room
                lvl.items[rng.choice(spots)] = make_barrel()
                return

    def _add_skeletons(self, lvl: Level) -> None:
        """A war band on every third floor from 50 to 70."""
        low, high = SKELETON_FLOORS
        if not low <= lvl.depth <= high or (lvl.depth - low) % SKELETON_EVERY:
            return
        room = SKELETON_MOST - sum(m.kind == "skeleton_warrior" for m in lvl.monsters)
        if room > 0:
            rng = random.Random(f"{self.seed}:{lvl.depth}:skeletons")
            size = (min(SKELETON_GROUP[0], room), min(SKELETON_GROUP[1], room))
            self._add_pack(lvl, rng, "skeleton_warrior", "skeleton_warrior", size)

    def _add_kobolds(self, lvl: Level) -> None:
        """Leaders with a few kobolds each, and scouts on their own."""
        rng = random.Random(f"{self.seed}:{lvl.depth}:kobolds")
        if KOBOLD_LEADER_FLOORS[0] <= lvl.depth <= KOBOLD_LEADER_FLOORS[1]:
            for _ in range(2):  # never more than two
                if rng.random() >= KOBOLD_LEADER_CHANCE:
                    break
                self._add_pack(lvl, rng, "kobold_leader", "kobold", (3, 4))
        if KOBOLD_SCOUT_FLOORS[0] <= lvl.depth <= KOBOLD_SCOUT_FLOORS[1] and rng.random() < KOBOLD_SCOUT_CHANCE:
            from_stairs = lvl.distances_to(*lvl.up_front)
            spots = [c for c in lvl.floor_cells if c not in lvl.occupant and 24 < from_stairs[c] < algo.INF]
            for spot in rng.sample(spots, min(len(spots), rng.randint(1, KOBOLD_SCOUT_MOST))):
                self._spawn(lvl, "kobold_scout", spot, rng, "wandering")

    def monkey_floor(self) -> int | None:
        """The one floor with a monkey, the thief of the fisherman's hooks: the floor below his or
        the one above, never floor 1. None in a run with no fisherman."""
        fisher = self.fisher_floor()
        if fisher is None:
            return None
        below = random.Random(f"{self.seed}:monkey").random() < 0.5 or fisher - 1 < 2
        return fisher + 1 if below else fisher - 1

    def _add_monkey(self, lvl: Level) -> None:
        """Only near the fisherman's floor, so the floors he can't be next to never work it out."""
        if not (max(2, FISHER_FLOORS[0] - 1) <= lvl.depth <= FISHER_FLOORS[1] + 1):
            return
        if self.monkey_floor() != lvl.depth:
            return
        rng = random.Random(f"{self.seed}:{lvl.depth}:monkey")
        from_stairs = lvl.distances_to(*lvl.up_front)
        spots = [c for c in lvl.floor_cells if c not in lvl.occupant and 24 < from_stairs[c] < algo.INF]
        if spots:
            self._spawn(lvl, "monkey", rng.choice(spots), rng, "wandering")

    def _add_mage(self, lvl: Level) -> None:
        """A cultist mage, a floor away from each cult that has one."""
        for cult in (lvl.depth - 1, lvl.depth + 1):
            if self._cult_planned(cult) and self._mage_floor(cult) == lvl.depth:
                rng = random.Random(f"{self.seed}:{lvl.depth}:{cult}:mage")
                from_stairs = lvl.distances_to(*lvl.up_front)
                spots = [c for c in lvl.floor_cells if c not in lvl.occupant and 24 < from_stairs[c] < algo.INF]
                if spots:
                    self._spawn(lvl, "cult_mage", rng.choice(spots), rng, "wandering")

    def _spawn(self, lvl: Level, kind: str, spot: tuple[int, int], rng: random.Random, state: str) -> Monster:
        m = self._new_monster(kind)
        m.state = state
        m.lag = m.next_time = rng.randrange(TICKS_PER_TURN)
        lvl.place(m, *spot)
        lvl.monsters.append(m)
        return m

    def _add_spiders(self, lvl: Level, force: bool = False) -> bool:
        """A spider queen nests in the level's big cave, if it has one, with her brood around her
        and webs spun across it, well away from the stairs. Forced, she nests anywhere."""
        rng = random.Random(f"{self.seed}:{lvl.depth}:spiders")
        if not force and not (SPIDER_FLOORS[0] <= lvl.depth <= SPIDER_FLOORS[1] and rng.random() < SPIDER_CHANCE):
            return False
        if lvl.cave is None and not force:
            return False
        from_stairs = lvl.distances_to(*lvl.up_front)
        nest = [c for c in lvl.floor_cells if c not in lvl.occupant and lvl.mainland[c] and lvl.tiles[c] == FLOOR
                and 12 * algo.CARDINAL_COST < from_stairs[c] < algo.INF and (lvl.cave is None or lvl.cave[c])]
        if len(nest) < 20:
            return False
        queen_at = rng.choice(nest)
        queen = self._spawn(lvl, "spider_queen", queen_at, rng, "wandering")
        queen.post = queen_at
        middle = lvl.distances_to(*queen_at)
        near = sorted((c for c in nest if c != queen_at), key=lambda c: (middle[c], c))
        for spot in near[:rng.randint(*SPIDER_BROOD)]:
            m = self._spawn(lvl, "spider", spot, rng, "wandering")
            m.leader = queen
        if force:  # webs around her, wherever she is
            nest = [c for c in near if middle[c] <= 8 * algo.CARDINAL_COST]
        for c in rng.sample(nest, max(1, int(len(nest) * WEB_SHARE))):
            lvl.webs.add(c)
        lvl.webs_changed = True
        return True

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
            m = self._new_monster("slime")
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
            m = self._new_monster(kind if leader else lead)
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
        m = self._new_monster("dragon")
        m.state, m.next_time = "sleeping", 0
        lvl.place(m, *spot)
        lvl.monsters.append(m)

    def _add_lair(self, lvl: Level) -> None:
        """The necromancer, asleep, and the Amulet across the room from it: close enough to
        be in its sight, but with the stealth to do it, far enough to creep to and back."""
        rng = random.Random(f"{self.seed}:lair")
        m = self._new_monster("necromancer")
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
        kinds = [k for k, t in ITEMS.items() if t["category"] == "potion" and t["weight"] > 0]
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
        kinds += ["antidote", "bomb"]  # always in stock
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
    def clean_key(key) -> str:
        """A key name from a client, for showing in messages. It came over the network, so
        anything that isn't a short, plain name gets the default."""
        return key if isinstance(key, str) and 0 < len(key) <= 12 and key.isprintable() else "g"

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
            self.note(p, f"returned hp {self._hp(p)}")
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
        self.note(p, f"joined hp {self._hp(p)}")
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
        self.note(p, f"left hp {self._hp(p)}")
        self._check_all_dead()

    def submit(self, p: Player, msg: dict) -> None:
        """Queue a player's action (replacing any earlier queued one). It runs now, or
        when their cooldown ends."""
        a = msg.get("a")
        if a == "sprint":  # kept even while down, or a held Shift would be lost on revival
            p.sprinting = bool(msg.get("on"))
            return
        if a == "ready":
            self._ready(p)
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
                if p.pending is not None and p.pending["a"] not in ("move", "auto"):
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
        elif a in ("use", "drop", "sell"):
            slot = msg.get("slot")
            if not isinstance(slot, int) or isinstance(slot, bool) or not 0 <= slot < PACK_SIZE:
                return
            p.pending = {"a": a, "slot": slot}
        elif a in ("descend", "ascend", "pickup", "dropgold", "quickheal", "sort"):
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

    def ledger_head(self) -> dict:
        """Starts a run's action log. Someone joining later is sent this too."""
        return {"t": "log", "run": self.run, "seed": self.seed,
                "head": f"Togetherogue {VERSION} | run {self.run} | seed {self.seed} | {self.difficulty}"}

    def note(self, who, text: str, depth: int | None = None) -> None:
        """A line in the action log. `who` is a player, a monster or just a name."""
        seconds = max(0, self.clock - self.run_start) / TICKS_PER_SECOND
        stamp = f"{int(seconds // 3600)}:{int(seconds // 60 % 60):02d}:{seconds % 60:04.1f}"
        depth = getattr(who, "depth", 0) if depth is None else depth
        self.ledger.append({"t": "log", "line": f"{stamp} F{depth:02d} {self._tag(who)} {text}"})

    @staticmethod
    def _tag(who) -> str:
        """A name for the log. Monsters get their number, to tell one goblin from the next."""
        if isinstance(who, Monster):
            return f"{who.name}#{who.id}"
        return getattr(who, "name", None) or str(who)

    @staticmethod
    def _hp(a) -> str:
        return f"{max(a.hp, 0)}/{a.max_hp}"

    def drain_ledger(self) -> list[dict]:
        out, self.ledger = self.ledger, []
        return out

    def drain_outbox(self) -> list[tuple[int | None, dict]]:
        for lvl in self.levels.values():
            if lvl.changes:
                msg = {"t": "tiles", "depth": lvl.depth, "cells": lvl.changes}
                lvl.changes = []
                self.outbox += [(p.id, msg) for p in self.players.values() if p.depth == lvl.depth]
            if lvl.new_stains:
                msg = {"t": "stains", "depth": lvl.depth, "cells": lvl.new_stains}
                lvl.new_stains = []
                self.outbox += [(p.id, msg) for p in self.players.values() if p.depth == lvl.depth]
            if lvl.webs_changed:
                lvl.webs_changed = False
                msg = {"t": "webs", "depth": lvl.depth, "cells": sorted(lvl.webs)}
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
                    if self.regen:
                        self._regen(p, ticks)
                    self._fill_stealth(p, ticks)
                    self._fill_stamina(p, ticks)
                    for effect, text in WEAR_OFF:
                        ends = getattr(p, effect)
                        if ends and self.clock >= ends and p.alive:
                            setattr(p, effect, 0)
                            self.note(p, f"{effect.removesuffix('_until')} wore off")
                            self.dirty = True
                            self._touch_down(p, text)
            self._tick_auto_attacks()
            self._tick_revives(ticks)
            self._tick_gas(ticks)
            self._tick_fire(ticks)
            self._tick_bombs()
            self._tick_food(ticks)
            self._tick_boomerangs()
            self._tick_tide()
            self._tick_haunts()

    def _seconds(self, seconds) -> int:
        """Ticks in a number of seconds, or a random number of them from a (low, high) pair."""
        if isinstance(seconds, tuple):
            seconds = self.rng.uniform(*seconds)
        return int(seconds * TICKS_PER_SECOND)

    def _start_fire(self, lvl: Level, x: int, y: int, by: Player | None) -> None:
        """A wand of fire's bolt sets the ground around where it lands alight."""
        lvl.fire_by = by
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                c = (x + dx, y + dy)
                if lvl.in_bounds(*c) and lvl.tiles[c] in BURNABLE:
                    span = GRASS_FIRE_SECONDS if lvl.tiles[c] in FLAMMABLE else FIRE_SECONDS
                    lvl.fire[c] = max(lvl.fire.get(c, 0), self.clock + self._seconds(span))
        lvl.fire_at = self.clock + self._seconds(FIRE_SPREAD_SECONDS)
        self.dirty = True

    def _tick_fire(self, ticks: int) -> None:
        """Fire goes out, leaving ash where there was grass, and jumps to the grass beside it.
        Anything standing in it catches fire, and players in it get burned."""
        for lvl in self.levels.values():
            if not lvl.fire:
                continue
            self.dirty = True
            if lvl.webs & lvl.fire.keys():  # fire burns webs away
                lvl.webs -= lvl.fire.keys()
                lvl.webs_changed = True
            for c, end in list(lvl.fire.items()):
                if end <= self.clock:
                    del lvl.fire[c]
                    if lvl.tiles[c] in FLAMMABLE:
                        lvl.burn_out(*c)
            if lvl.fire and self.clock >= lvl.fire_at:
                lvl.fire_at = self.clock + self._seconds(FIRE_SPREAD_SECONDS)
                for x, y in [c for c in lvl.fire if lvl.tiles[c] in FLAMMABLE]:
                    for dx, dy in DIRS8:
                        n = (x + dx, y + dy)
                        if lvl.in_bounds(*n) and n not in lvl.fire and lvl.tiles[n] in FLAMMABLE \
                                and self.rng.random() < FIRE_SPREAD_CHANCE:
                            lvl.fire[n] = self.clock + self._seconds(GRASS_FIRE_SECONDS)
            for m in lvl.monsters:
                if (m.x, m.y) in lvl.fire and m.burning < 2:
                    m.burning, m.burned_by = max(m.burning, 2), lvl.fire_by
            for p in self._living_on(lvl.depth):
                if (p.x, p.y) in lvl.fire and not self._levitating(p) and p.lavawalk_until <= self.clock:
                    self._stand_in_fire(p, ticks)

    def _stand_in_fire(self, p: Player, ticks: int) -> None:
        p.fire_ticks += ticks
        if p.fire_ticks < TICKS_PER_SECOND or p.god:
            return
        p.fire_ticks -= int(TICKS_PER_SECOND)
        p.hp -= FIRE_DAMAGE
        self.note(p, f"fire -{FIRE_DAMAGE} hp {self._hp(p)}")
        self.tell(p, "You're standing in fire!", ORANGE)
        if p.hp <= 0:
            self._kill(p, None, f"Burned to death on depth {p.depth}.")

    def _tick_bombs(self) -> None:
        for lvl in self.levels.values():
            for bomb in [b for b in lvl.bombs if b["at"] <= self.clock]:
                lvl.bombs.remove(bomb)
                self._explode(lvl, bomb)

    def _explode(self, lvl: Level, bomb: dict) -> None:
        """Hurts everyone close, friend or foe, sets grass alight and breaks a cracked wall."""
        x, y, by = bomb["x"], bomb["y"], bomb["by"]
        cells = [(x + dx, y + dy) for dx in range(-BOMB_RADIUS, BOMB_RADIUS + 1)
                 for dy in range(-BOMB_RADIUS, BOMB_RADIUS + 1) if lvl.in_bounds(x + dx, y + dy)]
        blast = {"t": "fx", "kind": "blast", "cells": cells}
        for v in self._living_on(lvl.depth):
            self.outbox.append((v.id, blast))
        self.dirty = True
        self._narrate(lvl, [(x, y)], set(), lambda v: ("The bomb explodes!", ORANGE))
        self.note(by or "bomb", f"bomb went off at {x},{y}", lvl.depth)
        for c in cells:
            who = lvl.occupant.get(c)
            if isinstance(who, Monster):
                dmg = self.rng.randint(*BOMB_DAMAGE)
                who.hp -= dmg
                self.note(who, f"bombed -{dmg} hp {self._hp(who)}")
                if who.hp <= 0:
                    self._kill(who, by if by is not None and by.alive else None)
                elif by is not None and by.alive:
                    self._hunt(who, by)
            elif isinstance(who, Player) and who.alive and not who.god:
                dmg = self.rng.randint(*BOMB_DAMAGE)
                who.hp -= dmg
                self.note(who, f"bombed -{dmg} hp {self._hp(who)}")
                self.tell(who, "The blast throws you off your feet!", RED)
                if who.hp <= 0:
                    self._kill(who, None, f"Caught in a bomb blast on depth {who.depth}.")
            if lvl.tiles[c] in FLAMMABLE:
                lvl.fire[c] = self.clock + self._seconds(GRASS_FIRE_SECONDS)
                lvl.fire_by = by
            if c in lvl.cracks:
                lvl.open_crack()
                self._narrate(lvl, [c], set(), lambda v: ("The cracked wall crumbles. There's a room behind it!", GOLD))
                self.note(by or "bomb", "blew open a hidden room", lvl.depth)

    def _tick_food(self, ticks: int) -> None:
        for p in self.players.values():
            if not p.alive or p.food_until <= self.clock - ticks:
                continue
            p.food_ticks += ticks
            while p.food_ticks >= TICKS_PER_SECOND:
                p.food_ticks -= int(TICKS_PER_SECOND)
                p.hp = min(p.max_hp, p.hp + FOOD_HEAL)
                self.dirty = True
            if p.food_until <= self.clock:
                p.food_until = p.food_ticks = 0

    def _tick_boomerangs(self) -> None:
        for p in self.players.values():
            for item in p.pack:
                if item.back_at and item.back_at <= self.clock:
                    item.back_at = 0
                    if p.alive:
                        self.tell(p, f"Your {item.name} comes back to your hand.", GRAY)

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
        for p in [p for p in self.players.values() if p.alive and p.venom_until > self.clock - ticks]:
            self._suffer_venom(p, ticks)  # including venom that ran out partway through these ticks

    def _envenom(self, p: Player) -> None:
        """A spider's bite: more venom, up to VENOM_MOST seconds of it."""
        if p.god:
            return
        if p.venom_until <= self.clock:
            self.tell(p, "Venom burns in your veins. It won't kill you, but it will leave you weak.", ORANGE)
        p.venom_until = min(max(p.venom_until, self.clock) + self._seconds(VENOM_PER_BITE),
                            self.clock + self._seconds(VENOM_MOST))
        self.note(p, f"envenomed: {(p.venom_until - self.clock) / TICKS_PER_SECOND:.0f}s")
        self.dirty = True

    def _suffer_venom(self, p: Player, ticks: int) -> None:
        """Venom wears you down, but never past your last point of health."""
        p.venom_ticks += min(ticks, max(0, p.venom_until - (self.clock - ticks)))  # only while it lasted
        every = self._seconds(VENOM_EVERY)
        while p.venom_ticks >= every and not p.god:
            p.venom_ticks -= every
            if p.hp > 1:
                p.hp = max(1, p.hp - VENOM_DAMAGE)
                self.note(p, f"venom -{VENOM_DAMAGE} hp {self._hp(p)}")
                self.dirty = True

    def _breathe_gas(self, p: Player, ticks: int) -> None:
        p.gas_ticks += ticks
        if p.gas_ticks < TICKS_PER_SECOND or p.god:
            return
        p.gas_ticks -= int(TICKS_PER_SECOND)
        p.hp -= GAS_DAMAGE
        self.note(p, f"gas -{GAS_DAMAGE} hp {self._hp(p)}")
        self.tell(p, "You choke on the gas.", ORANGE)
        if p.hp <= 0:
            self._kill(p, None, f"Choked on toxic gas on depth {p.depth}.")

    def _suffer_toxin(self, p: Player, ticks: int) -> None:
        p.toxin_ticks += ticks
        if p.toxin_ticks < TICKS_PER_SECOND or p.god:
            return
        p.toxin_ticks -= int(TICKS_PER_SECOND)
        p.hp -= TOXIN_DAMAGE
        self.note(p, f"toxin -{TOXIN_DAMAGE} hp {self._hp(p)}")
        self.dirty = True
        if p.hp <= 0:
            self._kill(p, None, f"Poisoned by a slime on depth {p.depth}.")

    def _slimed(self, p: Player) -> None:
        """A slime's touch, or stepping in what it left behind."""
        if p.god or self._levitating(p):
            return
        if p.toxin_until <= self.clock:
            self.tell(p, "Slime clings to you. It burns, and you can hardly move.", ORANGE)
            self.note(p, "slimed: poisoned and slowed")
        p.toxin_until = self.clock + int(TOXIN_SECONDS * TICKS_PER_SECOND)
        p.slow_until = self.clock + int(SLOW_SECONDS * TICKS_PER_SECOND)

    def _tick_haunts(self) -> None:
        """An altar's ghost comes once you're far enough away to think you got off lightly."""
        for p in self.players.values():
            due = [floor for floor in p.haunts if abs(p.depth - floor) >= GHOST_FLOORS] if p.alive else []
            for floor in due:
                p.haunts.remove(floor)
                self._raise_ghost(p, self.levels[p.depth])
                self.note(p, f"haunted: ghost rose for the altar on F{floor:02d}")

    def _raise_ghost(self, p: Player, lvl: Level) -> None:
        """Anywhere out of sight, walls included: it doesn't need to stand on floor."""
        sight = self.fov(p)
        spots = [(x, y) for x in range(1, MAP_W - 1) for y in range(1, MAP_H - 1)
                 if GHOST_DISTANCE[0] <= max(abs(x - p.x), abs(y - p.y)) <= GHOST_DISTANCE[1]
                 and not sight[x, y] and (x, y) not in lvl.occupant
                 and lvl.tiles[x, y] not in (STAIRS_DOWN, STAIRS_UP)]
        if not spots:
            spots = [c for c in lvl.land_cells if c not in lvl.occupant]
        g = self._new_monster("ghost")
        g.state, g.next_time = "hunting", self.clock + TICKS_PER_TURN
        lvl.place(g, *self.rng.choice(spots))
        lvl.monsters.append(g)
        self.dirty = True
        self.tell(p, "A chill runs through you. Something has followed you from the altar.", PURPLE)

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
        z = self._new_monster("zombie")
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
                if rescuer and progress >= self.revive_seconds * TICKS_PER_SECOND:
                    self._revive(p, rescuer, lvl)

    def _revive(self, p: Player, rescuer: Player, lvl: Level) -> None:
        lvl.downed.remove(p)
        p.alive, p.downed, p.revive_ticks, p.death, p.final_gold = True, False, 0, "", None
        p.hp = max(1, int(p.max_hp * REVIVE_HEALTH))
        p.next_time = self.clock
        lvl.place(p, *lvl.free_near(p.x, p.y))
        self.broadcast(f"{rescuer.name} revives {p.name}!", GOLD)
        self.note(p, f"revived by {rescuer.name} hp {self._hp(p)}")

    def _revive_percent(self, p: Player) -> int:
        return int(100 * p.revive_ticks / (self.revive_seconds * TICKS_PER_SECOND))

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
        slow = WEB_FACTOR if p.webbed_until > self.clock else SLOW_FACTOR if p.slow_until > self.clock else 1
        cost = p.move_cost * slow
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

    def wiped(self) -> bool:
        """The whole party has fallen and a fresh dungeon is on its way."""
        return self.reset_at is not None and not self.victory

    def _ready(self, p: Player) -> None:
        """Enter after a wipe: start the new dungeon now, once every connected player wants to."""
        if not self.wiped() or p.id in self.ready:
            return
        self.ready.add(p.id)
        waiting = [q for q in self.players.values() if q.connected and q.id not in self.ready]
        if not waiting:
            self.reset_at = 0.0
            return
        total = sum(1 for q in self.players.values() if q.connected)
        self.broadcast(f"{p.name} is ready for a new dungeon ({total - len(waiting)}/{total}).", GOLD)

    def check_reset(self, now: float) -> bool:
        """Start a fresh dungeon once the wipe delay is over. Returns True if it did."""
        if self.reset_at is None or now < self.reset_at:
            return False
        self.reset_run()
        return True

    # ----------------------------------------------------------- actions

    def _auto_choice(self, p: Player) -> tuple | None:
        """What auto attack would do now: ("melee", monster) for one fighting beside you, else
        ("ranged", monster) for one your readied weapon can reach. None if nothing."""
        lvl = self.levels[p.depth]
        sight = self.fov(p)

        def fighting(m) -> bool:
            return (m.state == "hunting" and sight[m.x, m.y] and not (m.kind == "monkey" and not m.provoked))

        beside = [m for m in lvl.monsters if cheb(p, m) == 1 and fighting(m) and not self._floating(m)
                  and not self._levitating(m) and not lvl.diagonal_blocked(p.x, p.y, m.x, m.y)]
        if beside:
            order = 1 if p.aim == "Weakest" else -1
            return "melee", min(beside, key=lambda m: (order * danger(m.kind), m.id))
        item = p.ranged
        if item is None or item not in p.pack:
            return None
        if item.category == "ranged":
            if item.back_at > self.clock or (item.fires and not any(i.category == "ammo" for i in p.pack)):
                return None
            reach = item.reach
        else:
            reach = STAFF_RANGE if item.lightning else WAND_RANGE
        near = [m for m in lvl.monsters if fighting(m) and cheb(p, m) <= reach
                and not (item.freeze and m.frozen_until > self.clock)]  # no use freezing it twice
        if not near:
            return None
        order = 1 if p.aim == "Weakest" else -1
        return "ranged", min(near, key=lambda m: (order * danger(m.kind), cheb(p, m), m.id))

    def _tick_auto_attacks(self) -> None:
        for p in self.players.values():
            if (p.auto_attack and p.alive and p.connected and p.pending is None and p.hold is None
                    and p.next_time <= self.clock and self._auto_choice(p)):
                p.pending = {"a": "auto"}

    def _auto_attack(self, p: Player, lvl: Level, met) -> int:
        """Decided again as it happens, since things move in the meantime."""
        choice = self._auto_choice(p)
        if choice is None:
            return 0
        kind, m = choice
        if kind == "melee":
            return self._player_move(p, lvl, m.x - p.x, m.y - p.y, met)
        item = p.ranged
        return self._shoot(p, item, m) if item.category == "ranged" else self._zap(p, item, m)

    def _perform(self, p: Player, act: dict) -> None:
        lvl = self.levels[p.depth]
        a = act["a"]
        cost = 0
        met, p.met = p.met, None  # walking into a merchant or fisherman again right away steps past them
        if a == "move":
            cost = self._player_move(p, lvl, act["dx"], act["dy"], met)
        elif a == "auto":
            cost = self._auto_attack(p, lvl, met)
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
        elif a == "quickheal":
            cost = self._quick_heal(p)
        elif a == "sort":
            self._sort_pack(p)
        elif a == "buy":
            cost = self._buy(p, lvl, act["id"])
        elif a == "sell":
            cost = self._sell(p, lvl, act["slot"])
        elif a == "enhance":
            cost = self._enhance(p, lvl, act["x"], act["y"])
        if cost > 0 and p.alive:
            if p.haste_until > self.clock:
                cost //= 2
            p.next_time = self.clock + cost
            p.turns += 1
            if a in ("move", "descend", "ascend") and not self._levitating(p):
                p.stealth = max(0.0, p.stealth - STEALTH_MOVE_DRAIN)

    def _player_move(self, p: Player, lvl: Level, dx: int, dy: int, met: int | None = None) -> int:
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
            if isinstance(other, Merchant) or (isinstance(other, Npc) and other.role == "fisherman"):
                if met == other.id:  # they never stand in your way, even in a doorway
                    return self._pass_ally(p, other, lvl, dx, dy)
                p.met = other.id
            if isinstance(other, Merchant):
                self.outbox.append((p.id, self._shop_msg(other)))
                self.tell(p, f"The {other.name}'s wares. Tab to sell. Walk into them again to pass.", GOLD)
                return 0
            if isinstance(other, Npc):
                return self._meet(p, other, lvl)
            if other.is_player:
                return self._pass_ally(p, other, lvl, dx, dy)
            if self._floating(other):
                self.tell(p, f"The {other.name} floats out of reach. Only ranged attacks and magic hit it now.", VIOLET)
                return 0
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

    def _pass_ally(self, p: Player, other, lvl: Level, dx: int, dy: int) -> int:
        """Allies never block each other, nor do merchants or the fisherman. You walk straight
        past them, which leaves them where they are, or trade places if there's nowhere to land.
        You must be able to stand where they're standing, or someone floating over a lake would
        be a bridge across it."""
        x, y = other.x, other.y
        while self._can_be_at(p, lvl, x, y) and lvl.in_bounds(x + dx, y + dy) \
                and not lvl.diagonal_blocked(x, y, x + dx, y + dy):
            x, y = x + dx, y + dy
            ahead = lvl.actor_at(x, y)
            if ahead is None:
                if self._can_land(p, lvl, x, y):
                    lvl.move(p, x, y)
                    self._step_onto(p, lvl)
                    return self._stride(p)
                break
            if not ahead.is_player:
                break
        ox, oy, nx, ny = p.x, p.y, other.x, other.y
        they_fit = self._can_be_at(other, lvl, ox, oy) if other.is_player else bool(lvl.walkable[ox, oy])
        if not (self._can_be_at(p, lvl, nx, ny) and they_fit):
            self.tell(p, f"There's no way past {other.name if other.is_player else 'the ' + other.name} here.", GRAY)
            return 0
        lvl.remove(p)
        lvl.remove(other)
        lvl.place(p, nx, ny)
        lvl.place(other, ox, oy)
        if other.is_player:
            self.tell(other, f"{p.name} swaps places with you.", GRAY)
        self._step_onto(p, lvl)
        return self._stride(p)

    def _floating(self, m) -> bool:
        return isinstance(m, Monster) and m.float_until > self.clock

    def _meet(self, p: Player, npc: Npc, lvl: Level) -> int:
        if npc.role == "fisherman":
            if not self._return_hooks(p, lvl):
                self._fisherman_talks(p, npc)
            if npc.talks == 1:
                self.tell(p, "Walk into him again to step past.", GRAY)
            return 0
        # A fairy: freed, it blesses the whole party, then it's gone.
        lvl.remove(npc)
        lvl.npcs.remove(npc)
        sparkle = {"t": "fx", "kind": "sparkle", "cells": [(npc.x, npc.y)]}
        for v in self._living_on(lvl.depth):
            self.outbox.append((v.id, sparkle))
        for q in self.players.values():
            if q.alive:
                boost = max(1, round(q.max_hp * FAIRY_BOOST))
                q.max_hp += boost
                q.hp += boost
                self.note(q, f"fairy: max health +{boost} hp {self._hp(q)}")
        self.broadcast(f"{p.name} frees a fairy! It blesses the party: everyone's health rises by a fifth.", TEAL)
        return TICKS_PER_TURN

    def _return_hooks(self, p: Player, lvl: Level) -> bool:
        """Monkeys take the fisherman's hooks. He gives a potion of strength for each one brought back."""
        hooks = next((i for i in p.pack if i.category == "hook"), None)
        if hooks is None:
            return False
        count = hooks.count
        p.pack.remove(hooks)
        p.pack_dirty = True
        for _ in range(count):
            potion = self._item("strength")
            if not self._stash(p, potion):
                lvl.items[lvl.free_item_spot(p.x, p.y)] = potion
        if count == 1:
            words = ("My hook! One of those thieving monkeys took it right off my line. "
                     "Thank you for getting it back. Here, take this potion of strength.")
        else:
            words = (f"My hooks! All {count} of them, back from those thieving monkeys. "
                     f"Thank you for getting them back. Here, take these {count} potions of strength.")
        self.tell(p, f'The fisherman says: "{words}"', TEAL)
        self.note(p, f"gave the fisherman {count} hook{'s' if count > 1 else ''} for strength")
        return True

    def _fisherman_talks(self, p: Player, npc: Npc) -> None:
        """He knows where the keys to the locked rooms lie, one at a time. With none, he gives a tip."""
        rooms = sorted(self.locked_rooms.values(), key=lambda r: r.depth)
        if rooms:
            room = rooms[npc.talks % len(rooms)]
            self.tell(p, f'The fisherman says: "The {room.color} key lies on floor {room.key_depth}. '
                         f'Its door is on floor {room.depth}."', TEAL)
        else:
            self.outbox.append((p.id, {"t": "tip", "who": "The fisherman"}))  # the client knows your keys
        npc.talks += 1
        self.note(p, "talked to the fisherman")

    def _can_land(self, p: Player, lvl: Level, x: int, y: int) -> bool:
        """Whether a step past an ally can end here, which must never be anywhere a step
        wouldn't normally just walk onto."""
        return (self._can_be_at(p, lvl, x, y) and (x, y) != lvl.lock
                and lvl.tiles[x, y] not in (STAIRS_DOWN, STAIRS_UP, PIT, ALTAR))

    def _offer(self, p: Player, x: int, y: int) -> int:
        if p.weapon is None:
            self.tell(p, "The altar hums. It wants a weapon in your hand.", PURPLE)
        else:
            self.outbox.append((p.id, {"t": "prompt", "text": "Would you like to enhance your weapon?", "x": x, "y": y}))
        return 0

    def _enhance(self, p: Player, lvl: Level, x: int, y: int) -> int:
        """Each altar works once, and what it does is the weapon's for good, whoever holds it.
        The one who used it pays for that later: see _tick_haunts."""
        if lvl.tiles[x, y] != ALTAR or max(abs(p.x - x), abs(p.y - y)) > 1:
            self.tell(p, "There's no altar within reach.", GRAY)
            return 0
        if p.weapon is None:
            self.tell(p, "You're not holding a weapon.", GRAY)
            return 0
        result = enhance_weapon(p.weapon, self.rng)
        lvl.spend_altar(x, y)
        p.haunts.append(lvl.depth)
        apply_gear(p)
        p.pack_dirty = True
        self.tell(p, f"Purple fire sinks into your {p.weapon.name}: {result}, and every blow hits harder.", PURPLE)
        self.note(p, f"enhanced {p.weapon.name}: {result}")
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
        self.note(p, f"unlocked the {room.color} door")
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
        self.note(p, f"fell F{lvl.depth:02d}->F{p.depth:02d} hp {self._hp(p)}")
        self._hear_merchant(p, below)
        if not self._can_be_at(p, below, p.x, p.y):
            self._burn(p, below)

    def _burn(self, p: Player, lvl: Level) -> None:
        """Lava. It's a long way from fatal only at good health."""
        self.tell(p, "You're in lava!", RED)
        if not p.god:
            p.hp -= LAVA_DAMAGE
        self.note(p, f"lava -{0 if p.god else LAVA_DAMAGE} hp {self._hp(p)}")
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
        if (p.x, p.y) in lvl.webs and not self._levitating(p) and not p.god:
            if p.slow_until <= self.clock:
                self.tell(p, "You blunder into a web. It clings to you.", GRAY)
            p.slow_until = max(p.slow_until, self.clock + self._seconds(SLOW_SECONDS))
        item = lvl.items.get((p.x, p.y))
        if item is None:
            return
        if item.category == "food":
            self._eat(p, lvl)
        elif item.category in AUTO_PICKUP:
            self._pick_up(p, lvl)
        else:
            self.tell(p, f"You see {self._a(item)} here. Press {p.pickup_key} to pick it up.", GRAY)

    def _eat(self, p: Player, lvl: Level) -> None:
        """A barrel of food: health comes back quickly for a few seconds, and the barrel's empty."""
        del lvl.items[(p.x, p.y)]
        p.food_until = self.clock + self._seconds(FOOD_SECONDS)
        self.tell(p, "Food is good!", GOLD)
        self.note(p, f"ate from a barrel hp {self._hp(p)}")
        self._narrate(lvl, [(p.x, p.y)], set(), lambda v: (f"{p.name} eats from a barrel of food.", GRAY), exclude=p)

    def _bathe(self, p: Player, lvl: Level) -> None:
        """A pond heals you fully and wards you, and that's the end of the pond."""
        sparkle = {"t": "fx", "kind": "sparkle", "cells": lvl.drain_pond(p.x, p.y)}
        for v in self._living_on(p.depth):
            self.outbox.append((v.id, sparkle))
        p.hp = p.max_hp
        p.reflect_until = self.clock + int(REFLECT_SECONDS * TICKS_PER_SECOND)
        self.tell(p, "The water sparkles around you. You feel whole, and warded against magic.", TEAL)
        self.note(p, f"pond: healed and warded hp {self._hp(p)}")

    def _reflecting(self, p: Player) -> bool:
        return p.reflect_until > self.clock or (p.armor is not None and p.armor.reflect)

    def _pick_up(self, p: Player, lvl: Level) -> bool:
        item = lvl.items.get((p.x, p.y))
        if item is None:
            return False
        if item.category == "food":
            self._eat(p, lvl)
            return True
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
        self.note(p, f"got {item.label}" + (f" gold now {p.gold}" if item.category == "gold" else ""))
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
        if item.kind == "bomb":  # the merchant never runs out of these
            item = self._item("bomb")
        if not self._stash(p, item):
            self.tell(p, "Your pack is full.", GRAY)
            return 0
        if item.kind != "bomb":
            del m.stock[stock_id]
        p.gold -= item.price
        p.pack_dirty = True
        self.tell(p, f"You buy {self._a(item)} for {item.price}.", GOLD)
        self.note(p, f"bought {item.label} for {item.price} gold now {p.gold}")
        for q in self._living_on(p.depth):  # everyone at the shop sees it sell out
            if cheb(q, m) <= 1:
                self.outbox.append((q.id, self._shop_msg(m)))
        return TICKS_PER_TURN

    def _sell(self, p: Player, lvl: Level, slot: int) -> int:
        """For half what it's worth, and the merchant keeps it: nobody can buy it back."""
        m = lvl.merchant
        if m is None or cheb(p, m) > 1:
            self.tell(p, "There's nobody here to sell to.", GRAY)
            return 0
        if slot >= len(p.pack):
            return 0
        item = p.pack[slot]
        if not item.sellable:
            self.tell(p, f"The {m.name} won't buy {self._a(item)}.", GRAY)
            return 0
        price = item.sell_price
        if item.category == "ammo":  # a quiver goes all at once
            p.pack.remove(item)
            p.pack_dirty = True
            sold = item
        else:
            sold = self._take_one(p, item)
        p.gold += price
        self.tell(p, f"You sell {self._a(sold)} for {price}. It's gone for good.", GOLD)
        self.note(p, f"sold {sold.label} for {price} gold now {p.gold}")
        return TICKS_PER_TURN

    def _levitating(self, a) -> bool:
        return a.levitate_until > self.clock

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
        if item.category in ("ranged", "wand") and p.auto_attack:
            p.ranged = None if p.ranged is item else item
            p.pack_dirty = True
            if p.ranged is item:
                self.tell(p, f"You ready the {item.name}. Auto attack fires it at what's fighting you.", WHITE)
            else:
                self.tell(p, f"You put away the {item.name}.", WHITE)
            self.note(p, f"{'readied' if p.ranged is item else 'put away'} {item.name}")
            return TICKS_PER_TURN
        if item.category == "wand":
            return self._zap(p, item)
        if item.category == "bomb":
            return self._light_bomb(p, item)
        if item.category == "ranged":
            return self._shoot(p, item)
        if item.category == "ammo":
            self.tell(p, "Use a bow to fire these.", GRAY)
            return 0
        if item.category == "amulet":
            self.tell(p, "It's your way out. Carry it up the stairs on floor 1.", GRAY)
            return 0
        if item.category == "hook":
            self.tell(p, "It's the fisherman's. Walk into him to give it back.", GRAY)
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
        elif item.cure and p.toxin_until <= self.clock and p.venom_until <= self.clock:
            self.tell(p, "You aren't poisoned.", GRAY)
            return 0
        else:
            p.hp = min(p.max_hp, p.hp + item.heal)
            self.note(p, f"drank {item.name} hp {self._hp(p)}")
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
            if item.strength:
                p.strength += item.strength
                apply_gear(p)
            if item.cure:
                p.toxin_until = p.toxin_ticks = p.venom_until = p.venom_ticks = p.slow_until = 0
            self.tell(p, "You feel better." if item.heal else "You rise off the ground!" if item.levitate
                      else f"The world lurches, and you're on floor {p.depth}!" if item.teleport
                      else "Your feet feel strangely light." if item.waterwalk
                      else "Your feet stop feeling the heat." if item.lavawalk
                      else "You feel stronger!" if item.strength
                      else "The burning fades, and your limbs loosen." if item.cure
                      else "Everything around you slows down.", GOLD)
            self._take_one(p, item)
            return TICKS_PER_TURN
        apply_gear(p)
        p.pack_dirty = True
        equipped = item in (p.weapon, p.armor, p.cloak)
        self.tell(p, f"You {'equip' if equipped else 'remove'} the {item.name}.", WHITE)
        self.note(p, f"{'equipped' if equipped else 'removed'} {item.name}")
        return TICKS_PER_TURN

    def _light_bomb(self, p: Player, bomb: Item) -> int:
        """Set down where you stand. It's up to you to get clear."""
        lvl = self.levels[p.depth]
        self._take_one(p, bomb)
        lvl.bombs.append({"x": p.x, "y": p.y, "at": self.clock + self._seconds(BOMB_SECONDS), "by": p})
        self.tell(p, f"You light the {bomb.name} and set it down. Get clear!", ORANGE)
        self.note(p, f"lit a bomb at {p.x},{p.y}")
        self._narrate(lvl, [(p.x, p.y)], set(), lambda v: (f"{p.name} lights a bomb!", ORANGE), exclude=p)
        self.dirty = True
        return TICKS_PER_TURN

    def _quick_heal(self, p: Player) -> int:
        """Drinks the smallest healing potion that fills you up, or failing that, the biggest."""
        potions = [i for i in p.pack if i.heal]
        if not potions:
            self.tell(p, "You have no healing potions.", GRAY)
            return 0
        enough = [i for i in potions if p.hp + i.heal >= p.max_hp]
        item = min(enough, key=lambda i: i.heal) if enough else max(potions, key=lambda i: i.heal)
        return self._use(p, p.pack.index(item))

    @staticmethod
    def _sort_pack(p: Player) -> None:
        """What you're wearing first, then the things you reach for in a hurry. It takes no time."""
        def order(item: Item) -> tuple:
            worn = item in (p.weapon, p.armor, p.cloak, p.ranged)
            return (not worn, PACK_ORDER.index(item.category), -item.heal, item.name)
        p.pack.sort(key=order)
        p.pack_dirty = True

    def _teleport_floor(self, p: Player) -> None:
        """The potion: a random spot on a random other floor, from the first to the last."""
        old = self.levels[p.depth]
        fx = {"t": "fx", "kind": "blink", "cells": [(p.x, p.y)]}
        for v in self._living_on(p.depth):
            self.outbox.append((v.id, fx))
        if old.depth == LAST_FLOOR and self.necro_awake:
            p.chased = True
        depth = self.rng.choice([d for d in range(1, LAST_FLOOR + 1) if d != p.depth])
        self.note(p, f"teleported F{old.depth:02d}->F{depth:02d}")
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

    def bring(self, p: Player, to: Player) -> None:
        """Console: puts a player right beside another, on whatever floor that is."""
        self.levels[p.depth].remove(p)
        lvl = self.level(to.depth)
        lvl.place(p, *lvl.free_near(to.x, to.y))
        p.pending, p.hold, p.needs_level = None, None, True
        self.note(p, f"brought to {to.name} on F{to.depth:02d}")

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

    def _shoot(self, p: Player, weapon: Item, m: Monster | None = None) -> int:
        """A bow or boomerang. A sneak shot works like a sneak attack."""
        lvl = self.levels[p.depth]
        ammo = next((i for i in p.pack if i.category == "ammo"), None)
        if weapon.fires and ammo is None:
            self.tell(p, f"You have no {weapon.fires}s.", GRAY)
            return 0
        if weapon.back_at > self.clock:
            self.tell(p, f"Your {weapon.name} hasn't come back yet.", GRAY)
            return 0
        m = m or self._target(p, lvl, weapon.reach)
        if m is None:
            self.tell(p, "There's nothing in range to aim at.", GRAY)
            return 0
        if weapon.fires:
            self._take_one(p, ammo)
        cells = line_between((p.x, p.y), (m.x, m.y))
        if not weapon.fires:  # out and back again, and it can't be thrown until it's back
            weapon.back_at = self.clock + self._seconds(max(BOOMERANG_WAIT, 2 * len(cells) * BOOMERANG_TILE_SECONDS))
        shot = {"t": "fx", "kind": weapon.kind, "cells": cells, "from": [p.x, p.y]}
        p.stealth = 0.0
        self._note_fight(p, m)
        sneak = m.state != "hunting"
        where = [(p.x, p.y), (m.x, m.y)]
        if sneak or self.rng.random() * 100 < p.accuracy * DEFENSE_FACTOR ** m.defense:
            dmg = self.rng.randint(*weapon.damage) * (SNEAK_DAMAGE if sneak else 1)
            m.hp -= dmg
            self.note(p, f"shot {self._tag(m)} with {weapon.name} -{dmg}{' sneak' if sneak else ''} hp {self._hp(m)}")
            self._narrate(lvl, where, {p}, lambda v: (
                f"{self._n(p, v, True)} {self._verb(p, v, ('hits', 'hit'))} {self._n(m, v)}.", WHITE))
        else:
            self.note(p, f"shot {self._tag(m)} with {weapon.name}: missed")
            self._narrate(lvl, where, {p}, lambda v: (
                f"{self._n(p, v, True)} {self._verb(p, v, ('misses', 'miss'))} {self._n(m, v)}.", GRAY))
        if m.hp <= 0:  # so it can still be seen until the arrow or boomerang gets there
            shot["fell"] = {"g": m.glyph, "c": list(m.color)}
        for v in self._living_on(p.depth):
            self.outbox.append((v.id, shot))
        if m.hp <= 0:
            self._kill(m, p)
        else:
            self._hunt(m, p)
        return TICKS_PER_TURN

    def _zap(self, p: Player, wand: Item, m: Monster | None = None) -> int:
        """Fires at a monster in sight. After its last use the wand breaks."""
        lvl = self.levels[p.depth]
        m = m or self._target(p, lvl, STAFF_RANGE if wand.lightning else WAND_RANGE)
        if m is None:
            self.tell(p, "There's nothing in range to aim at.", GRAY)
            return 0
        kind = "lightning" if wand.lightning else "frost" if wand.freeze else "fire"
        bolt = {"t": "fx", "kind": kind, "cells": line_between((p.x, p.y), (m.x, m.y))}
        for v in self._living_on(p.depth):
            self.outbox.append((v.id, bolt))
        p.stealth = 0.0
        self._note_fight(p, m)
        if wand.lightning:
            dmg = self.rng.randint(*LIGHTNING_DAMAGE)
            m.hp -= dmg
            self.note(p, f"zapped {self._tag(m)} with {wand.name} -{dmg} hp {self._hp(m)}")
            self._narrate(lvl, [(m.x, m.y)], {p}, lambda v: (
                f"Lightning from {self._n(p, v)} strikes {self._n(m, v)}!", VIOLET))
            if m.hp <= 0:
                self._kill(m, p)
            else:
                self._hunt(m, p)
        elif wand.freeze:  # it never knew what hit it, so nothing wakes
            m.frozen_until = self.clock + int(wand.freeze * TICKS_PER_SECOND)
            self.note(p, f"zapped {self._tag(m)} with {wand.name}: frozen {wand.freeze:.0f}s")
            self._narrate(lvl, [(m.x, m.y)], {p}, lambda v: (
                f"{self._n(p, v, True)} {self._verb(p, v, ('freezes', 'freeze'))} {self._n(m, v)} solid.", WHITE))
        else:
            dmg = self.rng.randint(*WAND_DAMAGE)
            m.hp -= dmg
            m.burning, m.burned_by = WAND_BURN_TURNS, p
            self.note(p, f"zapped {self._tag(m)} with {wand.name} -{dmg} burning hp {self._hp(m)}")
            self._narrate(lvl, [(m.x, m.y)], {p}, lambda v: (
                f"{self._n(p, v, True)} {self._verb(p, v, ('burns', 'burn'))} {self._n(m, v)}.", ORANGE))
            fx, fy = m.x, m.y
            if m.hp <= 0:
                self._kill(m, p)
            else:
                self._hunt(m, p)
            self._start_fire(lvl, fx, fy, p)
        if wand.unlimited:
            return TICKS_PER_TURN
        wand.charges -= 1
        p.pack_dirty = True
        if wand.charges <= 0:
            self._take_one(p, wand)
            self.tell(p, f"The {wand.name} crumbles to ash.", ORANGE)
            self.note(p, f"{wand.name} broke")
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
        if item is p.ranged:
            p.ranged = None
        apply_gear(p)
        return item

    def _drop(self, p: Player, lvl: Level, slot: int) -> int:
        if slot >= len(p.pack):
            return 0
        item = self._take_one(p, p.pack[slot])
        lvl.items[lvl.free_item_spot(p.x, p.y)] = item
        self.tell(p, f"You drop {self._a(item)}.", WHITE)
        self.note(p, f"dropped {item.label}")
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
        self.note(p, f"dropped {item.label} gold now {p.gold}")
        self._narrate(lvl, [(p.x, p.y)], set(), lambda v: (f"{p.name} drops {item.label}.", GRAY), exclude=p)
        return TICKS_PER_TURN

    def _scatter_belongings(self, p: Player, lvl: Level) -> None:
        """A fallen player's gear lands around them for the party to collect."""
        loot = p.pack + ([self._gold(p.gold)] if p.gold else [])
        for item in loot:
            lvl.items[lvl.free_item_spot(p.x, p.y)] = item
        p.pack, p.gold, p.weapon, p.armor, p.cloak, p.pack_dirty = [], 0, None, None, None, True
        p.ranged = None
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
            self.note(p, "chased by the rising dead")
        verb = "descends" if step > 0 else "climbs"
        self._narrate(old, [(p.x, p.y)], set(), lambda v: (f"{p.name} {verb} the stairs.", GRAY), exclude=p)
        old.remove(p)
        lvl = self.level(new_depth)
        lvl.place(p, *lvl.free_near(*(lvl.up_front if step > 0 else lvl.down_front)))
        p.needs_level = True
        self.tell(p, f"You {'descend' if step > 0 else 'ascend'} to depth {new_depth}.", WHITE)
        self.note(p, f"stairs F{old.depth:02d}->F{new_depth:02d} hp {self._hp(p)}")
        self._hear_merchant(p, lvl)
        return p.move_cost

    def _win(self, p: Player) -> None:
        """The whole party wins, and a new dungeon starts once they've seen the scores."""
        if self.victory:
            return
        self.victory = p.name
        self.reset_at = time.monotonic() + VICTORY_SECONDS
        self.broadcast(f"{p.name} carries the Amulet out of the dungeon. The party wins!", GOLD)
        self.note(p, "WON: escaped with the Amulet")
        for q in sorted(self.players.values(), key=self.score_of, reverse=True):
            self.broadcast(f"{q.name}: {self.score_of(q)} points, {q.kills} kills", GOLD)

    def _regen(self, p: Player, cost: int) -> None:
        if p.hp >= p.max_hp:
            p.regen_acc = 0
            return
        if p.toxin_until > self.clock or p.venom_until > self.clock:  # poison stops you healing
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
            dfn.provoked = True
            if self._levitating(dfn):
                self.note(att, f"can't reach {self._tag(dfn)}")
                self._narrate(lvl, [(att.x, att.y), (dfn.x, dfn.y)], {att}, lambda v: (
                    f"{self._n(att, v, True)} can't reach {self._n(dfn, v)}.", GRAY))
                return
        elif dfn.is_player:
            self._note_fight(dfn, att)
            if self._levitating(dfn) or dfn.god:
                self.note(att, f"can't reach {self._tag(dfn)}")
                self._narrate(lvl, [(att.x, att.y), (dfn.x, dfn.y)], {dfn}, lambda v: (
                    f"{self._n(att, v, True)} can't reach {self._n(dfn, v)}.", GRAY))
                return
        sneak = isinstance(dfn, Monster) and dfn.state != "hunting"
        crit = sneak and hidden and dfn.state == "sleeping"
        prob = 100.0 if sneak else att.accuracy * DEFENSE_FACTOR ** dfn.defense
        where = [(att.x, att.y), (dfn.x, dfn.y)]
        if self.rng.random() * 100 < prob:
            dmg = self.rng.randint(*att.damage) * (CRIT_DAMAGE if crit else SNEAK_DAMAGE if sneak else 1)
            if att.is_player and att.weapon is not None and att.weapon.enhanced and dfn.kind in UNDEAD:
                dmg = int(dmg * UNDEAD_BONUS)
            dfn.hp -= dmg
            kind = " crit" if crit else " sneak" if sneak else ""
            self.note(att, f"hit {self._tag(dfn)} -{dmg}{kind} hp {self._hp(dfn)}")

            def hit(v):
                tail = " with a critical hit!" if crit else " by surprise!" if sneak else "."
                color = RED if v is dfn else (WHITE if v is att else GRAY)
                return f"{self._n(att, v, True)} {self._verb(att, v, att.verbs)} {self._n(dfn, v)}{tail}", color
            self._narrate(lvl, where, {att, dfn}, hit)
            if att.is_player and att.weapon is not None:
                self._weapon_magic(att, dfn, dmg)
            if isinstance(att, Monster) and att.kind == "slime" and dfn.hp > 0:
                self._slimed(dfn)
            if isinstance(att, Monster) and att.kind in SPIDERS and dfn.hp > 0:
                self._envenom(dfn)
        else:
            self.note(att, f"missed {self._tag(dfn)} ({prob:.0f}% to hit)")
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
            self.note(p, f"froze {self._tag(m)}")
        if "drain" in spells:
            p.hp = min(p.max_hp, p.hp + max(1, damage // WEAPON_DRAIN))
            self.note(p, f"drained {self._tag(m)} hp {self._hp(p)}")

    @staticmethod
    def _note_fight(p: Player, m: Monster) -> None:
        if m.kind and (not p.hardest or danger(m.kind) > danger(p.hardest)):
            p.hardest = m.kind

    def _kill(self, victim, killer, cause: str = "") -> None:
        lvl = self.levels[victim.depth]
        where = [(victim.x, victim.y)]
        if isinstance(victim, Monster):
            self.note(victim, f"killed by {self._tag(killer)}" if killer is not None else "died")
            if victim is self.necromancer:
                self.necromancer, self.necro_awake = None, False
                for p in self.players.values():
                    p.chased = False
                self.broadcast(f"The {victim.name} is destroyed, and the dead lie still!", GOLD)
            self._narrate(lvl, where, {killer, victim}, lambda v: (
                (f"{self._n(killer, v, True)} {self._verb(killer, v, ('kills', 'kill'))} {self._n(victim, v)}."
                 if killer is not None else f"{self._n(victim, v, True)} dies."),
                WHITE if v is killer else GRAY))
            lvl.remove(victim)
            lvl.monsters.remove(victim)
            self._stain(lvl, victim)
            if victim.kind == "cult_leader":
                lvl.items[lvl.free_item_spot(victim.x, victim.y)] = seasons.dress_item(make_wand(), self.season)
                self._narrate(lvl, where, {killer}, lambda v: (f"The {victim.name} drops a wand!", GOLD))
                self.note(victim, "dropped a wand")
            if victim.kind == "monkey":
                victim.stolen_gold += self.rng.randint(*MONKEY_DEATH_GOLD)
                self._drop_stolen(victim, lvl)
                lvl.items[lvl.free_item_spot(victim.x, victim.y)] = self._item("hook")
                self._narrate(lvl, where, {killer}, lambda v: (f"The {victim.name} drops a fisherman's hook!", GOLD))
            if victim.kind == "cult_mage":
                lvl.items[lvl.free_item_spot(victim.x, victim.y)] = seasons.dress_item(make_staff(), self.season)
                self._narrate(lvl, where, {killer}, lambda v: (f"The {victim.name} drops its staff of lightning!", GOLD))
                self.note(victim, "dropped a staff of lightning")
            if killer is not None and killer.is_player:
                killer.kills += 1
                killer.kill_tally[victim.name] = killer.kill_tally.get(victim.name, 0) + 1
            return
        revivable = self.revive_seconds is not None
        self._narrate(lvl, where, {victim}, lambda v: (
            ("You are down..." if revivable else "You die...") if v is victim
            else f"{victim.name} {'is down' if revivable else 'dies'}!", RED))
        victim.alive, victim.hp, victim.pending, victim.hold = False, 0, None, None
        victim.levitate_until = victim.waterwalk_until = victim.lavawalk_until = victim.reflect_until = 0
        victim.toxin_until = victim.slow_until = victim.webbed_until = victim.venom_until = 0
        if not lvl.mainland[victim.x, victim.y]:  # over water or on an island: land where the party can reach
            lvl.move(victim, *lvl.free_near(victim.x, victim.y))
        victim.final_gold = victim.gold
        victim.death = cause or (f"Killed by {_article(killer.name)} on depth {victim.depth}." if killer else "Died.")
        gear = ", ".join(i.name for i in (victim.weapon, victim.armor, victim.cloak) if i is not None) or "no gear"
        self.note(victim, f"{'DOWN' if revivable else 'DIED'}: {victim.death} {victim.kills} kills, "
                          f"{victim.gold} gold, wearing {gear}")
        lvl.remove(victim)
        if revivable:  # they keep their gear; it comes back with them
            victim.downed, victim.revive_ticks = True, 0
            lvl.downed.append(victim)
            if any(p.alive for p in self.players.values()):
                for p in self.players.values():
                    if p is not victim:
                        self.tell(p, f"{victim.name} is down on floor {victim.depth}! Stand by the {BONES_GLYPH} "
                                     f"for {self.revive_seconds:.0f} seconds to revive.", ORANGE)
        else:
            self._scatter_belongings(victim, lvl)
        self._check_all_dead()

    def _stain(self, lvl: Level, m: Monster) -> None:
        """Blood where it fell, or goo, or bones, by what it was. Sometimes it splashes a tile over."""
        stain = STAINS.get(m.kind, "blood")
        if stain is None:
            return
        cells = [(m.x, m.y)]
        splash = [(m.x + dx, m.y + dy) for dx, dy in DIRS8 if lvl.walkable[m.x + dx, m.y + dy]]
        if splash and self.rng.random() < 0.5:
            cells.append(self.rng.choice(splash))
        for x, y in [c for c in cells if lvl.tiles[c] in BURNABLE]:  # water washes it away; doors stay clean
            lvl.stains[(x, y)] = stain
            lvl.new_stains.append([x, y, stain])

    @staticmethod
    def carried_gold(p: Player) -> int:
        return p.gold if p.final_gold is None else p.final_gold

    def score_of(self, p: Player) -> int:
        """Gold carried times kills, divided by moves, and doubled for a win."""
        points = self.carried_gold(p) * p.kills * SCORE_SCALE // max(1, p.turns)
        return points * 2 if self.victory else points

    def _check_all_dead(self) -> None:
        if self.players and not any(p.alive for p in self.players.values()) and self.reset_at is None:
            self.reset_at = time.monotonic() + RESET_DELAY
            self.broadcast("The whole party has fallen. A new dungeon takes shape...", RED)
            for p in sorted(self.players.values(), key=self.score_of, reverse=True):
                self.broadcast(f"{p.name}: {self.score_of(p)} points, {p.kills} kills", GOLD)
                self.note(p, f"RUN OVER: party fell, {self.score_of(p)} points, {p.kills} kills")

    def reset_run(self) -> None:
        self.seed = random.randrange(1, 2 ** 31)
        self.rng = random.Random(self.seed * 7919 + 1)
        self.locked_rooms = plan_locked_rooms(self.seed)
        self.levels, self.offline, self.maps = {}, {}, {}
        self.necromancer, self.necro_awake, self.tide_at, self.victory = None, False, 0, ""
        self.cloaks, self.cloak_floors = 0, []
        for _ in self.players:
            self._promise_cloak(1)
        self.season = self.season_fn()
        self.run += 1
        self.run_start = self.clock
        self.reset_at = None
        self.ready = set()
        lvl = self.level(1)
        for p in self.players.values():
            reset_player(p)
            lvl.place(p, *lvl.free_near(*lvl.up_front))
            p.needs_level = True
        self.dirty = True
        self.ledger.append(self.ledger_head())
        self.broadcast(f"Run {self.run} begins. Good luck!", GOLD)

    # ---------------------------------------------------------------- AI

    def _hunt(self, m: Monster, target) -> None:
        m.state, m.target_id, m.last_seen = "hunting", target.id, (target.x, target.y)
        if m is self.necromancer and not self.necro_awake:
            self.necro_awake = True
            self.broadcast(f"The {m.name} has woken!", RED)
            self.note(m, f"woke, hunting {self._tag(target)}")
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
            burn = self.rng.randint(*WAND_BURN)
            m.hp -= burn
            self.note(m, f"burned -{burn} hp {self._hp(m)}")
            if m.hp <= 0:
                self._kill(m, m.burned_by)
                return
        self._back_on_land(m, self.levels[m.depth])
        cost = max(1, self._monster_turn(m, self.levels[m.depth]))
        if m.haste_until > self.clock:
            cost = max(1, cost // 2)
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
            self.note(m, f"released gas over {len(room)} tiles")
        return TICKS_PER_TURN

    def _haunt(self, m: Monster, lvl: Level) -> int:
        """A ghost always knows where you are, and walls are nothing to it."""
        prey = self._living_on(m.depth)
        if not prey:
            return TICKS_PER_TURN
        t = min(prey, key=lambda p: (cheb(m, p), p.id))
        if cheb(m, t) == 1:
            self._attack(m, t)
            return m.attack_cost * MONSTER_SWING
        dx, dy = (t.x > m.x) - (t.x < m.x), (t.y > m.y) - (t.y < m.y)
        for sx, sy in ((dx, dy), (dx, 0), (0, dy)):
            n = (m.x + sx, m.y + sy)
            if (sx or sy) and 0 < n[0] < MAP_W - 1 and 0 < n[1] < MAP_H - 1 and n not in lvl.occupant \
                    and lvl.tiles[n] not in (STAIRS_DOWN, STAIRS_UP):
                lvl.move(m, *n)
                return m.move_cost
        return TICKS_PER_TURN

    def _ground(self, m: Monster, lvl: Level) -> np.ndarray:
        """Where a monster can walk: the floor, and while a potion lasts, the water, lava or chasms it lets it cross."""
        extra = []
        if m.levitate_until > self.clock:
            extra.append(lvl.hover)
        if m.waterwalk_until > self.clock:
            extra.append(lvl.tiles == DEEP)
        if m.lavawalk_until > self.clock:
            extra.append(lvl.tiles == LAVA)
        if not extra:
            return lvl.walkable
        ground = lvl.walkable.copy()
        for more in extra:
            ground |= more
        return ground

    def _distances(self, m: Monster, lvl: Level, x: int, y: int) -> np.ndarray:
        """How far every tile is from (x, y) for this monster. Only potions make it differ from the shared map."""
        ground = self._ground(m, lvl)
        return lvl.distances_to(x, y) if ground is lvl.walkable else algo.dijkstra(ground, [(x, y)])

    def _back_on_land(self, m: Monster, lvl: Level) -> None:
        """A potion wore off over water, lava or a chasm: it scrambles to the nearest floor."""
        if (m.levitate_until or m.waterwalk_until or m.lavawalk_until) and not self._ground(m, lvl)[m.x, m.y]:
            start = (m.x, m.y)
            lvl.move(m, *lvl.nearest_floor(m.x, m.y, lvl.occupant))
            self.note(m, "scrambled back to solid ground")
            self._narrate(lvl, [start, (m.x, m.y)], set(), lambda v: (
                f"The {m.name} scrambles back onto solid ground.", GRAY))

    def _step_away(self, m: Monster, lvl: Level, target: Player) -> int:
        """One step further from someone on foot, if there's anywhere to go."""
        walk = self._distances(m, lvl, target.x, target.y)
        ground = self._ground(m, lvl)
        best, best_d = None, walk[m.x, m.y]
        dirs = DIRS8[:]
        self.rng.shuffle(dirs)
        for dx, dy in dirs:
            n = (m.x + dx, m.y + dy)
            if (lvl.in_bounds(*n) and ground[n] and n not in lvl.occupant and best_d < walk[n] < algo.INF
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
        arrow = {"t": "fx", "kind": "bow", "cells": line_between((m.x, m.y), (target.x, target.y)), "from": [m.x, m.y]}
        for v in self._living_on(m.depth):
            self.outbox.append((v.id, arrow))
        self._note_fight(target, m)
        where = [(m.x, m.y), (target.x, target.y)]
        if self.rng.random() * 100 >= m.accuracy * DEFENSE_FACTOR ** target.defense:
            self.note(m, f"shot {self._tag(target)}: missed")
            self._narrate(lvl, where, {target}, lambda v: (f"The {m.name}'s arrow misses {self._n(target, v)}.", GRAY))
            return m.attack_cost
        self._narrate(lvl, where, {target}, lambda v: (f"The {m.name}'s arrow hits {self._n(target, v)}!", RED))
        if not target.god:
            dmg = self.rng.randint(*m.damage)
            target.hp -= dmg
            self.note(m, f"shot {self._tag(target)} -{dmg} hp {self._hp(target)}")
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
                self.note(m, f"fire reflected by {self._tag(p)} -{damage} hp {self._hp(m)}")
                self._narrate(lvl, [(p.x, p.y)], {p}, lambda v: (f"The flames rebound off {self._n(p, v)}!", TEAL))
                if m.hp <= 0:
                    self._kill(m, p)
                    return
            elif not p.god:
                p.hp -= damage
                self.note(m, f"burned {self._tag(p)} -{damage} hp {self._hp(p)}")
                self.tell(p, "The flames wash over you!", RED)
                if p.hp <= 0:
                    self._kill(p, m)

    def _summon(self, m: Monster, lvl: Level, target: Player) -> None:
        m.ready_at = self.clock + int(SUMMON_SECONDS * TICKS_PER_SECOND)
        room = TIDE_MAX - sum(z.kind == "zombie" for z in lvl.monsters)
        for _ in range(min(room, self.rng.randint(*SUMMON_SIZE))):
            self._raise_zombie(lvl, lvl.free_near(m.x, m.y), target)
        self._narrate(lvl, [(m.x, m.y)], set(), lambda v: (f"The {m.name} raises the dead!", RED))
        self.note(m, "raised the dead")

    def _bolt_at(self, m: Monster, lvl: Level, target: Player, kind: str, damage: tuple, what: str) -> bool:
        """Magic thrown at a player: lightning or fire. A ward stops it dead. Whether it got through."""
        cells = line_between((m.x, m.y), (target.x, target.y))
        for v in self._living_on(m.depth):
            self.outbox.append((v.id, {"t": "fx", "kind": kind, "cells": cells, "from": [m.x, m.y]}))
        self._note_fight(target, m)
        where = [(m.x, m.y), (target.x, target.y)]
        if self._reflecting(target):
            self.note(m, f"{what} warded off by {self._tag(target)}")
            self._narrate(lvl, where, {target}, lambda v: (
                f"The {m.name}'s {what} breaks against {self._n(target, v)}'s ward." if v is not target
                else f"The {m.name}'s {what} breaks harmlessly against your ward.", TEAL))
            return False
        self._narrate(lvl, where, {target}, lambda v: (f"The {m.name}'s {what} hits {self._n(target, v)}!", RED))
        if not target.god:
            dmg = self.rng.randint(*damage)
            target.hp -= dmg
            self.note(m, f"{what} hit {self._tag(target)} -{dmg} hp {self._hp(target)}")
            if target.hp <= 0:
                self._kill(target, m)
        return True

    def _clear_shot(self, lvl: Level, a, b) -> bool:
        """Nothing solid between two places, so a bolt or a spear gets through."""
        clear = lvl.transparency()
        return all(clear[c] or c == (b.x, b.y) for c in line_between((a.x, a.y), (b.x, b.y)))

    def _mage(self, m: Monster, lvl: Level, t: Player) -> int:
        """Rises every so often and drifts over to hang near its prey, out of reach of blades,
        and throws lightning whenever it's ready."""
        if self.clock >= m.float_next:
            m.float_next = self.clock + self._seconds(MAGE_CYCLE)
            m.float_until = self.clock + self._seconds(MAGE_FLOAT)
            sight = self.fov(t)
            near = [c for c in lvl.land_cells if c not in lvl.occupant and sight[c]
                    and 2 <= max(abs(c[0] - t.x), abs(c[1] - t.y)) <= 4]
            above = [c for c in near if c[1] < t.y] or near
            if above:
                spot = min(above, key=lambda c: (abs(c[0] - t.x) + (t.y - c[1] - 3) ** 2, c))
                blink = {"t": "fx", "kind": "blink", "cells": [(m.x, m.y), spot]}
                for v in self._living_on(m.depth):
                    self.outbox.append((v.id, blink))
                lvl.move(m, *spot)
            self._narrate(lvl, [(m.x, m.y)], set(), lambda v: (f"The {m.name} rises into the air, glowing violet!", VIOLET))
            self.note(m, "rose into the air")
        if self.clock >= m.ready_at and cheb(m, t) <= MAGE_RANGE and self._clear_shot(lvl, m, t):
            m.ready_at = self.clock + self._seconds(MAGE_BOLT)
            self._bolt_at(m, lvl, t, "lightning", LIGHTNING_DAMAGE, "lightning")
            return m.attack_cost
        if self._floating(m):
            return TICKS_PER_TURN  # hangs where it is
        if cheb(m, t) == 1 and not lvl.diagonal_blocked(m.x, m.y, t.x, t.y):
            self._attack(m, t)
            return m.attack_cost * MONSTER_SWING
        return self._step_toward(m, lvl, t.x, t.y) or TICKS_PER_TURN

    def _cult_leader(self, m: Monster, lvl: Level, t: Player) -> int:
        """Backs off out of reach, throws three bolts from its wand of fire one after another, the
        last setting the ground around you alight, then rests a while. Cornered, it fights."""
        away = cheb(m, t)
        if away < LEADER_RANGE[0]:
            cost = self._step_away(m, lvl, t)
            if cost:
                return cost
            if away == 1 and not lvl.diagonal_blocked(m.x, m.y, t.x, t.y):
                self._attack(m, t)
                return m.attack_cost * MONSTER_SWING
        if self.clock < m.ready_at:
            return TICKS_PER_TURN  # resting between volleys
        if away > LEADER_RANGE[1] or not self._clear_shot(lvl, m, t):
            return self._step_toward(m, lvl, t.x, t.y) or TICKS_PER_TURN
        m.volley += 1
        hit = self._bolt_at(m, lvl, t, "fire", LEADER_FIRE_DAMAGE, "fire bolt")
        if m.volley >= LEADER_VOLLEY:
            m.volley, m.ready_at = 0, self.clock + self._seconds(LEADER_REST)
            if hit and t.alive:
                self._start_fire(lvl, t.x, t.y, None)
        return m.attack_cost

    def _spider_queen(self, m: Monster, lvl: Level, t: Player) -> int:
        """Bites anyone close. Anyone who runs more than WEB_SPIT_RANGE tiles off, she spits web
        at, which slows them even more than her webs do, and leaves a web where they stand."""
        away = cheb(m, t)
        if WEB_SPIT_RANGE < away <= WEB_SPIT_REACH and self.clock >= m.ready_at and self._clear_shot(lvl, m, t):
            m.ready_at = self.clock + self._seconds(WEB_SPIT_SECONDS)
            cells = line_between((m.x, m.y), (t.x, t.y))
            for v in self._living_on(m.depth):
                self.outbox.append((v.id, {"t": "fx", "kind": "web", "cells": cells, "from": [m.x, m.y]}))
            self._note_fight(t, m)
            where = [(m.x, m.y), (t.x, t.y)]
            if self._levitating(t) or self.rng.random() * 100 >= m.accuracy * DEFENSE_FACTOR ** t.defense:
                self._narrate(lvl, where, {t}, lambda v: (f"The {m.name}'s web misses {self._n(t, v)}.", GRAY))
                return m.attack_cost
            self._narrate(lvl, where, {t}, lambda v: (
                f"The {m.name} spits web over {self._n(t, v)}!", ORANGE))
            self.note(m, f"webbed {self._tag(t)}")
            if not t.god:
                t.webbed_until = self.clock + self._seconds(WEB_SECONDS)
            if lvl.tiles[t.x, t.y] in BURNABLE and (t.x, t.y) not in lvl.webs:
                lvl.webs.add((t.x, t.y))
                lvl.webs_changed = True
            return m.attack_cost
        if away == 1 and not lvl.diagonal_blocked(m.x, m.y, t.x, t.y):
            self._attack(m, t)
            return m.attack_cost * MONSTER_SWING
        return self._step_toward(m, lvl, t.x, t.y) or TICKS_PER_TURN

    def _spider(self, m: Monster, lvl: Level, t: Player) -> int:
        """Leaps in from a few tiles off and bites as it lands, then backs off to do it again."""
        if m.volley:  # backing off after a bite
            m.volley -= 1
            cost = self._step_away(m, lvl, t)
            if cost:
                return cost
            m.volley = 0
        away = cheb(m, t)
        if away == 1 and not lvl.diagonal_blocked(m.x, m.y, t.x, t.y):
            self._attack(m, t)
            m.volley = LEAP_RETREAT
            return m.attack_cost * MONSTER_SWING
        if 2 <= away <= LEAP_RANGE and self.clock >= m.ready_at and self._clear_shot(lvl, m, t):
            path = line_between((m.x, m.y), (t.x, t.y))[:-1]
            spot = path[-1] if path else None
            if (spot is not None and lvl.walkable[spot] and spot not in lvl.occupant
                    and not lvl.diagonal_blocked(*spot, t.x, t.y)):
                m.ready_at = self.clock + self._seconds(LEAP_SECONDS)
                for v in self._living_on(m.depth):
                    self.outbox.append((v.id, {"t": "fx", "kind": "leap", "cells": [(m.x, m.y), *path]}))
                lvl.move(m, *spot)
                self._narrate(lvl, [spot], {t}, lambda v: (f"The {m.name} leaps at {self._n(t, v)}!", ORANGE))
                self._attack(m, t)
                m.volley = LEAP_RETREAT
                return m.attack_cost * MONSTER_SWING
        return self._step_toward(m, lvl, t.x, t.y) or TICKS_PER_TURN

    def _scout(self, m: Monster, lvl: Level, t: Player) -> int:
        """A kobold scout keeps its distance and throws fire when it's ready."""
        away = cheb(m, t)
        if away < SCOUT_RANGE[0]:
            cost = self._step_away(m, lvl, t)
            if cost:
                return cost
        elif away > SCOUT_RANGE[1]:
            return self._step_toward(m, lvl, t.x, t.y) or TICKS_PER_TURN
        if self.clock < m.ready_at or not self._clear_shot(lvl, m, t):
            if away == 1 and not lvl.diagonal_blocked(m.x, m.y, t.x, t.y):
                self._attack(m, t)
                return m.attack_cost * MONSTER_SWING
            return TICKS_PER_TURN
        m.ready_at = self.clock + self._seconds(SCOUT_RELOAD)
        self._bolt_at(m, lvl, t, "fireball", FIREBALL_DAMAGE, "fireball")  # thrown, so it flies across
        return m.attack_cost

    def _spearman(self, m: Monster, lvl: Level, t: Player) -> int:
        """A kobold leader likes a tile between it and you, and its spear reaches across it. After
        SPEAR_THRUSTS thrusts it's winded, and backs off for SPEAR_REST seconds before coming again."""
        away = cheb(m, t)
        if self.clock < m.rest_until:
            if away < SPEAR_REST_DISTANCE:
                cost = self._step_away(m, lvl, t)
                if cost:
                    return cost
            if away == 1 and not lvl.diagonal_blocked(m.x, m.y, t.x, t.y):  # cornered: it fights
                return self._thrust(m, lvl, t)
            return TICKS_PER_TURN
        if away == 1:
            cost = self._step_away(m, lvl, t)
            if cost:
                return cost
            if not lvl.diagonal_blocked(m.x, m.y, t.x, t.y):
                return self._thrust(m, lvl, t)
        if away == 2 and self._clear_shot(lvl, m, t):
            return self._thrust(m, lvl, t)
        return self._step_toward(m, lvl, t.x, t.y) or TICKS_PER_TURN

    def _thrust(self, m: Monster, lvl: Level, t: Player) -> int:
        """One jab of the spear, shown reaching across the tile between, and counted toward tiring."""
        cells = line_between((m.x, m.y), (t.x, t.y))
        for v in self._living_on(m.depth):
            self.outbox.append((v.id, {"t": "fx", "kind": "spear", "cells": cells, "from": [m.x, m.y]}))
        self._attack(m, t)
        m.thrusts += 1
        if m.thrusts >= SPEAR_THRUSTS and m.hp > 0:
            m.thrusts = 0
            m.rest_until = self.clock + self._seconds(SPEAR_REST)
            self.note(m, "winded, backing off")
            self._narrate(lvl, [(m.x, m.y)], set(), lambda v: (f"The {m.name} is winded and backs off.", GRAY))
        return m.attack_cost * MONSTER_SWING

    def _rock(self, m: Monster, lvl: Level, t: Player) -> int:
        cells = line_between((m.x, m.y), (t.x, t.y))
        for v in self._living_on(m.depth):
            self.outbox.append((v.id, {"t": "fx", "kind": "rock", "cells": cells, "from": [m.x, m.y]}))
        self._note_fight(t, m)
        where = [(m.x, m.y), (t.x, t.y)]
        if self.rng.random() * 100 >= m.accuracy * DEFENSE_FACTOR ** t.defense or self._levitating(t):
            self.note(m, f"threw a rock at {self._tag(t)}: missed")
            self._narrate(lvl, where, {t}, lambda v: (f"The {m.name}'s rock misses {self._n(t, v)}.", GRAY))
            return m.attack_cost
        self._narrate(lvl, where, {t}, lambda v: (f"The {m.name} throws a rock at {self._n(t, v)}!", RED))
        if not t.god:
            dmg = self.rng.randint(*ROCK_DAMAGE)
            t.hp -= dmg
            self.note(m, f"rock hit {self._tag(t)} -{dmg} hp {self._hp(t)}")
            if t.hp <= 0:
                self._kill(t, m)
        return m.attack_cost

    def _kobold(self, m: Monster, lvl: Level, t: Player) -> int | None:
        """A kobold keeps its distance and throws a few rocks before it closes in. After that a hurt
        one sometimes throws another, and one with nobody around runs. None means it fights as usual."""
        away = cheb(m, t)
        if m.rocks is None:
            m.rocks = self.rng.randint(*KOBOLD_ROCKS)
        if m.rocks > 0:
            if away == 1:  # backs off to throw; cornered, it fights
                cost = self._step_away(m, lvl, t)
                if cost:
                    return cost
            elif away <= KOBOLD_ROCK_RANGE and self._clear_shot(lvl, m, t):
                m.rocks -= 1
                return self._rock(m, lvl, t)
        if (m.hp < m.max_hp * FLEE_HEALTH and 2 <= away <= KOBOLD_ROCK_RANGE and self._clear_shot(lvl, m, t)
                and self.rng.random() < KOBOLD_ROCK_CHANCE):
            return self._rock(m, lvl, t)
        friends = any(o is not m and cheb(o, m) <= KOBOLD_ALONE for o in lvl.monsters)
        if not friends:
            return self._step_away(m, lvl, t) or None
        return None

    def _wolf_pack(self, m: Monster, lvl: Level) -> list[Monster]:
        """The living wolves of its pack, itself included. A wolf on its own is a pack of one."""
        head = m.leader or m
        return [o for o in lvl.monsters if o.kind == "wolf" and (o is head or o.leader is head)]

    def _wolf(self, m: Monster, lvl: Level, t: Player) -> int | None:
        """A wolf badly hurt, or in a pack taking a beating, may lose its nerve and run. It rolls
        once for each; one that runs keeps running. None means it fights as usual."""
        reasons = []
        if m.hp < m.max_hp * WOLF_FLEE_HEALTH:
            reasons.append("hurt")
        pack = self._wolf_pack(m, lvl)
        if sum(o.hp < o.max_hp * WOLF_PACK_HURT for o in pack) > len(pack) * WOLF_PACK_SHARE:
            reasons.append("pack")
        for reason in reasons:
            if m.fleeing or reason in m.nerve_tested:
                continue
            m.nerve_tested += (reason,)
            if self.rng.random() < WOLF_FLEE_CHANCE:
                m.fleeing = True
                self.note(m, f"lost its nerve ({reason}) and fled")
                self._narrate(lvl, [(m.x, m.y)], set(), lambda v: (f"The {m.name} turns tail and runs!", GRAY))
        if m.fleeing:
            return self._step_away(m, lvl, t) or None  # cornered, it fights
        return None

    def _monkey(self, m: Monster, lvl: Level, t: Player) -> int | None:
        """A monkey leaves you be unless you attack it. It comes to rob you, then runs until it's more
        than MONKEY_FLEE tiles away, and may drink a potion it took. Attacked, it fights back, and badly
        hurt it may run instead. None means it fights."""
        if m.drink_next:
            return self._monkey_drinks(m, lvl)
        if m.provoked or m.hp < m.max_hp:  # whatever hurt it, it's angry now
            m.provoked = True
            if m.hp < m.max_hp * MONKEY_FLEE_HEALTH and "hurt" not in m.nerve_tested:
                m.nerve_tested += ("hurt",)
                if self.rng.random() < MONKEY_FLEE_CHANCE:
                    m.fleeing = True
                    self.note(m, "lost its nerve (hurt) and fled")
                    self._narrate(lvl, [(m.x, m.y)], set(), lambda v: (f"The {m.name} shrieks and flees!", GRAY))
                    self._drop_stolen(m, lvl)
            if not m.fleeing:
                return None
        if m.robbed or m.fleeing:  # cornered, a frightened one fights
            if cheb(m, t) > MONKEY_FLEE:
                return TICKS_PER_TURN
            return self._step_away(m, lvl, t) or (None if m.fleeing else TICKS_PER_TURN)
        if cheb(m, t) == 1 and not lvl.diagonal_blocked(m.x, m.y, t.x, t.y):
            return self._steal(m, lvl, t)
        return self._step_toward(m, lvl, t.x, t.y) or TICKS_PER_TURN

    def _steal(self, m: Monster, lvl: Level, t: Player) -> int:
        """One item, or some gold. Never what they're wearing, a key or the Amulet."""
        m.robbed = True
        where = [(m.x, m.y), (t.x, t.y)]

        def whose(v) -> str:
            return "your" if v is t else f"{t.name}'s"

        items = [i for i in t.pack if i not in (t.weapon, t.armor, t.cloak, t.ranged)
                 and i.category not in ("amulet", "key")]
        choices = (["item"] if items else []) + (["gold"] if t.gold > 0 else [])
        if not choices:
            self.note(m, f"found nothing to steal from {self._tag(t)}")
            self._narrate(lvl, where, {t}, lambda v: (
                f"The {m.name} rummages through {whose(v)} pack, finds nothing and scampers off.", GRAY))
            return m.attack_cost
        if self.rng.choice(choices) == "item":
            item = m.stolen = self._take_one(t, self.rng.choice(items))
            m.drink_next = item.category == "potion" and self.rng.random() < MONKEY_DRINK_CHANCE
            self.note(m, f"stole {item.name} from {self._tag(t)}")
            self._narrate(lvl, where, {t}, lambda v: (f"The {m.name} snatches {whose(v)} {item.name}!", RED))
        else:
            amount = m.stolen_gold = min(t.gold, self.rng.randint(*MONKEY_GOLD))
            t.gold -= amount
            t.pack_dirty = True
            self.note(m, f"stole {amount} gold from {self._tag(t)}")
            self._narrate(lvl, where, {t}, lambda v: (f"The {m.name} grabs {amount} of {whose(v)} gold!", RED))
        return m.attack_cost

    def _drop_stolen(self, m: Monster, lvl: Level) -> None:
        """A monkey lets go of what it's carrying: what it stole, and any gold."""
        drops = [m.stolen, self._gold(m.stolen_gold) if m.stolen_gold else None]
        m.stolen, m.stolen_gold, m.drink_next = None, 0, False
        names = []
        for item in drops:
            if item is not None:
                lvl.items[lvl.free_item_spot(m.x, m.y)] = item
                names.append(item.label)
        if names:
            self.note(m, "dropped " + ", ".join(names))
            self._narrate(lvl, [(m.x, m.y)], set(), lambda v: (f"The {m.name} drops {' and '.join(names)}!", GOLD))

    def _monkey_drinks(self, m: Monster, lvl: Level) -> int:
        """The potion works on the monkey as it would on you."""
        item, m.stolen, m.drink_next = m.stolen, None, False
        start = (m.x, m.y)
        effects = []
        if item.heal:
            m.hp = min(m.max_hp, m.hp + item.heal)
            effects.append("looks better")
        if item.haste:
            m.haste_until = self.clock + int(item.haste * TICKS_PER_SECOND)
            effects.append("speeds up")
        if item.levitate:
            m.levitate_until = self.clock + int(item.levitate * TICKS_PER_SECOND)
            effects.append("floats up out of reach")
        if item.waterwalk:
            m.waterwalk_until = self.clock + int(item.waterwalk * TICKS_PER_SECOND)
            effects.append("can walk on water")
        if item.lavawalk:
            m.lavawalk_until = self.clock + int(item.lavawalk * TICKS_PER_SECOND)
            effects.append("can walk on lava")
        if item.strength:
            m.damage = (m.damage[0] + item.strength, m.damage[1] + item.strength)
            effects.append("looks stronger")
        if item.cure:
            effects.append("looks no different")
        if item.teleport:
            effects.append("vanishes")
        self.note(m, f"drank {item.name} hp {self._hp(m)}")
        self._narrate(lvl, [start], set(), lambda v: (
            f"The {m.name} drinks the {item.name} and {' and '.join(effects)}!", ORANGE))
        if item.teleport:
            self._monster_to_floor(m, lvl)
        return m.attack_cost

    def _monster_to_floor(self, m: Monster, old: Level) -> None:
        """The potion of teleportation: a random spot on a random other floor, as it does for you."""
        for v in self._living_on(m.depth):
            self.outbox.append((v.id, {"t": "fx", "kind": "blink", "cells": [(m.x, m.y)]}))
        depth = self.rng.choice([d for d in range(1, LAST_FLOOR + 1) if d != old.depth])
        self.note(m, f"teleported F{old.depth:02d}->F{depth:02d}")
        old.remove(m)
        old.monsters.remove(m)
        lvl = self.level(depth)
        lvl.place(m, *self._empty_floor(lvl, self.rng))
        lvl.monsters.append(m)
        m.state, m.target_id, m.last_seen, m.wander_target = "wandering", None, None, None

    def _turn_on_rat(self, m: Monster, lvl: Level) -> bool:
        """Kobolds and rats don't get on. Now and then a kobold kills one beside it."""
        rats = [o for o in lvl.monsters if o.kind == "rat" and cheb(o, m) == 1]
        if not rats or self.rng.random() >= KOBOLD_RAT_CHANCE:
            return False
        rat = rats[0]
        self.note(m, f"turned on {self._tag(rat)}")
        self._narrate(lvl, [(m.x, m.y), (rat.x, rat.y)], set(), lambda v: (f"The {m.name} turns on the {rat.name}!", GRAY))
        self._kill(rat, m)
        return True

    def _monster_turn(self, m: Monster, lvl: Level) -> int:
        if m.kind == "mushroom":
            return self._release_gas(m, lvl)
        if m.kind == "ghost":
            return self._haunt(m, lvl)
        if m.kind == "kobold" and m.state != "sleeping" and self._turn_on_rat(m, lvl):
            return m.attack_cost * MONSTER_SWING
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
            if m.burning and m.hp < m.max_hp * FLEE_HEALTH and m.kind not in STAY_PUT:
                cost = self._step_away(m, lvl, t)  # on fire and hurt: it runs
                if cost:
                    return cost
            if m.kind == "cult_mage":
                return self._mage(m, lvl, t)
            if m.kind == "cult_leader":
                return self._cult_leader(m, lvl, t)
            if m.kind == "spider_queen":
                return self._spider_queen(m, lvl, t)
            if m.kind == "spider":
                return self._spider(m, lvl, t)
            if m.kind == "kobold_scout":
                return self._scout(m, lvl, t)
            if m.kind == "kobold_leader":
                return self._spearman(m, lvl, t)
            if m.kind == "kobold":
                cost = self._kobold(m, lvl, t)
                if cost:
                    return cost
            if m.kind == "wolf":
                cost = self._wolf(m, lvl, t)
                if cost:
                    return cost
            if m.kind == "monkey":
                cost = self._monkey(m, lvl, t)
                if cost:
                    return cost
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
        dist = self._distances(m, lvl, tx, ty)
        ground = self._ground(m, lvl)
        best, best_d = None, dist[m.x, m.y]
        dirs = DIRS8[:]
        self.rng.shuffle(dirs)
        for dx, dy in dirs:
            nx, ny = m.x + dx, m.y + dy
            if not lvl.in_bounds(nx, ny) or not ground[nx, ny]:
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
                "lights": [protocol.pack_u8(m * 255) for m in lvl.torch_light],
                "stains": [[x, y, kind] for (x, y), kind in lvl.stains.items()],
                "webs": sorted(lvl.webs), **self._vault_walls(lvl)}

    def _vault_walls(self, lvl: Level) -> dict:
        """The walls around a locked room, to be drawn in its key's color."""
        room = self.locked_rooms.get(lvl.depth)
        if lvl.vault is None or room is None:
            return {}
        walls = beside(lvl.vault) & (lvl.tiles == WALL)
        return {"vault": {"c": list(LOCK_COLORS[room.color]), "cells": [[int(x), int(y)] for x, y in np.argwhere(walls)]}}

    def _status(self, p: Player) -> list[str]:
        if self.wiped():
            left = max(0, math.ceil(self.reset_at - time.monotonic()))
            if p.id in self.ready:
                return ["over", f"New dungeon in {left}s. Waiting for the rest of the party..."]
            return ["over", f"New dungeon in {left}s. Press Enter to start it now."]
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

    def _potion_left(self, a, until: str) -> float:
        """Seconds a player has left of walking on water or lava, which their glow fades away with."""
        return max(0.0, (getattr(a, until) - self.clock) / TICKS_PER_SECOND) if a.is_player else 0.0

    def _windup(self, m, lvl: Level) -> dict:
        """For a monster about to land a melee hit: seconds until it can, and how long its
        swing takes. The client turns these into a warning, so it stays smooth between states."""
        reach = 2 if getattr(m, "kind", "") == "kobold_leader" else 1  # a spear
        if (not isinstance(m, Monster) or m.state != "hunting" or not m.damage[1] or m.frozen_until > self.clock
                or m.kind == "skeleton_archer"  # it shoots rather than swings
                or not any(cheb(m, p) <= reach and (reach > 1 or not lvl.diagonal_blocked(m.x, m.y, p.x, p.y))
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
                 "eq": i in (p.weapon, p.armor, p.cloak, p.ranged), "sell": i.sell_price if i.sellable else 0} for i in p.pack]
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
                             "seen": seen or p.reveal, "hl": p.reveal and not a.is_player,
                             "st": "merchant" if isinstance(a, Merchant) else a.role if isinstance(a, Npc) else getattr(a, "state", ""),
                             "kind": getattr(a, "kind", ""), "lev": getattr(a, "levitate_until", 0) > self.clock,
                             "float": self._floating(a),
                             "burn": getattr(a, "burning", 0) > 0,
                             "frozen": getattr(a, "frozen_until", 0) > self.clock,
                             "ward": a.is_player and a.reflect_until > self.clock,
                             "aura": a.is_player and a.armor is not None and a.armor.reflect,
                             "wet": self._potion_left(a, "waterwalk_until"), "hot": self._potion_left(a, "lavawalk_until"),
                             **self._windup(a, lvl)})
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
                "levitate": self._levitating(p), "victory": self.victory,
                "slowed": p.slow_until > self.clock or p.webbed_until > self.clock, "webbed": p.webbed_until > self.clock,
                "toxin": p.toxin_until > self.clock or p.venom_until > self.clock,
                "venom": max(0, p.venom_until - self.clock) / TICKS_PER_SECOND, "slime": [c for c in lvl.slime if vis[c]], "bright": p.bright, "reveal": p.reveal,
                "gas": [[*c, max(1, 9 * (end - self.clock) // gas_span)] for c, end in lvl.gas.items() if vis[c]],
                "fire": [list(c) for c in lvl.fire if vis[c]],
                "bombs": [[b["x"], b["y"]] for b in lvl.bombs if vis[b["x"], b["y"]]],
                "fed": p.food_until > self.clock,
                "waterwalk": p.waterwalk_until > self.clock,
                "lavawalk": p.lavawalk_until > self.clock, "stamina": int(p.stamina), "lit": self._lit(p) > 0,
                "detect": round(self._notice_range(p, NOTICE_RANGE_AWAKE)),
                "status": status, "turns": p.turns, "kills": p.kills, "death": p.death,
                "score": self.score_of(p), "score_gold": self.carried_gold(p), "tally": p.kill_tally,
                "hardest": self._hardest_name(p), "season": self.season}
