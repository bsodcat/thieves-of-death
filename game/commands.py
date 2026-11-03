"""The test console: commands typed into the game while it runs.

Commands change the real game on the server, so only a player on the server's own computer
may use them (see `Player.can_command`), and everyone in the game is told when one runs.
Add a command by writing a function and listing it in COMMANDS.
"""
from __future__ import annotations

from .constants import LAST_FLOOR, STAMINA_MAX, STEALTH_MAX
from .entities import MONSTERS
from .items import ITEMS, make_amulet, make_cloak, make_item, make_key, make_staff, make_wand
from .seasons import dress_item
from .tiles import LOCK_COLORS

MAX_DEPTH = LAST_FLOOR
MAX_SPAWN = 20
MAX_GOLD = 1_000_000
GRAY = (160, 160, 160)
GOOD = (140, 230, 140)
BAD = (255, 110, 110)


class Refused(Exception):
    """Something wrong with what was typed. Its message goes back to the console."""


def number(text: str, low: int, high: int) -> int:
    try:
        value = int(text)
    except ValueError:
        raise Refused(f"{text[:20]} isn't a number.") from None
    if not low <= value <= high:
        raise Refused(f"Use a number from {low} to {high}.")
    return value


def pick(name: str, choices, what: str) -> str:
    """The choice matching a name, which may be just the start of it."""
    name = name.lower()
    if name in choices:
        return name
    found = [c for c in choices if c.startswith(name)]
    if len(found) == 1:
        return found[0]
    if found:
        raise Refused(f"Which {what}? " + ", ".join(found))
    raise Refused(f"No {what} called {name[:20]}. Try: list")


def item_names() -> list[str]:
    return [*ITEMS, "cloak", "wand", "staff", "amulet", "gold", *(f"{color}_key" for color in LOCK_COLORS)]


def make(kind: str, depth: int):
    if kind == "cloak":
        return make_cloak()
    if kind == "wand":
        return make_wand()
    if kind == "staff":
        return make_staff()
    if kind == "amulet":
        return make_amulet()
    if kind.endswith("_key"):
        return make_key(kind[:-4], depth)  # fits this floor's door, if it has one
    return make_item(kind)


def alive(p) -> None:
    if not p.alive:
        raise Refused("You have to be alive for that.")


def show_help(w, p, args) -> list[str]:
    """Two columns, to fit the console. `help give` says what one command does."""
    if args:
        _, usage, what = COMMANDS[pick(args[0], COMMANDS, "command")]
        return [f"{usage}: {what}"]
    usages = [usage for _, usage, _ in COMMANDS.values()]
    half = (len(usages) + 1) // 2
    return [left.ljust(34) + right for left, right in zip(usages[:half], usages[half:] + [""])]


def give(w, p, args) -> str:
    if not args:
        raise Refused("give <item> [count]")
    kind = pick(args[0], item_names(), "item")
    if kind == "gold":  # a count of gold is an amount, not a number of items
        return gold(w, p, args[1:] or ["100"])
    count = number(args[1], 1, 99) if len(args) > 1 else 1
    for _ in range(count):
        item = dress_item(make(kind, p.depth), w.season)
        if not w._stash(p, item):
            raise Refused("Your pack is full.")
    p.pack_dirty = True
    return f"Gave you {count} x {item.name}."


def gold(w, p, args) -> str:
    if not args:
        raise Refused("gold <amount>")
    p.gold = min(MAX_GOLD, p.gold + number(args[0], 1, MAX_GOLD))
    p.pack_dirty = True
    return f"You have {p.gold} gold."


def heal(w, p, args) -> str:
    alive(p)
    p.hp, p.stamina = p.max_hp, STAMINA_MAX
    return "Health and stamina are full."


def god(w, p, args) -> str:
    p.god = not p.god
    return f"God mode is {'on' if p.god else 'off'}."


def collision(w, p, args) -> str:
    alive(p)
    on = pick(args[0], ("on", "off"), "setting") == "on" if args else p.noclip
    p.noclip = not on
    lvl = w.levels[p.depth]
    locked_in = lvl.lock is not None and lvl.vault[p.x, p.y]
    if on and (locked_in or not w._can_be_at(p, lvl, p.x, p.y)):
        lvl.move(p, *lvl.nearest_floor(p.x, p.y, lvl.occupant))
    return f"Collision is {'on' if on else 'off'}."


