"""Items: potions, weapons, armor, cloaks, keys, wands, the Amulet and gold, and the catalogue they're made from."""
from __future__ import annotations

import math
from dataclasses import dataclass

from .constants import (BOMB_SECONDS, ENHANCE_ACCURACY, ENHANCE_BOOST, ENHANCE_DAMAGE, ENHANCE_NOISE, SELL_SHARE,
                        TICKS_PER_TURN, WAND_CHARGES)
from .tiles import LOCK_COLORS

GLYPHS = {"potion": "!", "weapon": ")", "armor": "[", "gold": "*", "key": "\u2640", "cloak": "¶", "wand": "/", "amulet": "§", "ranged": "}",
          "ammo": "|", "bomb": "δ", "food": "Θ"}
AUTO_PICKUP = ("potion", "gold", "key", "ammo", "bomb")   # collected by walking over them; the rest wait for a key press


@dataclass(eq=False)
class Item:
    kind: str
    name: str
    category: str               # potion / weapon / armor / cloak / gold / key / wand / amulet / ranged / ammo
    color: tuple
    count: int = 1              # stack size, or the amount for gold
    heal: int = 0
    haste: float = 0.0          # seconds of double speed
    levitate: float = 0.0       # seconds off the ground
    waterwalk: float = 0.0      # seconds of walking on deep water
    lavawalk: float = 0.0       # seconds of walking on lava
    teleport: bool = False      # moves you elsewhere on the floor
    price: int = 0              # what a merchant asks for it
    damage: tuple = (0, 0)
    attack_cost: int = TICKS_PER_TURN
    armor: int = 0
    move_cost: int = TICKS_PER_TURN
    noise: int = 0              # lowers the stealth cap while equipped; a cloak's is negative
    hush: float = 0.0           # the share of detection range a cloak takes away
    opens: int = 0              # the floor whose locked door this key fits
    charges: int = 0            # uses left in a wand
    freeze: float = 0.0         # seconds a wand holds its target still
    accuracy: int = 0           # added to the wielder's chance to hit
    reflect: bool = False       # armor that sends magic back
    reach: int = 0              # how far a ranged weapon can hit
    fires: str = ""             # what it uses up, if anything
    magic: tuple = ()           # an enhanced weapon's spells: fire, frost, drain
    enhanced: int = 0           # how many times an altar has improved it
    unlimited: bool = False     # a wand that never runs out
    lightning: bool = False     # a wand that casts lightning
    back_at: int = 0            # tick a thrown boomerang is back in hand

    @property
    def glyph(self) -> str:
        return GLYPHS[self.category]

    @property
    def stacks(self) -> bool:
        return self.category in ("potion", "ammo", "bomb")

    @property
    def sellable(self) -> bool:
        return self.price > 0 and self.category not in ("key", "amulet", "gold", "food")

    @property
    def sell_price(self) -> int:
        """What a merchant pays for one of these, or for a whole quiver of arrows."""
        each = max(1, int(self.price * SELL_SHARE))
        return each * self.count if self.category == "ammo" else each

    @property
    def label(self) -> str:
        if self.category == "gold":
            return f"{self.count} {self.name}"
        return f"{self.name} x{self.count}" if self.count > 1 else self.name

    @property
    def info(self) -> str:
        if self.category == "weapon":
            speed = ", slow" if self.attack_cost > TICKS_PER_TURN else ""
            extras = "".join(f", {spell}" for spell in self.magic) + (", bane of undead" if self.enhanced else "")
            return f"dmg {self.damage[0]}-{self.damage[1]}{speed}, noise {self.noise}{extras}"
        if self.category == "armor":
            speed = ", heavy" if self.move_cost > TICKS_PER_TURN else ""
            ward = ", warded" if self.reflect else ""
            return f"armor +{self.armor}{speed}, noise {self.noise}{ward}"
        if self.category == "ranged":
            ammo = f", uses {self.fires}s" if self.fires else ", comes back"
            return f"dmg {self.damage[0]}-{self.damage[1]}, range {self.reach}{ammo}"
        if self.category == "ammo":
            return "for a bow"
        if self.category == "bomb":
            return f"blows up {BOMB_SECONDS:.0f}s after use"
        if self.category == "food":
            return "walk into it to eat"
        if self.category == "cloak":
            return f"detection -{self.hush:.0%}, noise {self.noise}"
        if self.heal:
            return f"heals {self.heal}"
        if self.haste:
            return f"speed for {self.haste:.0f}s"
        if self.levitate:
            return f"float for {self.levitate:.0f}s"
        if self.teleport:
            return "jump to a random floor"
        if self.waterwalk:
            return f"walk on water for {self.waterwalk:.0f}s"
        if self.lavawalk:
            return f"walk on lava for {self.lavawalk:.0f}s"
        if self.category == "wand" and self.unlimited:
            return "lightning, unlimited, no altar takes it"
        if self.category == "wand":
            effect = f"freeze {self.freeze:.0f}s" if self.freeze else "fire"
            return f"{effect}, {self.charges} use{'' if self.charges == 1 else 's'} left"
        if self.category == "amulet":
            return "carry it up the stairs on floor 1"
        if self.category == "key":
            return f"opens a door on floor {self.opens}"
        return ""


