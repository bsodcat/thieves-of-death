"""Holiday dress-up for monsters and items. Only names, descriptions and colors change.

A season is on when today falls inside its dates, by the clock of the computer running
the server. Stats never change, so a season can't affect how the game plays. Add one by
adding an entry to SEASONS; a kind left out keeps its normal look.
"""
from __future__ import annotations

from datetime import date

SEASONS = {
    "halloween": {
        "start": (10, 24), "end": (10, 31),
        "greeting": "Happy Halloween!",
        "joined": "Happy Halloween! Something has dressed up the dungeon...",
        "gold": "candy corn",
        "merchant": "cloaked peddler",
        "monsters": {
            "rat": ("skeletal rat", (225, 220, 195), "Nothing but bones and spite."),
            "kobold": ("jack-o'-kobold", (255, 150, 40), "Its grin is carved on."),
            "jackal": ("werejackal", (190, 150, 110), "Howls at nothing."),
            "monkey": ("mummified monkey", (210, 200, 160), "Trailing its wrappings."),
            "goblin": ("ghostly goblin", (170, 240, 200), "Cold to the touch."),
            "ogre": ("zombie ogre", (130, 170, 90), "Huge, and still falling apart."),
        },
        "items": {
            "healing": ("pumpkin juice", (255, 150, 40)),
            "greater_healing": ("witch's brew", (170, 90, 220)),
            "haste": ("bag of sugary candy", (255, 90, 160)),
            "levitation": ("broomstick brew", (190, 170, 255)),
            "dagger": ("bone shiv", (225, 220, 195)),
            "sword": ("cursed sword", (170, 90, 220)),
            "mace": ("tombstone club", (160, 160, 170)),
            "leather": ("tattered shroud", (190, 190, 200)),
            "scale": ("rib cage armor", (225, 220, 195)),
            "plate": ("coffin plate", (120, 90, 70)),
        },
    },
    "christmas": {
        "start": (12, 18), "end": (12, 26),
        "greeting": "Merry Christmas!",
        "joined": "Merry Christmas! The dungeon is looking festive...",
        "gold": "chocolate coins",
        "merchant": "jolly toymaker",
        "monsters": {
            "rat": ("stirring mouse", (190, 190, 200), "Not a creature was stirring, except this."),
            "kobold": ("naughty elf", (90, 200, 110), "Definitely on the list."),
            "jackal": ("runaway reindeer", (190, 140, 90), "Has gone off the route."),
            "monkey": ("wind-up monkey", (230, 90, 90), "Clashes its cymbals."),
            "goblin": ("gift goblin", (230, 60, 60), "Nobody asked for this."),
            "ogre": ("krampus", (170, 60, 50), "Here for the naughty ones."),
        },
        "items": {
            "healing": ("mug of cocoa", (170, 110, 70)),
            "greater_healing": ("figgy pudding", (140, 80, 60)),
            "haste": ("candy cane", (255, 90, 90)),
            "levitation": ("pinch of sleigh dust", (190, 170, 255)),
            "dagger": ("sharp icicle", (170, 230, 255)),
            "sword": ("peppermint sword", (255, 120, 120)),
            "mace": ("yule log", (150, 100, 60)),
            "leather": ("ugly sweater", (90, 200, 110)),
            "scale": ("tinsel mail", (230, 215, 120)),
            "plate": ("nutcracker armor", (230, 60, 60)),
        },
    },
}


def active_season(day: date) -> str | None:
    for name, season in SEASONS.items():
        if season["start"] <= (day.month, day.day) <= season["end"]:
            return name
    return None


def current() -> str | None:
    """The season by this computer's clock."""
    return active_season(date.today())


def merchant_name(season: str | None) -> str:
    return SEASONS[season]["merchant"] if season else "merchant"


def gold_name(season: str | None) -> str:
    return SEASONS[season]["gold"] if season else "gold"


def greeting(season: str | None) -> str:
    return SEASONS[season]["greeting"] if season else ""


def joined_message(season: str | None) -> str:
    return SEASONS[season]["joined"] if season else ""


def dress_monster(monster, season: str | None):
    look = SEASONS[season]["monsters"].get(monster.kind) if season else None
    if look:
        monster.name, monster.color = look[0], look[1]
    return monster


def dress_item(item, season: str | None):
    if not season:
        return item
    if item.category == "gold":
        item.name = SEASONS[season]["gold"]
        return item
    look = SEASONS[season]["items"].get(item.kind)
    if look:
        item.name, item.color = look
    return item


def monster_name(kind: str, season: str | None, default: str) -> str:
    look = SEASONS[season]["monsters"].get(kind) if season else None
    return look[0] if look else default


def monster_description(kind: str, season: str | None, default: str) -> str:
    look = SEASONS[season]["monsters"].get(kind) if season else None
    return look[2] if look else default