def goto(w, p, args) -> str:
    alive(p)
    if not args:
        raise Refused("goto <floor>")
    w.warp(p, number(args[0], 1, MAX_DEPTH))
    return f"You're on floor {p.depth}."


def floor(w, p, args) -> str:
    if not args:
        raise Refused("floor <number> [player]")
    depth = number(args[0], 1, MAX_DEPTH)
    target = p
    if len(args) > 1:
        players = {q.name.lower(): q for q in w.players.values()}
        target = players[pick(" ".join(args[1:]), players, "player")]
    if not target.alive:
        raise Refused(f"{target.name} has to be alive for that.")
    w.warp(target, depth)
    if target is not p:
        w.tell(target, f"{p.name} moved you to floor {depth}.", GOOD)
    return f"{target.name} is on floor {depth}."


def summon(w, p, args) -> str:
    """Brings another player, or everyone else, to stand beside you."""
    alive(p)
    others = {q.name.lower(): q for q in w.players.values() if q is not p}
    if not others:
        raise Refused("There's nobody else here.")
    targets = [others[pick(" ".join(args), others, "player")]] if args else list(others.values())
    moved = []
    for q in targets:
        if not q.alive:
            continue
        w.bring(q, p)
        w.tell(q, f"{p.name} brought you to them.", GOOD)
        moved.append(q.name)
    if not moved:
        raise Refused("Only living players can be brought over.")
    return f"Brought {', '.join(moved)} to you."


def spawn(w, p, args) -> str:
    alive(p)
    if not args:
        raise Refused("spawn <monster, cult or nest> [count]")
    lvl = w.levels[p.depth]
    if args[0].lower() == "cult":
        return "A cult has gathered on this floor." if w._add_cult(lvl, force=True) else "There's no room for a cult here."
    if args[0].lower() == "nest":
        return ("A spider queen has nested on this floor." if w._add_spiders(lvl, force=True)
                else "There's no room for a nest here.")
    kind = pick(args[0], MONSTERS, "monster")
    count = number(args[1], 1, MAX_SPAWN) if len(args) > 1 else 1
    for _ in range(count):
        m = w._new_monster(kind)
        m.state, m.next_time = "wandering", w.clock
        lvl.place(m, *lvl.free_near(p.x, p.y))
        lvl.monsters.append(m)
    return f"Spawned {count} x {m.name}."


def killall(w, p, args) -> str:
    lvl = w.levels[p.depth]
    count = len(lvl.monsters)
    for m in list(lvl.monsters):
        w._kill(m, p if p.alive else None)
    return f"Killed {count} monsters."


def reveal(w, p, args) -> str:
    p.reveal = not p.reveal
    return f"Reveal is {'on: all maps, monsters and items are marked' if p.reveal else 'off'}."


def ultrabright(w, p, args) -> str:
    p.bright = not p.bright
    return f"Ultrabright is {'on' if p.bright else 'off'}."


def stealth(w, p, args) -> str:
    if not args:
        raise Refused("stealth <0-100>")
    p.stealth = min(p.stealth_cap, number(args[0], 0, STEALTH_MAX))
    return f"Stealth is {int(p.stealth)}."


def teleport(w, p, args) -> str:
    alive(p)
    w.teleport(p)
    return f"You're at {p.x}, {p.y}."


def info(w, p, args) -> list[str]:
    lvl = w.levels[p.depth]
    rooms = ", ".join(f"{r.color} on {r.depth}, key on {r.key_depth}" for r in w.locked_rooms.values())
    cloaks = ", ".join(map(str, sorted(w.cloak_floors)))
    return [f"Seed {w.seed}, run {w.run}, {w.difficulty}, season {w.season or 'none'}",
            f"Floor {p.depth} at {p.x}, {p.y}: {len(lvl.monsters)} monsters, {len(lvl.items)} items",
            f"Locked rooms: {rooms or 'none'}",
            f"Cloaks on floors not built yet: {cloaks or 'none'}"]


# How `list` sorts items: a heading and the item categories under it. Anything else goes under Other.
ITEM_GROUPS = (("Weapons", ("weapon",)), ("Ranged", ("ranged", "ammo", "bomb")), ("Armor", ("armor",)),
               ("Potions", ("potion",)), ("Magic", ("wand",)))