# Stats are this project's own; tweak freely. depths = (first, last) depth it appears on.
ITEMS = {
    "healing": dict(name="potion of healing", category="potion", color=(255, 110, 130), heal=20, price=30,
                    depths=(1, 26), weight=10),
    "greater_healing": dict(name="potion of greater healing", category="potion", color=(255, 60, 90), heal=40,
                            price=70, depths=(3, 26), weight=4),
    "haste": dict(name="potion of haste", category="potion", color=(120, 220, 255), haste=10.0, price=60,
                  depths=(2, 26), weight=4),
    "levitation": dict(name="potion of levitation", category="potion", color=(190, 170, 255), levitate=9.0, price=600,
                       depths=(3, 26), weight=1),
    "teleportation": dict(name="potion of teleportation", category="potion", color=(230, 120, 255), teleport=True,
                          price=60, depths=(1, 26), weight=3),
    "waterwalking": dict(name="potion of water walking", category="potion", color=(90, 170, 255), waterwalk=60.0,
                         price=90, depths=(18, 42), weight=3),
    "lavawalking": dict(name="potion of lava walking", category="potion", color=(255, 130, 40), lavawalk=60.0,
                        price=90, depths=(18, 42), weight=3),
    "bow": dict(name="bow", category="ranged", color=(180, 135, 80), damage=(4, 8), reach=12, fires="arrow",
                price=100, depths=(1, 26), weight=3),
    "arrows": dict(name="arrow", category="ammo", color=(205, 195, 170), price=2, depths=(1, 26), weight=4),
    "boomerang": dict(name="boomerang", category="ranged", color=(225, 175, 90), damage=(3, 6), reach=9,
                      price=90, depths=(2, 26), weight=2),
    "bomb": dict(name="bomb", category="bomb", color=(200, 200, 200), price=50, depths=(3, 26), weight=1),
    "dagger": dict(name="dagger", category="weapon", color=(200, 200, 210), damage=(3, 5), noise=5, price=40,
                   depths=(1, 6), weight=6),
    "sword": dict(name="sword", category="weapon", color=(220, 220, 240), damage=(5, 9), noise=15, price=120,
                  depths=(2, 26), weight=4),
    "mace": dict(name="mace", category="weapon", color=(190, 170, 150), damage=(12, 18), noise=20, price=220,
                 attack_cost=2 * TICKS_PER_TURN, depths=(4, 26), weight=2),
    "leather": dict(name="leather armor", category="armor", color=(170, 120, 70), armor=15, noise=10, price=80,
                    depths=(1, 8), weight=6),
    "scale": dict(name="scale armor", category="armor", color=(150, 170, 150), armor=35, noise=25, price=220,
                  depths=(3, 26), weight=3),
    "frost_wand": dict(name="wand of frost", category="wand", color=(140, 210, 255), freeze=30.0, charges=WAND_CHARGES,
                       price=250, depths=(6, 86), weight=1),
    "plate": dict(name="plate armor", category="armor", color=(190, 200, 215), armor=60, noise=40, price=450,
                  move_cost=TICKS_PER_TURN * 5 // 4, depths=(32, 62), weight=1),
    "magic": dict(name="magic armor", category="armor", color=(51, 51, 215), armor=40, noise=10, reflect=True,
                  price=590, depths=(60, 70), weight=3),
    "chain": dict(name="chain mail", category="armor", color=(170, 175, 185), armor=25, noise=20, price=160,
                  depths=(2, 26), weight=3),
    "mithril": dict(name="mithril shirt", category="armor", color=(200, 230, 255), armor=40, noise=5, price=520,
                    depths=(36, 80), weight=1),
    "dragonscale": dict(name="dragon scale armor", category="armor", color=(120, 200, 140), armor=75, noise=25,
                        price=580, depths=(72, 98), weight=2),
    "flame_blade": dict(name="flame blade", category="weapon", color=(255, 140, 50), damage=(7, 11), noise=15,
                        magic=("fire",), price=380, depths=(20, 60), weight=1),
    "frost_brand": dict(name="frost brand", category="weapon", color=(150, 215, 255), damage=(8, 12), noise=15,
                        magic=("frost",), price=420, depths=(30, 75), weight=1),
    "war_axe": dict(name="war axe", category="weapon", color=(205, 185, 165), damage=(14, 20), noise=25, price=400,
                    depths=(30, 75), weight=2),
    "greatsword": dict(name="greatsword", category="weapon", color=(235, 235, 250), damage=(20, 28), noise=30,
                       price=560, attack_cost=TICKS_PER_TURN * 3 // 2, depths=(55, 98), weight=2),
}
GOLD_COLOR = (255, 215, 90)
CLOAK = dict(name="cloak", category="cloak", color=(120, 130, 185), noise=-45, hush=0.5, price=100)  # not found by chance


def enhance_weapon(w: Item, rng) -> str:
    """Improves a weapon for good, in one random way, and says how."""
    options = ["damage", "damage", "accuracy"]
    options += [spell for spell in ("fire", "frost", "drain") if spell not in w.magic]
    if w.attack_cost > TICKS_PER_TURN // 2:
        options.append("speed")
    if w.noise > 0:
        options.append("silence")
    choice = rng.choice(options)
    w.enhanced += 1
    w.name = f"{w.name.rsplit(' +', 1)[0]} +{w.enhanced}"
    w.damage = tuple(math.ceil(d * (1 + ENHANCE_BOOST)) for d in w.damage)  # every blessing adds a share
    if choice == "damage":
        extra = rng.randint(*ENHANCE_DAMAGE)
        w.damage = (w.damage[0] + extra, w.damage[1] + extra)
        return f"it hits {extra} harder"
    if choice == "accuracy":
        w.accuracy += ENHANCE_ACCURACY
        return "it finds its mark more often"
    if choice == "speed":
        w.attack_cost = max(TICKS_PER_TURN // 2, w.attack_cost * 3 // 4)
        return "it feels lighter and strikes faster"
    if choice == "silence":
        w.noise = max(0, w.noise - ENHANCE_NOISE)
        return "it makes less noise"
    w.magic += (choice,)
    return {"fire": "it sets what it hits alight", "frost": "it can freeze what it hits",
            "drain": "it heals you as it wounds"}[choice]


def make_item(kind: str) -> Item:
    fields = {k: v for k, v in ITEMS[kind].items() if k not in ("depths", "weight")}
    return Item(kind=kind, **fields)


def make_cloak() -> Item:
    return Item(kind="cloak", **CLOAK)


def make_wand() -> Item:
    return Item(kind="fire_wand", name="wand of fire", category="wand", color=(255, 120, 40), charges=WAND_CHARGES,
                price=200)


def make_staff() -> Item:
    """The cultist mage's. It's never used up, and it isn't a melee weapon, so no altar takes it."""
    return Item(kind="lightning_staff", name="staff of lightning", category="wand", color=(190, 140, 255),
                unlimited=True, lightning=True, price=700)


def make_barrel() -> Item:
    return Item(kind="food", name="barrel of food", category="food", color=(170, 120, 70))


def make_amulet() -> Item:
    return Item(kind="amulet", name="the Amulet", category="amulet", color=(255, 230, 120))


def make_key(color: str, depth: int) -> Item:
    return Item(kind=f"{color}_key", name=f"{color} key", category="key", color=LOCK_COLORS[color], opens=depth)


def make_gold(amount: int) -> Item:
    return Item(kind="gold", name="gold", category="gold", color=GOLD_COLOR, count=amount)
