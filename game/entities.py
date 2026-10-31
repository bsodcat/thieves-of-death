"""Players, monsters and the monster catalogue."""
from __future__ import annotations

from dataclasses import dataclass, field

from .constants import STAMINA_MAX, STEALTH_MAX, TICKS_PER_TURN
from .items import Item


@dataclass(eq=False)
class Actor:
    id: int
    name: str
    glyph: str
    color: tuple
    hp: int
    max_hp: int
    accuracy: int
    defense: int
    damage: tuple
    move_cost: int = TICKS_PER_TURN
    attack_cost: int = TICKS_PER_TURN
    x: int = 0
    y: int = 0
    depth: int = 1
    next_time: int = 0          # absolute tick at which this actor may act again

    is_player = False
    verbs = ("hits", "hit")     # (third person, second person)


@dataclass(eq=False)
class Player(Actor):
    pending: dict | None = None  # the one action queued until this player's cooldown ends
    hold: tuple | None = None    # the direction being held down, stepped once per cooldown
    alive: bool = True
    connected: bool = True
    turns: int = 0
    kills: int = 0
    regen_acc: int = 0
    pack: list = field(default_factory=list)
    gold: int = 0
    weapon: Item | None = None   # equipped items stay in the pack
    armor: Item | None = None
    haste_until: int = 0         # tick when haste wears off
    levitate_until: int = 0      # tick when they come back down
    stealth: float = 0.0         # 0 to stealth_cap
    stealth_cap: int = STEALTH_MAX   # lowered by the noise of equipped gear
    stamina: float = STAMINA_MAX
    stamina_rest: int = 0        # tick when stamina starts refilling
    sprinting: bool = False      # Shift is held down
    ping: float | None = None    # smoothed round trip in ms; None until measured
    downed: bool = False         # Revive mode: fallen, but can be brought back
    final_gold: int | None = None  # gold carried when they fell; Classic scatters the real gold
    kill_tally: dict = field(default_factory=dict)   # monster name -> kills
    hardest: str = ""            # the most dangerous monster kind they've fought
    revive_ticks: int = 0        # how long a teammate has been beside them
    pack_dirty: bool = True      # the client needs a fresh copy of the pack
    needs_level: bool = True
    death: str = ""
    fov_key: tuple | None = None
    fov: object = None

    is_player = True


@dataclass(eq=False)
class Monster(Actor):
    kind: str = ""
    verbs: tuple = ("hits", "hit")
    state: str = "sleeping"      # sleeping / wandering / hunting
    target_id: int | None = None
    last_seen: tuple | None = None
    wander_target: tuple | None = None
    lag: int = 0                 # staggers monsters so a level doesn't all move at once


# What players can choose on the character screen. Shapes that look like a monster,
# an item or a map tile are left out, so a player is never mistaken for one.
PLAYER_GLYPHS = ("@", "&", "\u263a", "\u263b", "\u2665", "\u2666", "\u2663", "\u2660",
                 "\u2642", "\u2640", "\u263c", "\u03a9")
PLAYER_COLOR_NAMES = {
    "Gold": (255, 215, 90), "Sky": (110, 200, 255), "Pink": (255, 120, 170),
    "Lime": (140, 255, 140), "Orange": (255, 160, 80), "Violet": (200, 150, 255),
    "Red": (255, 90, 90), "Teal": (80, 220, 200), "White": (235, 235, 235),
}
PLAYER_COLORS = list(PLAYER_COLOR_NAMES.values())

@dataclass(eq=False)
class Merchant(Actor):
    stock: dict = field(default_factory=dict)   # stock id -> Item


def make_merchant(mid: int, name: str) -> Merchant:
    return Merchant(id=mid, name=name, glyph="$", color=(255, 215, 90), hp=1, max_hp=1, accuracy=0,
                    defense=0, damage=(0, 0))


PLAYER_STATS = dict(hp=40, accuracy=100, defense=30, damage=(2, 4))