EXTRA_GROUPS = {"cloak": "Armor", "wand": "Magic", "staff": "Magic"}  # made by hand, not from ITEMS
LIST_LABEL, LIST_COLUMN, LIST_COLUMNS = 10, 19, 3
HEADING = (235, 215, 130)


def table(label: str, names: list[str]) -> list[str]:
    """Names in even columns, with the label at the start of the first row."""
    rows = [names[i:i + LIST_COLUMNS] for i in range(0, len(names), LIST_COLUMNS)]
    return [(label if i == 0 else "").ljust(LIST_LABEL) + "".join(n.ljust(LIST_COLUMN) for n in row).rstrip()
            for i, row in enumerate(rows)]


def item_groups() -> dict[str, list[str]]:
    groups = {label: [] for label, _ in ITEM_GROUPS} | {"Other": []}
    category = {cat: label for label, cats in ITEM_GROUPS for cat in cats}
    for kind in item_names():
        entry = ITEMS.get(kind)
        label = category.get(entry.get("category"), "Other") if entry else EXTRA_GROUPS.get(kind, "Other")
        groups[label].append(kind)
    return {label: names for label, names in groups.items() if names}


def list_names(w, p, args) -> list:
    """Items by kind and monsters, in columns. `list items` or `list monsters` shows one."""
    which = pick(args[0], ("items", "monsters"), "list") if args else None
    lines = []
    if which in (None, "items"):
        lines.append(("Items - give <item> [count]", HEADING))
        for label, names in item_groups().items():
            lines += table(label, names)
    if which in (None, "monsters"):
        lines.append(("Monsters - spawn <monster> [count], spawn cult or spawn nest", HEADING))
        lines += table("", sorted(MONSTERS))
    return lines


# name -> (function, usage, what it does)
COMMANDS = {
    "help": (show_help, "help [command]", "List the commands, or explain one"),
    "list": (list_names, "list [items|monsters]", "List item and monster names"),
    "info": (info, "info", "Seed, floor, locked rooms and cloaks"),
    "give": (give, "give <item> [count]", "Put an item, or gold, in your pack"),
    "gold": (gold, "gold <amount>", "Add gold"),
    "heal": (heal, "heal", "Fill your health and stamina"),
    "god": (god, "god", "Take no damage, on or off"),
    "collision": (collision, "collision [on|off]", "Walk through walls, enemies and hazards"),
    "goto": (goto, "goto <floor>", "Go to any floor"),
    "floor": (floor, "floor <number> [player]", "Move you, or another player, to a floor"),
    "summon": (summon, "summon [player]", "Bring a player, or everyone, to you"),
    "spawn": (spawn, "spawn <monster> [count]", "Add monsters; cult or nest adds a group"),
    "killall": (killall, "killall", "Kill every monster on this floor"),
    "reveal": (reveal, "reveal", "Map floors, mark monsters and items"),
    "ultrabright": (ultrabright, "ultrabright", "Light up every floor, on or off"),
    "stealth": (stealth, "stealth <0-100>", "Set your stealth"),
    "teleport": (teleport, "teleport", "Jump to another part of this floor"),
    "clear": (None, "clear", "Empty this console"),
}


def run(w, p, text: str) -> None:
    """Runs a line typed by a player, and sends the results to their console."""
    def reply(line: str, color=GRAY) -> None:
        w.outbox.append((p.id, {"t": "console", "text": line, "c": list(color)}))

    words = str(text).split()[:8]
    if not words:
        return
    if not p.can_command:
        reply("Only someone playing on the host's computer can use commands.", BAD)
        return
    try:
        name = pick(words[0], [c for c, entry in COMMANDS.items() if entry[0]], "command")
        result = COMMANDS[name][0](w, p, words[1:])
    except Refused as why:
        reply(str(why), BAD)
        return
    for line in [result] if isinstance(result, str) else result:
        reply(*line) if isinstance(line, tuple) else reply(line, GOOD)  # a tuple brings its own color
    w.dirty = True
    if name not in ("help", "list", "info"):
        w.note(p, "CONSOLE " + " ".join(words))
        for q in w.players.values():
            if q is not p:
                w.tell(q, f"{p.name} used the console: {' '.join(words)[:60]}", GRAY)
