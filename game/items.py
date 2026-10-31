"""Items: potions, weapons, armor and gold, and the catalogue they're made from."""
from __future__ import annotations

from dataclasses import dataclass

from .constants import TICKS_PER_TURN

GLYPHS = {"potion": "!", "weapon": ")", "armor": "[", "gold": "*"}
AUTO_PICKUP = ("potion", "gold")   # collected by walking over them; the rest wait for a key press


@dataclass(eq=False)
class Item:
    kind: str
    name: str
    category: str               # potion / weapon / armor / gold
    color: tuple
    count: int = 1              # stack size, or the amount for gold
    heal: int = 0
    haste: float = 0.0          # seconds of double speed
    levitate: float = 0.0       # seconds off the ground
    price: int = 0              # what a merchant asks for it
    damage: tuple = (0, 0)
    attack_cost: int = TICKS_PER_TURN
    armor: int = 0
    move_cost: int = TICKS_PER_TURN
    noise: int = 0              # lowers the stealth cap while equipped

    @property
    def glyph(self) -> str:
        return GLYPHS[self.category]

    @property
    def stacks(self) -> bool:
        return self.category == "potion"

    @property
    def label(self) -> str:
        if self.category == "gold":
            return f"{self.count} {self.name}"
        return f"{self.name} x{self.count}" if self.count > 1 else self.name

    @property
    def info(self) -> str:
        if self.category == "weapon":
            speed = ", slow" if self.attack_cost > TICKS_PER_TURN else ""
            return f"dmg {self.damage[0]}-{self.damage[1]}{speed}, noise {self.noise}"
        if self.category == "armor":
            speed = ", heavy" if self.move_cost > TICKS_PER_TURN else ""
            return f"armor +{self.armor}{speed}, noise {self.noise}"
        if self.heal:
            return f"heals {self.heal}"
        if self.haste:
            return f"speed for {self.haste:.0f}s"
        if self.levitate:
            return f"float for {self.levitate:.0f}s"
        return ""


# Stats are this project's own; tweak freely. depths = (first, last) depth it appears on.
ITEMS = {
    "healing": dict(name="potion of healing", category="potion", color=(255, 110, 130), heal=20,
                    depths=(1, 26), weight=10),
    "greater_healing": dict(name="potion of greater healing", category="potion", color=(255, 60, 90), heal=40,
                            depths=(3, 26), weight=4),
    "haste": dict(name="potion of haste", category="potion", color=(120, 220, 255), haste=10.0,
                  depths=(2, 26), weight=4),
    "levitation": dict(name="potion of levitation", category="potion", color=(190, 170, 255), levitate=9.0, price=600,
                       depths=(3, 26), weight=1),
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
    "plate": dict(name="plate armor", category="armor", color=(190, 200, 215), armor=60, noise=40, price=450,
                  move_cost=TICKS_PER_TURN * 5 // 4, depths=(6, 26), weight=1),
}
GOLD_COLOR = (255, 215, 90)


def make_item(kind: str) -> Item:
    fields = {k: v for k, v in ITEMS[kind].items() if k not in ("depths", "weight")}
    return Item(kind=kind, **fields)


def make_gold(amount: int) -> Item:
    return Item(kind="gold", name="gold", category="gold", color=GOLD_COLOR, count=amount)