def make_player(pid: int, name: str, color: tuple) -> Player:
    s = PLAYER_STATS
    return Player(id=pid, name=name, glyph="@", color=color, hp=s["hp"], max_hp=s["hp"],
                  accuracy=s["accuracy"], defense=s["defense"], damage=s["damage"])


def apply_gear(p: Player) -> None:
    """Recomputes a player's stats from what they have equipped."""
    s, w, a = PLAYER_STATS, p.weapon, p.armor
    p.damage = w.damage if w else s["damage"]
    p.attack_cost = w.attack_cost if w else TICKS_PER_TURN
    p.defense = s["defense"] + (a.armor if a else 0)
    p.move_cost = a.move_cost if a else TICKS_PER_TURN
    p.stealth_cap = max(0, STEALTH_MAX - (w.noise if w else 0) - (a.noise if a else 0))
    p.stealth = min(p.stealth, p.stealth_cap)


def reset_player(p: Player) -> None:
    s = PLAYER_STATS
    p.hp = p.max_hp = s["hp"]
    p.accuracy = s["accuracy"]
    p.alive, p.pending, p.hold, p.death, p.stealth = True, None, None, "", 0.0
    p.stamina, p.stamina_rest = STAMINA_MAX, 0
    p.downed, p.revive_ticks = False, 0
    p.final_gold, p.kill_tally, p.hardest = None, {}, ""
    p.turns = p.kills = p.regen_acc = p.next_time = p.haste_until = p.levitate_until = 0
    p.fov_key, p.fov = None, None
    p.pack, p.gold, p.weapon, p.armor, p.pack_dirty = [], 0, None, None, True
    apply_gear(p)


# Stats are this project's own; tweak freely. depths = (first, last) depth it appears on.
MONSTERS = {
    "rat": dict(name="rat", glyph="r", color=(160, 130, 110), hp=6, accuracy=70, defense=0,
                damage=(1, 3), move=100, attack=100, depths=(1, 6), weight=10, verbs=("bites", "bite"),
                desc="A mangy rat."),
    "kobold": dict(name="kobold", glyph="k", color=(150, 190, 120), hp=7, accuracy=70, defense=0,
                   damage=(1, 4), move=100, attack=100, depths=(1, 7), weight=10, verbs=("hits", "hit"),
                   desc="Small, mean and armed."),
    "jackal": dict(name="jackal", glyph="j", color=(200, 160, 90), hp=8, accuracy=70, defense=3,
                   damage=(2, 4), move=50, attack=100, depths=(1, 8), weight=8, verbs=("bites", "bite"),
                   desc="Runs you down."),
    "monkey": dict(name="monkey", glyph="m", color=(170, 120, 80), hp=12, accuracy=100, defense=17,
                   damage=(1, 3), move=100, attack=100, depths=(2, 10), weight=6, verbs=("hits", "hit"),
                   desc="Quick to dodge."),
    "goblin": dict(name="goblin", glyph="g", color=(120, 170, 90), hp=15, accuracy=70, defense=10,
                   damage=(2, 5), move=100, attack=100, depths=(3, 12), weight=7, verbs=("slashes", "slash"),
                   desc="A hardened fighter."),
    "ogre": dict(name="ogre", glyph="O", color=(160, 120, 170), hp=55, accuracy=125, defense=60,
                 damage=(9, 13), move=100, attack=200, depths=(7, 26), weight=4,
                 verbs=("bludgeons", "bludgeon"), desc="Huge. One hit hurts."),
}


def danger(kind: str) -> float:
    """How tough a monster is: its health times the damage it deals per normal turn."""
    t = MONSTERS[kind]
    return t["hp"] * sum(t["damage"]) / 2 * TICKS_PER_TURN / t["attack"]


def make_monster(kind: str, mid: int) -> Monster:
    t = MONSTERS[kind]
    return Monster(id=mid, name=t["name"], glyph=t["glyph"], color=t["color"], hp=t["hp"],
                   max_hp=t["hp"], accuracy=t["accuracy"], defense=t["defense"], damage=t["damage"],
                   move_cost=t["move"], attack_cost=t["attack"], kind=kind, verbs=t["verbs"])
