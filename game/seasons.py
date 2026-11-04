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
            "wolf": ("hellhound", (200, 80, 60), "Its eyes glow like coals."),
            "mushroom": ("toadstool", (170, 90, 220), "It breathes out when you get close."),
            "zombie": ("rotting corpse", (130, 170, 90), "It won't stop coming."),
            "necromancer": ("lich lord", (190, 90, 255), "Death itself, in a robe."),
            "skeleton_archer": ("rattling archer", (225, 220, 195), "Its bones click as it aims."),
            "skeleton_warrior": ("grave knight", (190, 190, 200), "It has been waiting."),
            "slime": ("ectoplasm", (170, 240, 200), "Left behind by something."),
            "ghost": ("wailing spirit", (170, 240, 200), "It knows what you took."),
            "dragon": ("bone wyrm", (225, 220, 195), "All teeth and old fire."),
            "cultist": ("hooded ghoul", (150, 120, 170), "Chants at the dark."),
            "cult_leader": ("grave priest", (200, 90, 220), "Its wand smolders."),
            "cult_mage": ("banshee witch", (180, 100, 255), "Floats out of reach and calls down lightning."),
            "kobold_leader": ("scarecrow kobold", (90, 130, 255), "Slow, and its pitchfork reaches a tile away."),
            "kobold_scout": ("lantern kobold", (255, 120, 40), "Keeps its distance and throws embers."),
            "spider_queen": ("widow queen", (200, 40, 50), "A giant widow in a webbed cave. Run and she spits web. Venomous."),
            "spider": ("black widow", (90, 80, 100), "Leaps, bites and backs off. Its venom never kills."),
        },
        "items": {
            "healing": ("pumpkin juice", (255, 150, 40)),
            "greater_healing": ("witch's brew", (170, 90, 220)),
            "haste": ("bag of sugary candy", (255, 90, 160)),
            "levitation": ("broomstick brew", (190, 170, 255)),
            "teleportation": ("vanishing cider", (170, 240, 200)),
            "dagger": ("bone shiv", (225, 220, 195)),
            "sword": ("cursed sword", (170, 90, 220)),
            "mace": ("tombstone club", (160, 160, 170)),
            "leather": ("tattered shroud", (190, 190, 200)),
            "scale": ("rib cage armor", (225, 220, 195)),
            "plate": ("coffin plate", (120, 90, 70)),
            "magic": ("witch's robes", (51, 51, 215)),
            "bow": ("bone bow", (225, 220, 195)),
            "arrows": ("black arrow", (120, 110, 130)),
            "boomerang": ("flying scythe", (190, 190, 200)),
            "cloak": ("vampire's cape", (150, 40, 60)),
            "waterwalking": ("swamp witch's broth", (90, 170, 120)),
            "lavawalking": ("brimstone broth", (255, 110, 40)),
            "fire_wand": ("jack-o'-lantern wand", (255, 150, 40)),
            "frost_wand": ("witch's icy wand", (140, 210, 255)),
            "bomb": ("cherry bomb", (230, 60, 60)),
            "chain": ("rattling chains", (170, 175, 185)),
            "mithril": ("ghost silk shirt", (200, 230, 255)),
            "dragonscale": ("wyrm hide armor", (120, 200, 140)),
            "flame_blade": ("hellfire blade", (255, 140, 50)),
            "frost_brand": ("grave-cold brand", (150, 215, 255)),
            "war_axe": ("headsman's axe", (205, 185, 165)),
            "greatsword": ("reaper's blade", (190, 190, 200)),
            "strength": ("ogre's blood", (200, 60, 40)),
            "hook": ("fisherman's bone hook", (225, 220, 195)),
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
            "wolf": ("snow wolf", (220, 235, 250), "Hungry all winter."),
            "mushroom": ("sprout", (90, 200, 110), "Nobody likes these. It knows."),
            "zombie": ("melted snowman", (190, 200, 220), "It keeps on walking."),
            "necromancer": ("krampus", (200, 40, 40), "Keeps a very different list."),
            "skeleton_archer": ("toy archer", (230, 215, 120), "Wound up, and aiming."),
            "skeleton_warrior": ("toy soldier", (230, 60, 60), "Marching out of step."),
            "slime": ("eggnog spill", (240, 230, 190), "Sticky, and it's moving."),
            "ghost": ("christmas past", (200, 230, 255), "It has come to collect."),
            "dragon": ("ghost of yule", (200, 230, 255), "Past, present and hungry."),
            "cultist": ("carol singer", (200, 60, 70), "Sings without stopping."),
            "cult_leader": ("choir master", (240, 90, 80), "Its wand glows like a coal."),
            "cult_mage": ("star topper", (255, 230, 120), "Floats out of reach and throws lightning."),
            "kobold_leader": ("head elf", (90, 130, 255), "Slow, and its candy cane reaches a tile away."),
            "kobold_scout": ("chimney elf", (235, 75, 55), "Keeps its distance and throws hot coals."),
            "spider_queen": ("ice spider queen", (170, 220, 255), "A giant spider in an icy cave. Run and she spits web. Venomous."),
            "spider": ("frost spider", (200, 230, 255), "Leaps, bites and backs off. Its venom never kills."),
        },
        "items": {
            "healing": ("mug of cocoa", (170, 110, 70)),
            "greater_healing": ("figgy pudding", (140, 80, 60)),
            "haste": ("candy cane", (255, 90, 90)),
            "levitation": ("pinch of sleigh dust", (190, 170, 255)),
            "teleportation": ("chimney soot", (120, 120, 130)),
            "dagger": ("sharp icicle", (170, 230, 255)),
            "sword": ("peppermint sword", (255, 120, 120)),
            "mace": ("yule log", (150, 100, 60)),
            "leather": ("ugly sweater", (90, 200, 110)),
            "scale": ("tinsel mail", (230, 215, 120)),
            "plate": ("nutcracker armor", (230, 60, 60)),
            "magic": ("snowflake mail", (170, 200, 255)),
            "bow": ("gift-ribbon bow", (230, 60, 60)),
            "arrows": ("candy arrow", (255, 120, 120)),
            "boomerang": ("flying wreath", (90, 200, 110)),
            "cloak": ("snowy cloak", (220, 235, 250)),
            "waterwalking": ("ice skate tonic", (170, 230, 255)),
            "lavawalking": ("hot toddy", (255, 150, 60)),
            "fire_wand": ("yule torch", (255, 170, 60)),
            "frost_wand": ("snow globe", (170, 230, 255)),
            "bomb": ("christmas cracker", (230, 60, 60)),
            "chain": ("tinsel chain", (230, 215, 120)),
            "mithril": ("silver bell shirt", (200, 230, 255)),
            "dragonscale": ("evergreen armor", (60, 160, 80)),
            "flame_blade": ("hearth blade", (255, 140, 50)),
            "frost_brand": ("frosty brand", (170, 230, 255)),
            "war_axe": ("woodcutter's axe", (170, 120, 80)),
            "greatsword": ("nutcracker's saber", (235, 235, 250)),
            "strength": ("mug of eggnog", (250, 235, 190)),
            "hook": ("candy cane fish hook", (255, 120, 120)),
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
