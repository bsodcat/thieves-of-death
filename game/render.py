"""Client-side view: what this player knows, drawn into a frame buffer.

Nothing here imports tcod. The frame uses the same layout as a tcod
console's `rgb` array (ch / fg / bg, indexed [x, y]), so client.py just
copies it onto a tcod Console. That also lets the tests render screenshots
without a window.
"""
from __future__ import annotations

import math
import random
import re
import textwrap
import time
from collections import deque

import numpy as np

from . import commands, controls, pathing, protocol, seasons
from .constants import (ATTACK_STAMINA, BONES_GLYPH, BOOMERANG_TILE_SECONDS, LOOK_Y, MAP_H, MAP_W, MAP_X, MAP_Y,
                        MSG_LINES, PACK_SIZE, REVIVE_SECONDS, SCREEN_H, SCREEN_W, SIDEBAR_W, STAMINA_MAX, STEALTH_MAX,
                        TICKS_PER_TURN, VICTORY_SECONDS)
from .entities import MONSTERS
from .tiles import (ALTAR, BG, DEEP, DESCRIPTIONS, FG, GLYPH, LAVA, NAMES, POND, SHALLOW, STAIRS_DOWN, STAIRS_UP,
                    TOWER_WALL, WALKABLE, WALL)

FRAME_DTYPE = np.dtype([("ch", np.int32), ("fg", "3u1"), ("bg", "3u1")])

TEXT = (220, 220, 220)
PANEL_BG = (20, 20, 34)
DIM = (130, 130, 140)
HEADING = (180, 170, 140)
HELP_LINES = (
    ("Arrows, {keys}{letters}", "Move or attack; hold to keep going"),
    ("Two arrows together", "Move diagonally"),
    ("Hold {sprint}", "Sprint, while you have the stamina"),
    ("Walk into > or <", "Take the stairs"),
    ("1-9, 0, or {heal}", "Use a pack slot, or quick heal"),
    ("{pack} or {tally}", "Show or hide your pack, or your tally"),
    ("{drop}, then 1-0 or $", "Drop an item, or 25 gold"),
    ("Mouse", "Point to identify, hold right to walk"),
    ("{pickup} or {log}", "Pick up, or show the action log"),
    ("Enter, or ` or F2", "Chat, or the test console (host only)"),
    ("{help} or F1, Esc", "Show or hide this help, or close a panel"),
    ("{quit} twice", "Leave the game"),
)
VI_KEYS = "hjklyubn"      # they walk, unless given another job in Controls
HELP_TIPS = (
    "Stand still to build stealth. Attacks empty it; gear limits it.",
    "Monsters notice you from further away in torchlight.",
    "Hold {sprint} to sprint. It burns stamina and stealth fast.",
    "With too little stamina, your attacks take twice as long.",
    "Stamina only refills once you stop spending it.",
    "A sneak attack on an unaware monster does triple damage.",
    "Walk over potions and gold to collect them. Gear needs {pickup}.",
    "A key always lies 2 floors from its door, above or below.",
    "A pit is a quick way down, but the fall hurts.",
    "Levitation carries you over water and pits, but not forever.",
    "Deep water stops monsters too. Put a lake between you.",
    "Some rooms are cut off by water, and hold what nobody can reach.",
    "Stuck on an island? You can always swim back. It's slow.",
    "Merchants can turn up on every 5th floor.",
    "Spending gold lowers your score, but it might keep you alive.",
    "Health comes back by itself, so a quiet corner can save you.",
    "In Revive mode, stand by a teammate's bones for 3 seconds.",
    "Walk into an ally to swap places with them.",
    "Hold right click to walk to the pointer, around walls.",
    "Only equipped gear makes noise. Carrying it is free.",
    "Each player has a cloak out there. Wear one to hide better.",
    "Strike a sleeper with 30% stealth for a critical hit.",
    "Cultists come in packs. Their leader carries a wand of fire.",
    "Ranged weapons aim at the strongest foe. Change it in Options.",
    "A boomerang needs no ammo, but a bow reaches further.",
    "Skeleton archers back away. Corner them, or block their view.",
    "Slime trails poison you and slow you down. Step around them.",
    "The necromancer's side rooms hide a hoard and a potion store.",
    "Past floor 50, a pit might drop you straight into lava.",
    "Score is gold times kills, divided by your moves.",
    "Merchants buy gear for half price. Tab switches to selling.",
    "A bomb breaks a cracked wall, and there's a room behind it.",
    "A fisherman on an early floor knows where keys lie.",
    "Monkeys stole the fisherman's hooks. He rewards their return.",
    "A barrel of food heals you quickly for a few seconds.",
    "Fire spreads through grass. Burning monsters run when hurt.",
    "A floating cultist mage can only be hit from range.",
    "A boomerang has to come back before you can throw it again.",
    "A lone kobold runs. A kobold leader's spear reaches 2 tiles.",
    "Mushrooms never move, but don't get close without a plan.",
    "The goal: the Amulet on floor 99, out through floor 1.",
    "Wake the necromancer and flee, and the dead follow you up.",
    "A wand of frost holds an enemy still for 30 seconds.",
    "Walk through tall grass to see what's beyond it.",
    "A potion of teleportation could land you on any floor at all.",
    "A pond of healing heals you once, and wards you against magic.",
    "A ward sends magic back at whoever cast it.",
    "The skeletal dragon on floor 80 breathes fire along a line.",
    "Magic armor turns up on floors 60 to 70. It reflects magic.",
    "Toxic gas only spreads 4 tiles. Back away, or shut a door.",
    "Cultists guard altars. One use each, and the weapon keeps it.",
    "An altar's gift hurts the undead more, and an altar's ghost.",
    "Water and lava walking potions turn up around floors 20 to 40.",
)

LOOK_HINT = "Point the mouse at the map to identify what's there."
HOVER_BG = (70, 70, 100)
TORCH_GLOW = np.array((70, 38, 8), np.float32)    # added to the background at full brightness
TORCH_TEXT = (255, 180, 70)
DEATH_BG = (40, 10, 10)
BOLT_SECONDS = 0.35
FLAME = (255, 120, 20)
BOLT_COLORS = {"fire": FLAME, "blink": (230, 120, 255), "frost": (150, 215, 255), "sparkle": (150, 255, 240),
               "bow": (225, 215, 180), "lightning": (200, 160, 255), "blast": (255, 150, 40), "rock": (150, 140, 128),
               "web": (215, 215, 225), "leap": (120, 90, 140)}
WEB_GLYPH, WEB_FG, WEB_BG = ord(":"), (215, 215, 228), (38, 36, 44)   # a spider web, over the ground
SPIN = "/-\\|"               # a thrown boomerang turns through these
SPIN_COLOR = (235, 190, 100)
SPIN_TILE_SECONDS = BOOMERANG_TILE_SECONDS   # how long it takes to cross a tile, out and back
# What monsters leave where they die: (background, glyph or None, glyph color).
STAIN_LOOKS = {"blood": ((80, 8, 10), None, None), "goo": ((30, 90, 22), None, None),
               "rot": ((52, 58, 24), None, None), "spores": ((70, 54, 34), None, None),
               "bones": ((40, 38, 32), ord(","), (205, 200, 175))}
FIRE_FG, FIRE_BG = ((255, 210, 70), (255, 120, 30)), (120, 34, 6)
BOMB_COLORS = ((255, 80, 60), (255, 230, 200))
MAGE_GLOW = np.array((120, 40, 200), np.float32)
NPC_LABELS = {"sleeping": "asleep", "merchant": "shop", "fisherman": "talk", "fairy": "fairy"}
SCROLL_PAUSE, SCROLL_SPEED = 1.2, 5.0   # a name too long to fit waits, then scrolls this many letters a second
SPIN_TURN_SECONDS = 0.05   # how long each glyph shows
# A kobold leader's spear: drawn across the tile between it and you, it lunges into your tile
# from SPEAR_LUNGE seconds in until SPEAR_BACK, and is gone at SPEAR_SECONDS.
SPEAR_COLOR = (230, 40, 40)
SPEAR_LUNGE, SPEAR_BACK, SPEAR_SECONDS = 0.07, 0.2, 0.3
# Things thrown or shot without magic fly across one tile at a time, instead of flashing:
# kind -> (glyph, or None for an arrow pointing the way it flies, color, seconds per tile).
FLIGHTS = {"bow": (None, (225, 215, 180), 0.025), "rock": ("*", (165, 155, 140), 0.05),
           "fireball": ("*", (255, 140, 40), 0.045), "web": (":", (215, 215, 228), 0.05)}
SPARKLE = (90, 240, 220)
# Each animated tile cycles through glyphs that look alike: (tile, glyphs, steps a second).
RIPPLES = ((DEEP, (0x2248, ord("~"), 0x2248, 0x2248), 3), (SHALLOW, (ord("~"), 0x2248, ord("~"), ord("-")), 2),
           (LAVA, (0x2248, ord("~"), 0x2591, 0x2248), 4), (POND, (0x2248, ord("*"), ord("~"), 0xB7), 6))
ICE = (70, 130, 190)
AURA = np.array((165, 60, 250), np.float32)      # added to the background right beside an altar
AURA_RADIUS = 5.0
ULTRABRIGHT = 1.5
PACK_WIDTH = 62
SHOP_WIDTH = 70           # room for the longest item info and a price beside it
PACK_HOVER = (45, 45, 70)
LOG_KEPT = 2000           # lines of the action log kept for reading in the game
LOG_ROWS, LOG_ROWS_DEAD, LOG_SCROLL = 12, 26, 6  # it's only tall once there's nobody to keep in view
WHEEL_LINES = 3           # lines a notch of the mouse wheel scrolls
LOG_WRAP_INDENT = 10      # lines it wraps line up under the text, past the time
LOG_LOUD = (255, 150, 110)
LOUD_LOG = re.compile(r" (DIED|DOWN|WON|RUN OVER|CONSOLE|ERROR)\b")
WARNING_START = 0.3       # the share of a swing gone before it starts to blink
WARNING_BLINKS = 2.6      # how fast the blinking speeds up: more is more frantic
WARNING_DIM = 0.45        # how bright a monster stays in the dark part of a blink
HIT_RED = np.array((230, 35, 25), np.float32)     # at the center of a blow
HIT_RADIUS, HIT_SECONDS = 2.5, 0.35
WATER_GLOW = np.array((30, 95, 190), np.float32)
LAVA_GLOW = np.array((190, 85, 15), np.float32)
WALK_GLOW_RADIUS = 6.0    # fades out here, so the 5th tile away is the last one lit
WALK_GLOW_FADE = 55.0     # the seconds left on the potion when the glow starts to fade
ARMOR_GLOW = np.array((50, 110, 240), np.float32)
ARMOR_PULSE = 0.7         # how fast magic armor pulses: 0.7 is one pulse in about 9 seconds
WARD_GLOW = np.array((35, 90, 235), np.float32)   # a pond's ward
WARD_GLOW_RADIUS = 3.5
MARK_MONSTER, MARK_ITEM = (150, 30, 45), (125, 105, 15)   # behind whatever reveal is showing you
GAS = np.array((50, 120, 30), np.float32)
WIN_BG = (30, 26, 6)
SLIME_BG = (32, 70, 26)
VAULT_WALL_FG, VAULT_WALL_BG = 0.85, 0.22   # a locked room's walls: its key's color, as glyph and ground
VAULT_WALL_MEMORY = 0.3                     # and how bright they stay once out of sight
SLOWED_TEXT = (150, 220, 110)
CONSOLE_WIDTH, CONSOLE_ROWS = 72, 14
CONSOLE_TITLE = "Test console. Type help for commands, wheel scrolls, Esc closes"
CONSOLE_CLOSE = "[x]"
CONSOLE_SUGGESTIONS = 6                   # completions shown at once, above the typing line
SUGGEST_BG, LINK_BG = (40, 40, 70), (60, 60, 105)
WORD = re.compile(r"[A-Za-z0-9_]+")
WALK_ON_WATER, WALK_ON_LAVA = (120, 190, 255), (255, 130, 40)
XS, YS = np.indices((MAP_W, MAP_H))
FLOAT_DIM, FLOAT_BRIGHT, FLOAT_SHADOW = (30, 50, 110), (90, 150, 240), (6, 6, 14)
FLOAT_TEXT = (190, 170, 255)
STATE_NAMES = {"sleeping": "Asleep", "wandering": "Wandering", "hunting": "Hunting you"}

STATUS_COLORS = {"go": (140, 230, 140), "revive": (255, 215, 90), "dead": (255, 100, 100),
                 "over": (255, 100, 100)}


def scale(color, k: float) -> tuple:
    return tuple(int(max(0, min(255, c * k))) for c in color)


def format_clock(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02}:{secs:02}" if hours else f"{minutes:02}:{secs:02}"


class ClientView:
    def __init__(self, config: dict | None = None) -> None:
        self.my_id: int | None = None
        self.name = ""
        self.run = None
        self.depth = 1
        self.levels: dict[int, np.ndarray] = {}   # depth -> tiles
        self.seen: dict[int, np.ndarray] = {}     # depth -> tiles this player has ever seen
        self.visible = np.zeros((MAP_W, MAP_H), dtype=bool)
        self.ents: list[dict] = []
        self.item_memory: dict[int, dict] = {}    # depth -> {(x, y): item last seen there}
        self.pack: list[dict] = []
        self.gold = self.defense = 0
        self.dmg = ""
        self.haste = False
        self.stealth = 0
        self.stealth_cap = STEALTH_MAX
        self.detect = 0                           # how far away monsters can notice you, in tiles
        self.stamina = STAMINA_MAX
        self.lit = False                          # standing in torchlight
        self.lights: dict[int, np.ndarray] = {}   # depth -> brightness 0 to 1, [torch, x, y]
        self.tips: list[str] = []                 # the tips still to come, so none repeats early
        self.tip = HELP_TIPS[0]
        self._walk_key = None                     # what the last auto-walk step was worked out from
        self._walk_step = None
        self.show_help = False
        self.show_tally = False
        self.show_log = False
        self.keys = controls.labels(controls.load(config or {}))  # the player's keys, as shown on screen
        self.log: deque[str] = deque(maxlen=LOG_KEPT)  # the action log, as far back as we keep
        self.log_back = 0                         # lines scrolled up from the newest
        self.log_run: tuple | None = None
        self.log_path = ""                        # the file it's being saved to
        self.season = None
        self.shop: list | None = None             # the merchant's stock while you're at the shop
        self.shop_name = ""
        self.shop_pos = (0, 0)
        self.shop_selling = False                 # the shop shows your pack, to sell from
        self.stains: dict[int, dict] = {}         # depth -> {(x, y): what a monster left there}
        self.difficulty = ""                      # the host's, from the welcome
        self.revive_seconds = REVIVE_SECONDS      # how long a teammate stands by the fallen
        self.vault_walls: dict[int, tuple] = {}   # depth -> (walls around its locked room, key color)
        self.webs: dict[int, set] = {}            # depth -> spider webs, remembered like the map
        self.webbed = False                       # a spider queen's web holds you
        self.venom = 0.0                          # seconds of spider venom left
        self.fire: list = []                      # burning tiles in sight
        self.bombs: list = []                     # lit bombs in sight
        self.fed = False                          # a meal is healing you
        self.levitate = False
        self.waterwalk = self.lavawalk = False
        self.bolts: list[tuple] = []              # (tiles, when, color) of magic still on screen
        self.hits: list[tuple] = []               # (x, y, when) of blows still showing
        self.throws: list[tuple] = []             # (tiles, when) of boomerangs in the air
        self.spears: list[tuple] = []             # (tiles, when, glyph) of spear thrusts
        self.flights: list[tuple] = []            # (tiles, when, glyph, color, seconds a tile, what fell) in the air
        self.gas: list = []                       # tiles of toxic gas in sight
        self.slime: list = []                     # tiles of slime trail in sight
        self.slowed = self.toxin = False
        self.prompt: dict | None = None           # a yes or no question waiting for an answer
        self.bright = False                       # console: draw the whole floor fully lit
        self.victory = ""                         # who won the run
        self.console_open = False
        self.console_buf = ""
        self.console_log: deque = deque(maxlen=200)
        self.console_history: list[str] = []
        self.console_back = 0                     # how far back up the history you've gone
        self.console_scroll = 0                   # lines scrolled up from the newest
        self.console_tab: tuple | None = None     # (what was typed, what Tab made of it, which choice) while cycling
        self.score = self.score_gold = 0
        self.tally: dict = {}                     # monster name -> kills
        self.hardest = ""
        self.mouse: tuple[int, int] | None = None  # the screen cell under the pointer
        self.show_pack = False
        self.drop_mode = False
        self.leave_prompt = ""                    # shown while confirming leaving the game
        self.clock_base = 0.0                     # run time in the last state...
        self.clock_at = time.monotonic()          # ...and when it arrived
        self.party: list[dict] = []
        self.status = ["", "Connecting..."]
        self.alive = True
        self.downed = False
        self.death = ""
        self.turns = self.kills = 0
        self.messages: deque = deque(maxlen=100)
        self.chat_mode = False
        self.chat_buf = ""
        self.connected = True

    # ------------------------------------------------------------ network

    def apply(self, msg: dict) -> None:
        t = msg.get("t")
        if t == "welcome":
            self.my_id, self.name = msg["id"], msg["name"]
            self.difficulty = msg.get("difficulty", "")
            self.revive_seconds = msg.get("revive") or REVIVE_SECONDS  # only shown when the fallen can be revived
        elif t == "level":
            if msg.get("run") != self.run:  # new dungeon: forget the old map
                self.run = msg.get("run")
                self.levels.clear()
                self.seen.clear()
                self.item_memory.clear()
                self.lights.clear()
                self.stains.clear()
                self.webs.clear()
            shape = (msg["w"], msg["h"])
            self.levels[msg["depth"]] = protocol.unpack_u8(msg["tiles"], shape)
            self.lights[msg["depth"]] = [protocol.unpack_u8(m, shape) / 255 for m in msg.get("lights", ())]
            self.seen.setdefault(msg["depth"], np.zeros(shape, dtype=bool))
            self.stains[msg["depth"]] = {(x, y): kind for x, y, kind in msg.get("stains", ())}
            self.webs[msg["depth"]] = {tuple(c) for c in msg.get("webs", ())}
            vault = msg.get("vault")
            if vault:  # a locked room's walls, in its key's color
                walls = np.zeros(shape, dtype=bool)
                for x, y in vault["cells"]:
                    walls[x, y] = True
                self.vault_walls[msg["depth"]] = (walls, np.array(vault["c"], np.float32))
            else:
                self.vault_walls.pop(msg["depth"], None)
        elif t == "tiles":
            tiles = self.levels.get(msg["depth"])
            if tiles is not None:
                for x, y, tile in msg["cells"]:
                    tiles[x, y] = tile
        elif t == "webs":
            self.webs[msg["depth"]] = {tuple(c) for c in msg["cells"]}
        elif t == "stains":
            here = self.stains.setdefault(msg["depth"], {})
            for x, y, kind in msg["cells"]:
                here[(x, y)] = kind
        elif t == "tip":
            self.messages.append((f'{msg.get("who", "Someone")} says: "{self._key_text(self._next_tip())}"',
                                  (150, 255, 240)))
        elif t == "state":
            self.depth = msg["depth"]
            self.visible = protocol.unpack_bool(msg["visible"], (MAP_W, MAP_H))
            self.bright = msg.get("bright", False)
            if self.depth in self.seen:
                self.seen[self.depth] |= self.visible
                if msg.get("reveal"):
                    self.seen[self.depth][:] = True
            memory = self.item_memory.setdefault(self.depth, {})
            if msg.get("reveal"):
                memory.clear()  # everything on the floor is about to be reported
            for pos in [pos for pos in memory if self.visible[pos]]:
                del memory[pos]  # visible tiles are about to be reported afresh
            for item in msg.get("items", ()):
                memory[(item["x"], item["y"])] = item
            self.ents, self.party, self.status = msg["ents"], msg["party"], msg["status"]
            me = self.me()
            if me is not None and max(abs(me["x"] - self.shop_pos[0]), abs(me["y"] - self.shop_pos[1])) > 1:
                self.shop = None  # walked away
            if me is not None and self.prompt and max(abs(me["x"] - self.prompt["x"]),
                                                      abs(me["y"] - self.prompt["y"])) > 1:
                self.prompt = None
            self.alive, self.death = msg["alive"], msg.get("death", "")
            self.downed = msg.get("downed", False)
            self.turns, self.kills = msg.get("turns", 0), msg.get("kills", 0)
            self.haste, self.stealth = msg.get("haste", False), msg.get("stealth", 0)
            self.score, self.score_gold = msg.get("score", 0), msg.get("score_gold", 0)
            self.tally, self.hardest = msg.get("tally", {}), msg.get("hardest", "")
            self.season = msg.get("season")
            self.levitate = msg.get("levitate", False)
            self.gas, self.victory = msg.get("gas", ()), msg.get("victory", "")
            self.slime, self.slowed, self.toxin = msg.get("slime", ()), msg.get("slowed", False), msg.get("toxin", False)
            self.webbed, self.venom = msg.get("webbed", False), msg.get("venom", 0.0)
            self.waterwalk, self.lavawalk = msg.get("waterwalk", False), msg.get("lavawalk", False)
            self.stamina, self.lit = msg.get("stamina", STAMINA_MAX), msg.get("lit", False)
            self.detect = msg.get("detect", 0)
            self.fire, self.bombs, self.fed = msg.get("fire", ()), msg.get("bombs", ()), msg.get("fed", False)
            self.clock_base, self.clock_at = msg.get("time", 0.0), time.monotonic()
        elif t == "shop":
            if self.shop is None:
                self.shop_selling = False
            self.shop, self.shop_name, self.shop_pos = msg["stock"], msg["name"], (msg["x"], msg["y"])
            self.show_pack = self.drop_mode = self.show_help = self.show_tally = self.show_log = False
        elif t == "fx" and msg.get("kind") == "boomerang":
            out = [tuple(c) for c in msg["cells"]]
            fell = msg.get("fell")  # the monster it killed, shown until the boomerang reaches it
            self.throws.append((out + out[-2::-1], time.monotonic(),  # out to the target, and back
                                (*out[-1], fell["g"], tuple(fell["c"])) if fell else None))
        elif t == "fx" and msg.get("kind") in FLIGHTS:
            cells = [tuple(c) for c in msg["cells"]]
            glyph, color, pace = FLIGHTS[msg["kind"]]
            fell = msg.get("fell")  # the monster it killed, shown until it gets there
            self.flights.append((cells, time.monotonic(), glyph or self.arrow(msg.get("from"), cells), color, pace,
                                 (*cells[-1], fell["g"], tuple(fell["c"])) if fell and cells else None))
        elif t == "fx" and msg.get("kind") == "spear":
            cells = [tuple(c) for c in msg["cells"]]
            self.spears.append((cells, time.monotonic(), self.arrow(msg.get("from"), cells)))
        elif t == "fx" and msg.get("kind") == "hit":
            self.hits += [(x, y, time.monotonic()) for x, y in msg["cells"]]
        elif t == "fx":
            self.bolts.append((msg["cells"], time.monotonic(), BOLT_COLORS.get(msg.get("kind"), FLAME)))
        elif t == "console":
            for line in textwrap.wrap(msg["text"], CONSOLE_WIDTH - 4, replace_whitespace=False, drop_whitespace=False):
                self.console_log.append((line, tuple(msg.get("c", TEXT))))
                self.console_scroll += 1 if self.console_scroll else 0  # stay put while reading
        elif t == "prompt":
            self.prompt = msg
        elif t == "reject":
            self.messages.append((msg["text"], (255, 90, 90)))
        elif t == "pack":
            self.pack, self.gold, self.defense = msg["pack"], msg["gold"], msg["defense"]
            self.dmg, self.stealth_cap = msg["dmg"], msg.get("stealth_cap", STEALTH_MAX)
        elif t == "msg":
            self.messages.append((msg["text"], tuple(msg.get("c", TEXT))))
        elif t == "log":
            self._add_log(msg)
        elif t == "_disconnected":
            self.connected = False
            self.messages.append(("Disconnected from the server.", (255, 90, 90)))

    def _add_log(self, msg: dict) -> None:
        if "head" not in msg:
            self.log.append(msg["line"])
            self.log_back = self.log_back + 1 if self.log_back else 0  # stay put while reading
        elif (msg["run"], msg["seed"]) != self.log_run:
            self.log_run = msg["run"], msg["seed"]
            self.log.clear()
            self.log_back = 0
            self.log.append(msg["head"])

    def log_rows(self) -> int:
        return LOG_ROWS if self.alive or self.downed else LOG_ROWS_DEAD

    def toggle_log(self) -> None:
        self.show_log = not self.show_log
        self.log_back = 0
        self.show_pack = self.drop_mode = self.show_help = self.show_tally = False

    def scroll_log(self, step: int, lines: int = LOG_SCROLL) -> None:
        """Up shows older lines. It stops with the oldest line at the top of the panel."""
        self.log_back = max(0, min(len(self.log) - self.log_rows(), self.log_back + step * lines))

    def wheel(self, notches: int) -> None:
        """The mouse wheel scrolls whichever is on top, away from you showing older lines."""
        if self.console_open:
            rows = CONSOLE_ROWS - 2
            self.console_scroll = max(0, min(len(self.console_log) - rows, self.console_scroll + notches * WHEEL_LINES))
        elif self.show_log:
            self.scroll_log(notches, WHEEL_LINES)

    def console_submit(self) -> str:
        """Takes the typed line. Returns what to send the server, if anything."""
        text, self.console_buf, self.console_back = self.console_buf.strip(), "", 0
        self.console_scroll = 0
        if not text:
            return ""
        self.console_history.append(text)
        if text.lower() == "clear":
            self.console_log.clear()
            return ""
        self.console_log.append((f"> {text}"[:CONSOLE_WIDTH - 4], DIM))
        return text

    def console_recall(self, step: int) -> None:
        """Up and down arrows: older or newer lines you've typed."""
        self.console_back = max(0, min(len(self.console_history), self.console_back + step))
        self.console_buf = self.console_history[-self.console_back] if self.console_back else ""

    def console_players(self) -> list[str]:
        names = [self.name, *(q["name"] for q in self.party)]
        return list(dict.fromkeys(n for n in names if n))

    def console_suggestions(self) -> tuple[str, int, list[str], int]:
        """The completions for what's typed: (the text they finish, where its last word starts,
        the choices, the highlighted one). Pressing Tab again keeps the same list and moves on."""
        cycling = self.console_tab is not None and self.console_buf == self.console_tab[1]
        base = self.console_tab[0] if cycling else self.console_buf
        start, found = commands.complete(base, self.console_players())
        if found == [base[start:]]:
            found = []  # already typed in full
        return base, start, found, self.console_tab[2] if cycling else 0

    def console_complete(self, choice: int | None = None) -> None:
        """Tab: finish the word with the highlighted completion; again for the next one. A click picks one."""
        base, start, found, at = self.console_suggestions()
        if not found:
            return
        cycling = self.console_tab is not None and self.console_buf == self.console_tab[1]
        at = choice if choice is not None else (at + 1) % len(found) if cycling else 0
        self.console_buf = (base[:start] + found[at] + " ")[:200]
        self.console_tab = (base, self.console_buf, at) if choice is None and len(found) > 1 else None

    def _console_lines(self) -> list:
        end = len(self.console_log) - self.console_scroll
        return list(self.console_log)[max(0, end - (CONSOLE_ROWS - 2)):end]

    def _suggestion_cells(self) -> list[tuple]:
        """Where each completion shown sits: (x, y, width, which choice, text)."""
        base, start, found, at = self.console_suggestions()
        if not found:
            return []
        x0, y0 = self._panel_pos(CONSOLE_WIDTH, CONSOLE_ROWS)
        first = max(0, at - CONSOLE_SUGGESTIONS + 1)
        shown = found[first:first + CONSOLE_SUGGESTIONS]
        width = max(map(len, shown)) + 2
        x = x0 + 2 + min(2 + start, CONSOLE_WIDTH - 4 - width)
        top = y0 + CONSOLE_ROWS - 1 - len(shown)
        return [(x, top + j, width, first + j, name) for j, name in enumerate(shown)]

    def _console_word_at(self, tile) -> tuple | None:
        """The word under the pointer in the console's title or text: (word, x, y)."""
        x0, y0 = self._panel_pos(CONSOLE_WIDTH, CONSOLE_ROWS)
        x, y = tile
        lines = self._console_lines()
        line = CONSOLE_TITLE if y == y0 else lines[y - y0 - 1][0] if 0 <= y - y0 - 1 < len(lines) else ""
        for m in WORD.finditer(line[:CONSOLE_WIDTH - 4]):
            if m.start() <= x - x0 - 2 < m.end():
                return m.group(), x0 + 2 + m.start(), y
        return None

    def console_link(self, tile) -> tuple | None:
        """What a click there would do: ("close" | "help" | "pick" | "fill", detail, x, y, width),
        or None if nothing."""
        if tile is None:
            return None
        x0, y0 = self._panel_pos(CONSOLE_WIDTH, CONSOLE_ROWS)
        x, y = tile
        if not (x0 <= x < x0 + CONSOLE_WIDTH and y0 <= y < y0 + CONSOLE_ROWS - 1):
            return None
        for sx, sy, width, at, _ in self._suggestion_cells():
            if y == sy and sx <= x < sx + width:
                return "pick", at, sx, sy, width
        close_x = x0 + CONSOLE_WIDTH - 1 - len(CONSOLE_CLOSE)
        if y == y0 and close_x <= x < close_x + len(CONSOLE_CLOSE):
            return "close", None, close_x, y, len(CONSOLE_CLOSE)
        found = self._console_word_at(tile)
        if found is None:
            return None
        word, wx, wy = found
        if wy == y0:
            return ("help", None, wx, wy, len(word)) if word == "help" else None
        filled = commands.clicked_word(self.console_buf, word, self.console_players())
        return ("fill", filled, wx, wy, len(word)) if filled else None

    def console_click(self, tile) -> str | None:
        """A left click in the open console. Returns "close", or a command to run straight away."""
        link = self.console_link(tile)
        if link is None:
            return None
        kind, detail = link[:2]
        if kind == "pick":
            self.console_complete(detail)
        elif kind == "fill":
            self.console_buf, self.console_tab = detail[:200], None
        elif kind == "help":
            return "help"
        elif kind == "close":
            return "close"
        return None

    def toggle_help(self) -> None:
        """Each time the help opens it shows the next tip, in a shuffled order."""
        self.show_help = not self.show_help
        self.show_pack = self.drop_mode = self.show_tally = self.show_log = False
        if self.show_help:
            self._next_tip()

    def _next_tip(self) -> str:
        if not self.tips:
            self.tips = random.sample([t for t in HELP_TIPS if t != self.tip], len(HELP_TIPS) - 1)
        self.tip = self.tips.pop()
        return self.tip

    def toggle_selling(self) -> None:
        """Tab, at a shop: between what the merchant sells and what you could sell them."""
        if self.shop is not None:
            self.shop_selling = not self.shop_selling

    @staticmethod
    def fit(s: str, width: int) -> str:
        """A name that fits, or one that's too long, scrolled along so all of it gets seen.
        It waits at the start, scrolls to the end, waits there, and starts over."""
        if len(s) <= width or width <= 0:
            return s
        extra = len(s) - width
        run = extra / SCROLL_SPEED
        t = time.monotonic() % (SCROLL_PAUSE * 2 + run)
        start = min(extra, max(0, int((t - SCROLL_PAUSE) * SCROLL_SPEED)))
        return s[start:start + width]

    def me(self) -> dict | None:
        return next((e for e in self.ents if e["id"] == self.my_id), None)

    def walk_step(self, x: int, y: int) -> tuple[int, int] | None:
        """The next step of an auto-walk to map tile (x, y), using only what this player knows."""
        me = self.me()
        tiles = self.levels.get(self.depth)
        if me is None or tiles is None or not self.alive:
            return None
        goal, start = (x, y), (me["x"], me["y"])
        if goal == start:
            return None
        seen = self.seen[self.depth]
        others = {(e["x"], e["y"]) for e in self.ents  # allies don't count: you walk past them
                  if e["id"] != self.my_id and e["st"] != "down" and e["seen"] and not e["p"]}
        stairs = tiles[x, y] == STAIRS_DOWN or (tiles[x, y] == STAIRS_UP and self.depth > 1)
        key = (id(tiles), start, goal, frozenset(others), int(seen.sum()))
        if key != self._walk_key:  # this is asked every frame, but the answer rarely changes
            self._walk_key = key
            self._walk_step = pathing.next_step(WALKABLE[tiles] & seen, start, goal, others,
                                                bool(stairs and seen[x, y]))
        return self._walk_step

    def clock(self) -> float:
        """Run time in seconds. Counts on smoothly between states from the server."""
        return self.clock_base + (time.monotonic() - self.clock_at if self.connected else 0.0)

    # ------------------------------------------------------------ drawing

    def draw(self) -> np.ndarray:
        f = np.zeros((SCREEN_W, SCREEN_H), dtype=FRAME_DTYPE)
        f["ch"] = ord(" ")
        self._draw_map(f)
        self._draw_sidebar(f)
        self._draw_look(f)
        self._draw_messages(f)
        self._draw_footer(f)
        if self.show_pack or self.drop_mode:
            self._draw_pack(f)
        if self.victory:
            self._draw_victory(f)
        elif not self.alive:
            self._draw_death(f)
        if self.shop is not None:
            self._draw_shop(f)
        if self.show_tally:
            self._draw_tally(f)
        if self.show_log:
            self._draw_log(f)
        if self.show_help:
            self._draw_help(f)
        if self.prompt:
            self._draw_prompt(f)
        if self.console_open:
            self._draw_console(f)
        return f

    @staticmethod
    def text(f, x: int, y: int, s: str, fg=TEXT, bg=None, width: int | None = None) -> None:
        if width is not None:
            s = s[:width]
        for i, c in enumerate(s):
            if 0 <= x + i < SCREEN_W and 0 <= y < SCREEN_H:
                f["ch"][x + i, y] = ord(c)
                f["fg"][x + i, y] = fg
                if bg is not None:
                    f["bg"][x + i, y] = bg

    def bar(self, f, x: int, y: int, w: int, frac: float, label: str, color) -> None:
        """Brogue-style bar: the background fills up, the label sits on top."""
        filled = int(round(w * max(0.0, min(1.0, frac))))
        label = label[:w].center(w)
        for i in range(w):
            bg = color if i < filled else scale(color, 0.25)
            self.text(f, x + i, y, label[i], (255, 255, 255), bg)

    def _draw_map(self, f) -> None:
        tiles = self.levels.get(self.depth)
        if tiles is None:
            return
        seen, vis = self.seen[self.depth], self.visible
        ch = GLYPH[tiles]
        fg = FG[tiles].astype(np.float32)
        bg = BG[tiles].astype(np.float32)
        ch, fg, bg = self._animate(tiles, ch, fg, bg)
        walls, color = self.vault_walls.get(self.depth, (None, None))
        if walls is not None:
            walls = (walls & (tiles == WALL))[..., None]  # only while they're still walls
            fg = np.where(walls, color * VAULT_WALL_FG, fg)
            bg = np.where(walls, color * VAULT_WALL_BG, bg)
        me = self.me()
        if me is not None:  # gentle light falloff around you
            light = np.clip(1.15 - np.hypot(XS - me["x"], YS - me["y"]) / 28.0, 0.55, 1.0)[..., None]
        else:
            light = 1.0
        if self.bright:
            seen = vis = np.ones((MAP_W, MAP_H), dtype=bool)
            light = ULTRABRIGHT
        # Remembered tiles: dark and bluish, like Brogue's magic-mapped memory.
        mem_fg = fg.mean(axis=-1, keepdims=True) * 0.32 + np.array([12, 14, 34], np.float32)
        mem_bg = bg * 0.22 + np.array([0, 0, 10], np.float32)
        if walls is not None:  # remembered in color too, dimmer, so you can find the room again
            mem_fg = np.where(walls, color * VAULT_WALL_MEMORY, mem_fg)
        v, s = vis[..., None], seen[..., None]
        lit_fg, lit_bg = fg * light, bg * light
        glow = self._torchlight()
        if glow is not None:
            lit_fg = lit_fg * (1 + 0.6 * glow)
            lit_bg = lit_bg * (1 + 0.8 * glow) + glow * TORCH_GLOW
        for x, y in np.argwhere(tiles == ALTAR):
            pulse = 0.75 + 0.25 * math.sin(time.monotonic() * 3 + x)
            lit_bg = lit_bg + (np.clip(1 - np.hypot(XS - x, YS - y) / AURA_RADIUS, 0, 1) * pulse)[..., None] * AURA
        lit_bg = self._add_glows(lit_bg)
        out_fg = np.where(v, lit_fg, np.where(s, mem_fg, 0))
        out_bg = np.where(v, lit_bg, np.where(s, mem_bg, 0))
        area = (slice(MAP_X, MAP_X + MAP_W), slice(MAP_Y, MAP_Y + MAP_H))
        f["ch"][area] = np.where(vis | seen, ch, ord(" "))
        f["fg"][area] = np.clip(out_fg, 0, 255).astype(np.uint8)
        f["bg"][area] = np.clip(out_bg, 0, 255).astype(np.uint8)

        for (x, y), kind in self.stains.get(self.depth, {}).items():
            if not (vis[x, y] or seen[x, y]):
                continue
            bg_color, glyph, glyph_color = STAIN_LOOKS.get(kind, STAIN_LOOKS["blood"])
            dim = 1.0 if vis[x, y] else 0.35  # remembered, like the rest of the map
            f["bg"][MAP_X + x, MAP_Y + y] = scale(bg_color, dim)
            if glyph is not None:
                f["ch"][MAP_X + x, MAP_Y + y] = glyph
                f["fg"][MAP_X + x, MAP_Y + y] = scale(glyph_color, dim)

        for x, y in self.slime:
            f["bg"][MAP_X + x, MAP_Y + y] = SLIME_BG

        for x, y in self.webs.get(self.depth, ()):
            if vis[x, y] or seen[x, y]:
                dim = 1.0 if vis[x, y] else 0.35  # remembered, like the rest of the map
                f["ch"][MAP_X + x, MAP_Y + y] = WEB_GLYPH
                f["fg"][MAP_X + x, MAP_Y + y] = scale(WEB_FG, dim)
                f["bg"][MAP_X + x, MAP_Y + y] = scale(WEB_BG, dim)

        for x, y, thickness in self.gas:  # fades to nothing, and thins to specks on the way
            share = thickness / 9
            at = (MAP_X + x, MAP_Y + y)
            f["bg"][at] = np.clip(f["bg"][at] * (1 - 0.5 * share) + GAS * share, 0, 255).astype(np.uint8)
            if thickness > 1:
                f["ch"][at] = 0x2592 if thickness > 5 else 0x2591
                f["fg"][at] = np.clip(GAS * (0.6 + share), 0, 255).astype(np.uint8)

        now = time.monotonic()
        for x, y in self.fire:  # flames that flicker, each tile on its own
            flick = math.sin(now * 13 + x * 1.7 + y * 2.3)
            f["ch"][MAP_X + x, MAP_Y + y] = ord("^") if flick > -0.3 else 0x2591
            f["fg"][MAP_X + x, MAP_Y + y] = FIRE_FG[flick > 0.4]
            f["bg"][MAP_X + x, MAP_Y + y] = scale(FIRE_BG, 0.8 + 0.3 * flick)

        for (x, y), item in self.item_memory.get(self.depth, {}).items():
            f["ch"][MAP_X + x, MAP_Y + y] = ord(item["g"])
            f["fg"][MAP_X + x, MAP_Y + y] = item["c"] if vis[x, y] or item.get("hl") else scale(item["c"], 0.45)
            if item.get("hl"):
                f["bg"][MAP_X + x, MAP_Y + y] = MARK_ITEM

        # Monsters first, then allies, then you on top.
        for e in sorted(self.ents, key=lambda e: (e["p"], e["id"] == self.my_id)):
            if e["seen"]:
                color = e["c"]
            elif e["p"]:
                color = scale(e["c"], 0.45)  # ally out of sight: you still sense them
            else:
                continue
            f["ch"][MAP_X + e["x"], MAP_Y + e["y"]] = ord(e["g"])
            f["fg"][MAP_X + e["x"], MAP_Y + e["y"]] = color
            if e.get("hl"):
                f["bg"][MAP_X + e["x"], MAP_Y + e["y"]] = MARK_MONSTER
            if self.blinked_off(e):
                f["fg"][MAP_X + e["x"], MAP_Y + e["y"]] = scale(color, WARNING_DIM)
            if e.get("lev"):
                self._draw_float(f, e)
            if e.get("burn"):
                f["bg"][MAP_X + e["x"], MAP_Y + e["y"]] = scale(FLAME, 0.7 + 0.3 * math.sin(time.monotonic() * 11))
            if e.get("frozen"):
                f["bg"][MAP_X + e["x"], MAP_Y + e["y"]] = ICE
        for x, y in self.bombs:  # its fuse blinks faster than anything else on the map
            f["ch"][MAP_X + x, MAP_Y + y] = 0x3B4
            f["fg"][MAP_X + x, MAP_Y + y] = BOMB_COLORS[int(now * 8) % 2]
        self._draw_bolts(f)
        self._draw_throws(f)
        self._draw_flights(f)
        self._draw_spears(f)

        hover = self.hovered()
        if hover is not None:
            f["bg"][MAP_X + hover[0], MAP_Y + hover[1]] = HOVER_BG

    @staticmethod
    def _animate(tiles, ch, fg, bg) -> tuple:
        """Water and lava ripple, with each tile a step out from its neighbors, and the
        tower's walls glow and fade."""
        now = time.monotonic()
        wave = np.sin(XS * 0.6 + YS * 0.9 + now * 3)[..., None]
        for tile, glyphs, speed in RIPPLES:
            here = tiles == tile
            if here.any():
                step = (XS * 3 + YS * 5 + int(now * speed)) % len(glyphs)
                ch = np.where(here, np.array(glyphs)[step], ch)
                fg = np.where(here[..., None], fg * (1 + 0.25 * wave), fg)
                bg = np.where(here[..., None], bg * (1 + 0.2 * wave), bg)
        walls = (tiles == TOWER_WALL)[..., None]
        if walls.any():
            glow = 0.85 + 0.15 * math.sin(now * 1.5)
            fg, bg = np.where(walls, fg * glow, fg), np.where(walls, bg * glow, bg)
        return ch, fg, bg

    def _draw_throws(self, f) -> None:
        """One tile at a time from the thrower to the target, spinning all the way. A monster it
        killed stays in view until the boomerang reaches it."""
        now = time.monotonic()
        self.throws = [t for t in self.throws if now - t[1] < len(t[0]) * SPIN_TILE_SECONDS]
        for cells, thrown, fell in self.throws:
            flown = now - thrown
            if fell and flown < (len(cells) // 2) * SPIN_TILE_SECONDS:  # the target is the middle tile
                x, y, glyph, color = fell
                f["ch"][MAP_X + x, MAP_Y + y] = ord(glyph)
                f["fg"][MAP_X + x, MAP_Y + y] = color
            x, y = cells[int(flown / SPIN_TILE_SECONDS)]
            f["ch"][MAP_X + x, MAP_Y + y] = ord(SPIN[int(flown / SPIN_TURN_SECONDS) % len(SPIN)])
            f["fg"][MAP_X + x, MAP_Y + y] = SPIN_COLOR

    @staticmethod
    def arrow(start, cells) -> str:
        """An arrow's glyph, pointing the way it flies."""
        if not cells:
            return "-"
        sx, sy = start if start else cells[0]
        dx, dy = cells[-1][0] - sx, cells[-1][1] - sy
        if abs(dx) >= 2 * abs(dy):
            return "-"
        if abs(dy) >= 2 * abs(dx):
            return "|"
        return "\\" if (dx > 0) == (dy > 0) else "/"

    def _draw_flights(self, f) -> None:
        """Arrows, rocks and the like, a tile at a time from whoever threw them to where they land.
        Anything it killed stays in view until it gets there."""
        now = time.monotonic()
        self.flights = [t for t in self.flights if now - t[1] < len(t[0]) * t[4]]
        for cells, thrown, glyph, color, pace, fell in self.flights:
            flown = now - thrown
            if fell and flown < (len(cells) - 1) * pace:
                x, y, g, c = fell
                f["ch"][MAP_X + x, MAP_Y + y] = ord(g)
                f["fg"][MAP_X + x, MAP_Y + y] = c
            x, y = cells[int(flown / pace)]
            f["ch"][MAP_X + x, MAP_Y + y] = ord(glyph)
            f["fg"][MAP_X + x, MAP_Y + y] = color

    def spear_cells(self, cells, age: float) -> list:
        """The tiles a spear thrust covers this long after it began: the shaft across the gap,
        and the point in the target's tile while it lunges."""
        if age >= SPEAR_SECONDS:
            return []
        shaft = list(cells[:-1])
        return shaft + list(cells[-1:]) if SPEAR_LUNGE <= age < SPEAR_BACK else shaft

    def _draw_spears(self, f) -> None:
        now = time.monotonic()
        self.spears = [s for s in self.spears if now - s[1] < SPEAR_SECONDS]
        for cells, thrust, glyph in self.spears:
            for x, y in self.spear_cells(cells, now - thrust):
                f["ch"][MAP_X + x, MAP_Y + y] = ord(glyph)
                f["fg"][MAP_X + x, MAP_Y + y] = SPEAR_COLOR

    def _draw_bolts(self, f) -> None:
        now = time.monotonic()
        self.bolts = [b for b in self.bolts if now - b[1] < BOLT_SECONDS]
        for cells, fired, color in self.bolts:
            heat = 1 - (now - fired) / BOLT_SECONDS
            for x, y in cells:
                f["bg"][MAP_X + x, MAP_Y + y] = scale(color, heat)

    def blinked_off(self, e: dict) -> bool:
        """Whether a monster about to hit you is in the dark part of its blink, which comes
        exponentially faster as the moment gets close."""
        if "strike" not in e:
            return False
        left = e["strike"] - (time.monotonic() - self.clock_at)
        share = 1 - left / e["swing"]
        return WARNING_START < share < 1 and math.cos(math.exp(share * WARNING_BLINKS)) < 0

    def _add_glows(self, bg: np.ndarray) -> np.ndarray:
        """Light that moves with people, and the red that shows where a player struck."""
        now = time.monotonic()
        for e in self.ents:
            for potion, color in (("wet", WATER_GLOW), ("hot", LAVA_GLOW)):
                if e.get(potion):
                    left = e[potion] - (now - self.clock_at)
                    reach = np.clip(1 - np.hypot(XS - e["x"], YS - e["y"]) / WALK_GLOW_RADIUS, 0, 1)
                    reach = reach * min(max(left, 0.0) / WALK_GLOW_FADE, 1.0)
                    bg = bg + (reach * (0.85 + 0.15 * math.sin(now * 2)))[..., None] * color
            if e.get("ward"):
                reach = np.clip(1 - np.hypot(XS - e["x"], YS - e["y"]) / WARD_GLOW_RADIUS, 0, 1) ** 1.5
                bg = bg + (reach * (0.8 + 0.2 * math.sin(now * 1.5)))[..., None] * WARD_GLOW
            if e.get("float") and e.get("seen"):  # a cultist mage, glowing violet up in the air
                reach = np.clip(1 - np.hypot(XS - e["x"], YS - e["y"]) / 2.5, 0, 1)
                bg = bg + (reach * (0.75 + 0.25 * math.sin(now * 4)))[..., None] * MAGE_GLOW
            if e.get("aura"):
                near = np.maximum(abs(XS - e["x"]), abs(YS - e["y"])) <= 1
                reach = near * (1 - np.hypot(XS - e["x"], YS - e["y"]) / 2)
                bg = bg + (reach * (0.7 + 0.3 * math.sin(now * ARMOR_PULSE)))[..., None] * ARMOR_GLOW
        self.hits = [h for h in self.hits if now - h[2] < HIT_SECONDS]
        for x, y, struck in self.hits:
            reach = np.clip(1 - np.hypot(XS - x, YS - y) / HIT_RADIUS, 0, 1)
            bg = bg + (reach * (1 - (now - struck) / HIT_SECONDS))[..., None] * HIT_RED
        return bg

    def _torchlight(self) -> np.ndarray | None:
        """How brightly torches light each tile right now, with each one flickering by itself."""
        maps = self.lights.get(self.depth)
        if not maps:
            return None
        t = time.monotonic()
        glow = sum(m * (0.8 + 0.12 * math.sin(t * 9 + i * 2.1) + 0.08 * math.sin(t * 23 + i)) for i, m in enumerate(maps))
        return np.clip(glow, 0, 1.2)[..., None]

    @staticmethod
    def _draw_float(f, e: dict) -> None:
        """A levitating player: a slow blue pulse, and a shadow on the ground below them."""
        pulse = (math.sin(time.monotonic() * 5) + 1) / 2
        f["bg"][MAP_X + e["x"], MAP_Y + e["y"]] = tuple(int(a + (b - a) * pulse)
                                                        for a, b in zip(FLOAT_DIM, FLOAT_BRIGHT))
        if e["y"] + 1 < MAP_H:
            f["bg"][MAP_X + e["x"], MAP_Y + e["y"] + 1] = FLOAT_SHADOW

    # --------------------------------------------------------------- look

    def hovered(self) -> tuple[int, int] | None:
        """The map tile under the pointer, if it's over the map."""
        if self.mouse is None:
            return None
        x, y = self.mouse[0] - MAP_X, self.mouse[1] - MAP_Y
        return (x, y) if 0 <= x < MAP_W and 0 <= y < MAP_H else None

    def _describe_actor(self, e: dict) -> list:
        color = tuple(e["c"])
        if e["st"] == "merchant":
            return [(f"{e['g']} {e['name'].capitalize()}", color),
                    ("Walk into them to see what's for sale, or to sell.", TEXT)]
        if e["st"] == "fisherman":
            return [(f"{e['g']} Fisherman", color), ("Walk into him to talk. He knows where keys lie, and wants his hooks back.", TEXT)]
        if e["st"] == "fairy":
            return [(f"{e['g']} Fairy", color), ("Trapped down here. Walk into it to free it.", TEXT)]
        if e["st"] == "down":
            if e["id"] == self.my_id:
                return [(f"{e['g']} Your bones", color), ("A teammate can stand here to revive you.", TEXT)]
            return [(f"{e['g']} {e['name']}'s bones", color),
                    (f"Stand next to them for {self.revive_seconds:.0f} seconds to revive them.", TEXT)]
        if e["p"]:
            name = "You" if e["id"] == self.my_id else e["name"]
            lines = [(f"{e['g']} {name}", color), (f"Health {e['hp']}/{e['mhp']}", TEXT)]
            if e.get("lev"):
                lines.append(("Levitating", FLOAT_TEXT))
            if e.get("ward") or e.get("aura"):
                lines.append(("Reflecting magic", SPARKLE))
            return lines
        lines = [(f"{e['g']} {e['name'].capitalize()}", color),
                 (f"Health {e['hp']}/{e['mhp']}", TEXT),
                 (STATE_NAMES.get(e["st"], ""), (255, 170, 80) if e["st"] == "hunting" else DIM)]
        kind = e.get("kind") or e["name"]
        t = MONSTERS.get(kind)
        if t:
            speed = " Fast." if t["move"] < TICKS_PER_TURN else ""
            speed += " Slow hits." if t["attack"] > TICKS_PER_TURN else ""
            desc = seasons.monster_description(kind, self.season, t["desc"])
            hits = f" Hits for {t['damage'][0]}-{t['damage'][1]}." if t["damage"][1] else ""
            lines.append((f"{desc}{hits}{speed}", TEXT))
        if e.get("float"):
            lines.append(("Floating: out of melee reach", (190, 140, 255)))
        if e.get("burn"):
            lines.append(("On fire", FLAME))
        if e.get("frozen"):
            lines.append(("Frozen solid", ICE))
        return lines

    def _describe_item(self, item: dict, in_sight: bool) -> list:
        how = "Walk over it to collect." if item.get("auto") else f"Stand on it and press {self.keys['pickup']}."
        lines = [(f"{item['g']} {item['name'].capitalize()}", tuple(item["c"]))]
        if item.get("info"):
            lines.append((item["info"].capitalize(), TEXT))
        lines.append((how if in_sight else "As you remember it.", DIM))
        return lines

    def describe(self, x: int, y: int) -> list:
        """What the player knows about a map tile, as (text, color) lines."""
        tiles = self.levels.get(self.depth)
        seen = self.seen.get(self.depth)
        if tiles is None or seen is None or not (seen[x, y] or self.bright):
            actor = next((e for e in self.ents if (e["x"], e["y"]) == (x, y)), None)
            if actor is None:
                return [("Unexplored", DIM), ("You haven't seen this yet.", DIM)]
            return self._describe_actor(actor)  # an ally you can sense through walls
        lines = []
        for e in self.ents:
            if (e["x"], e["y"]) == (x, y) and (e["seen"] or e["p"]):
                lines += self._describe_actor(e)
        in_sight = bool(self.visible[x, y]) or self.bright
        item = self.item_memory.get(self.depth, {}).get((x, y))
        if item is not None:
            lines += self._describe_item(item, in_sight)
        tile = int(tiles[x, y])
        if not lines and (x, y) in self.webs.get(self.depth, ()):
            return [(f"{chr(WEB_GLYPH)} Spider web", WEB_FG),
                    ("Sticky strands. Walk into it and it slows you down. Fire burns it away."
                     + ("" if in_sight else " As you remember it."), DIM)]
        if not lines:
            lines.append((NAMES[tile].capitalize(), TEXT))
            lines.append((DESCRIPTIONS[tile] + ("" if in_sight else " As you remember it."), DIM))
        return lines

    def _draw_look(self, f) -> None:
        w = SIDEBAR_W
        for x in range(w):
            f["bg"][x, LOOK_Y:SCREEN_H] = (14, 14, 22)
        self.text(f, 1, LOOK_Y, "Look", HEADING)
        hover = self.hovered()
        lines = self.describe(*hover) if hover is not None else [(LOOK_HINT, DIM)]
        y = LOOK_Y + 1
        for text, color in lines:
            for part in textwrap.wrap(text, w - 2):
                if y < SCREEN_H:
                    self.text(f, 1, y, part, color)
                y += 1

    def _draw_sidebar(self, f) -> None:
        w = SIDEBAR_W
        y = 0
        me = next((p for p in self.party if p["id"] == self.my_id), None)
        if me:
            self.text(f, 1, y, self.fit(me["name"], w - 1), tuple(me["c"]))
            y += 1
            health = (70, 130, 40) if self.toxin else (160, 30, 30)  # green while poisoned
            self.bar(f, 0, y, w, me["hp"] / me["mhp"], f"Health {me['hp']}/{me['mhp']}", health)
            y += 1
            cap = self.stealth_cap
            label = f"Stealth {self.stealth}%" + (f" max {cap}" if cap < STEALTH_MAX else "")
            self.bar(f, 0, y, w, self.stealth / STEALTH_MAX, label, (60, 70, 170))
            f["bg"][round(w * cap / STEALTH_MAX):w, y] = (70, 24, 24)  # out of reach in this gear
            y += 1
            tired = " Tired" if self.stamina < ATTACK_STAMINA else ""
            self.bar(f, 0, y, w, self.stamina / STAMINA_MAX, f"Stamina {self.stamina}%{tired}", (150, 120, 30))
            y += 1
            clock = f"Time {format_clock(self.clock())}"
            self.text(f, 1, y, clock, (255, 255, 255))
            if self.haste:
                self.text(f, len(clock) + 2, y, "Haste", (120, 220, 255))
            elif self.webbed:
                self.text(f, len(clock) + 2, y, "Webbed", WEB_FG)
            elif self.slowed:
                self.text(f, len(clock) + 2, y, "Slowed", SLOWED_TEXT)
            elif self.venom:
                self.text(f, len(clock) + 2, y, f"Venom {math.ceil(self.venom)}s", (150, 200, 90))
            elif self.fed:
                self.text(f, len(clock) + 2, y, "Fed", (255, 215, 90))
            y += 1
            self.text(f, 1, y, f"Depth {self.depth}  Gold {self.gold}", TEXT, width=w - 1)
            y += 1
            self.text(f, 1, y, f"Dmg {self.dmg}  Armor {self.defense}", TEXT, width=w - 1)
            y += 1
            if self.lit:
                self.text(f, 1, y, f"Torchlit: {self.detect} tiles", TORCH_TEXT, width=w - 1)
            else:
                self.text(f, 1, y, f"Detection {self.detect} tiles", TEXT, width=w - 1)
            y += 1
            self.text(f, 1, y, f"Moves {self.turns}  Kills {self.kills}", DIM, width=w - 1)
            y += 1
            score = f"Score {self.score}"
            self.text(f, 1, y, score, (255, 215, 90), width=w - 1)
            if self.levitate:
                self.text(f, max(len(score) + 2, 13), y, "Float", FLOAT_TEXT)
            y += 1

        if self.party:
            self.text(f, 1, y, "Players", HEADING)
            if self.waterwalk:
                self.text(f, 9, y, "Water", WALK_ON_WATER)
            if self.lavawalk:
                self.text(f, 15, y, "Lava", WALK_ON_LAVA)
            y += 1
            for q in self.party:
                if y >= LOOK_Y - 2:
                    break
                self.text(f, 1, y, q.get("g", "@"), tuple(q["c"]))
                self.text(f, 3, y, self.fit(q["name"], w - 4), TEXT)
                y += 1
                ping = "--" if q.get("ping") is None else f"{q['ping']}ms"
                fallen = "  down" if q.get("down") else "  dead"
                tail, frac = (fallen, 0.0) if not q["alive"] else ("", q["hp"] / q["mhp"])
                label = f"Floor {q['depth']}  {ping}{tail}"
                if len(label) > w:
                    label = label.replace("  ", " ")
                self.bar(f, 0, y, w, frac, label, (40, 110, 60))
                y += 1
            y += 1

        me_e = self.me()
        mons = [e for e in self.ents if not e["p"] and e["seen"] and (not e.get("hl") or self.visible[e["x"], e["y"]])]
        if me_e:
            mons.sort(key=lambda e: max(abs(e["x"] - me_e["x"]), abs(e["y"] - me_e["y"])))
        for e in mons:
            if y >= LOOK_Y - 2:
                break
            self.text(f, 1, y, e["g"], tuple(e["c"]))
            self.text(f, 3, y, self.fit(e["name"], w - 3), TEXT)
            y += 1
            label = NPC_LABELS.get(e["st"], "")
            if e.get("float"):
                label = "floating"
            friendly = e["st"] in ("merchant", "fisherman", "fairy")
            self.bar(f, 0, y, w, e["hp"] / e["mhp"], label, (130, 100, 30) if friendly else (130, 40, 40))
            y += 1

    def _draw_messages(self, f) -> None:
        recent = list(self.messages)[-MSG_LINES:]
        start = MSG_LINES - len(recent)
        for i, (text, color) in enumerate(recent):
            age = len(recent) - 1 - i
            self.text(f, MAP_X, start + i, text, scale(color, (1.0, 0.7, 0.5)[age]), width=MAP_W)

    def _draw_footer(self, f) -> None:
        y = MAP_Y + MAP_H
        if not self.connected:
            self.text(f, MAP_X, y, "Disconnected. Press Esc to leave.", (255, 90, 90))
        elif self.leave_prompt:
            self.text(f, MAP_X, y, self.leave_prompt, (255, 215, 90), width=MAP_W)
        else:
            kind, text = (self.status + ["", ""])[:2]
            self.text(f, MAP_X, y, text, STATUS_COLORS.get(kind, TEXT), width=MAP_W)
        if self.chat_mode:
            self.text(f, MAP_X, y + 1, "Say: " + self.chat_buf[-(MAP_W - 7):] + "_", (255, 255, 255))
        else:
            self.text(f, MAP_X, y + 1,
                      self._key_text("{keys}/arrows  {heal} heal  {pack} pack  {tally} tally  {log} log  "
                                     "{drop} drop  {pickup} get  {help} help  {quit} quit"),
                      DIM, width=MAP_W)

    def _draw_pack(self, f) -> None:
        """The game keeps running behind this, so it stays clear of you; see _panel_pos."""
        bw, panel_bg = PACK_WIDTH, PANEL_BG
        rows = PACK_SIZE + 4
        x0, y0 = self._panel_pos(bw, rows)
        title = ("Drop what? 1-0 or click, $ for gold, Esc cancels" if self.drop_mode
                 else self._key_text("Pack: 1-0 or click to use, {sort} sorts, {pack} closes"))
        hovered = self.pack_slot_at(self.mouse) if self.mouse else None
        for j in range(rows):
            self.text(f, x0, y0 + j, " " * bw, TEXT, panel_bg)
        self.text(f, x0 + 2, y0 + 1, title, HEADING, width=bw - 4)
        for i in range(PACK_SIZE):
            y = y0 + 2 + i
            self.text(f, x0 + 2, y, str((i + 1) % 10), DIM)
            if i >= len(self.pack):
                continue
            item = self.pack[i]
            if i == hovered:
                self.text(f, x0 + 1, y, " " * (bw - 2), TEXT, PACK_HOVER)
            self.text(f, x0 + 2, y, str((i + 1) % 10), DIM)
            self.text(f, x0 + 4, y, item["g"], tuple(item["c"]))
            note = item["info"] + (" (on)" if item["eq"] else "")
            room = bw - 9 - len(note)
            if room < 12:  # a long note gives way to the name, and is cut short
                note, room = note[:bw - 9 - 12 - 1] + "~" if len(note) > bw - 9 - 12 else note, 12
            self.text(f, x0 + 6, y, self.fit(item["name"], room), (255, 255, 255) if item["eq"] else TEXT)
            self.text(f, x0 + bw - 2 - len(note), y, note, DIM)
        self.text(f, x0 + 2, y0 + rows - 1, f"{self.gold} {seasons.gold_name(self.season)}", (255, 215, 90))
        note = f"Equipped gear limits stealth to {self.stealth_cap}%"
        self.text(f, x0 + bw - 2 - len(note), y0 + rows - 1, note, DIM)

    def pack_slot_at(self, tile: tuple[int, int] | None) -> int | None:
        """The pack slot at a place on the screen, if the pack is open and there's an item there."""
        if tile is None or not (self.show_pack or self.drop_mode):
            return None
        x0, y0 = self._panel_pos(PACK_WIDTH, PACK_SIZE + 4)
        slot = tile[1] - y0 - 2
        return slot if x0 <= tile[0] < x0 + PACK_WIDTH and 0 <= slot < len(self.pack) else None

    def _key_text(self, text: str) -> str:
        """Fills in the player's own keys. {keys} is their four movement keys, if that's short."""
        keys = self.keys
        moves = keys["up"] + keys["left"] + keys["down"] + keys["right"]
        letters = "".join(c for c in VI_KEYS if c not in keys.values())  # any reassigned no longer walk
        return text.format(**keys, keys=moves if len(moves) == 4 else "keys", letters=", " + letters if letters else "")

    def _panel_pos(self, width: int, height: int) -> tuple[int, int]:
        """Where a panel goes to leave your character in view.
        Panels are under half the map's height, so taking the
        half your character is not in always clears away from you."""
        me = self.me()
        x = MAP_X if me is not None and me["x"] >= MAP_W // 2 else MAP_X + MAP_W - width
        y = MAP_Y + MAP_H - height if me is not None and me["y"] < MAP_H // 2 else MAP_Y
        return x, y

    def score_line(self) -> str:
        return f"Score {self.score}  ({self.score_gold} gold x {self.kills} kills / {self.turns} moves)"

    def tally_lines(self) -> list[str]:
        hardest = self.hardest or "none yet"
        return [self.score_line(), f"Kills {self.kills}   Hardest enemy fought: {hardest}"]

    def _draw_tally(self, f) -> None:
        kills = sorted(self.tally.items(), key=lambda kv: (-kv[1], kv[0]))
        bw, rows = 66, min(14, 6 + (len(kills) + 2) // 3)
        x0, y0 = self._panel_pos(bw, rows)
        for j in range(rows):
            self.text(f, x0, y0 + j, " " * bw, TEXT, PANEL_BG)
        self.text(f, x0 + 2, y0, "Tally: t closes", HEADING)
        self.text(f, x0 + 2, y0 + 1, self.score_line(), (255, 215, 90), width=bw - 4)
        self.text(f, x0 + 2, y0 + 2, f"Hardest enemy fought: {self.hardest or 'none yet'}", TEXT, width=bw - 4)
        self.text(f, x0 + 2, y0 + 3, f"Kills: {self.kills}", TEXT)
        per_column = rows - 5
        for j, (name, count) in enumerate(kills[:per_column * 3]):  # three columns hold every monster there is
            x, y = x0 + 2 + 21 * (j // per_column), y0 + 4 + j % per_column
            self.text(f, x, y, name, TEXT, width=16)
            self.text(f, x + 17, y, f"{count}", (255, 255, 255))

    def _draw_log(self, f) -> None:
        shown = self.log_rows()
        bw, rows = MAP_W, shown + 2
        x0, y0 = self._panel_pos(bw, rows) if shown == LOG_ROWS else (MAP_X, MAP_Y + (MAP_H - rows) // 2)
        for j in range(rows):
            self.text(f, x0, y0 + j, " " * bw, TEXT, PANEL_BG)
        self.text(f, x0 + 2, y0, self._key_text("Action log: up, down or the wheel scroll, {log} or Esc closes"), HEADING)
        for j, (row, color) in enumerate(self._log_lines(shown, bw - 4)):
            self.text(f, x0 + 2, y0 + 1 + j, row, color)
        self.text(f, x0 + 2, y0 + rows - 1, self._log_where(bw - 4), DIM)

    def _log_lines(self, shown: int, width: int) -> list:
        """The rows of text to show, with long lines wrapped. If that's too many, it keeps the
        newest while following the log, and the oldest while scrolled back, so scrolling either
        way can reach every line."""
        end = len(self.log) - self.log_back
        rows = []
        for line in list(self.log)[max(0, end - shown):end]:
            color = LOG_LOUD if LOUD_LOG.search(line) else TEXT
            parts = textwrap.wrap(line, width, subsequent_indent=" " * LOG_WRAP_INDENT) or [""]
            rows += [(part, color) for part in parts]
        return rows[:shown] if self.log_back else rows[-shown:]

    def _log_where(self, width: int) -> str:
        """The file it's saved to, keeping the end if it's too long, as that's the part that differs."""
        path = self.log_path or "Not saving to a file."
        return path if len(path) <= width else "..." + path[3 - width:]

    def _draw_shop(self, f) -> None:
        if self.shop_selling:
            self._draw_selling(f)
            return
        bw, rows = SHOP_WIDTH, len(self.shop) + 4 if self.shop else 5
        x0, y0 = self._panel_pos(bw, rows)
        for j in range(rows):
            self.text(f, x0, y0 + j, " " * bw, TEXT, PANEL_BG)
        self.text(f, x0 + 2, y0, f"{self.shop_name.capitalize()}: 1-0 buy, Tab to sell, Esc closes", HEADING,
                  width=bw - 4)
        if not self.shop:
            self.text(f, x0 + 2, y0 + 2, "Sold out.", DIM)
        for i, item in enumerate(self.shop[:10]):
            y = y0 + 1 + i
            affordable = self.gold >= item["price"]
            self.text(f, x0 + 2, y, str((i + 1) % 10), DIM)
            self.text(f, x0 + 4, y, item["g"], tuple(item["c"]))
            self.text(f, x0 + 6, y, self.fit(item["name"], 25), TEXT if affordable else DIM)
            self.text(f, x0 + 32, y, item["info"], DIM)
            price = str(item["price"])
            self.text(f, x0 + bw - 2 - len(price), y, price, (255, 215, 90) if affordable else (200, 80, 80))
        self.text(f, x0 + 2, y0 + rows - 1, f"{self.gold} {seasons.gold_name(self.season)}", (255, 215, 90))
        note = "Spending lowers your score"
        self.text(f, x0 + bw - 2 - len(note), y0 + rows - 1, note, DIM)

    def _draw_selling(self, f) -> None:
        """Your pack, with what the merchant would pay for each thing in it."""
        bw, rows = SHOP_WIDTH, max(len(self.pack), 1) + 4
        x0, y0 = self._panel_pos(bw, rows)
        for j in range(rows):
            self.text(f, x0, y0 + j, " " * bw, TEXT, PANEL_BG)
        self.text(f, x0 + 2, y0, f"{self.shop_name.capitalize()}: 1-0 sell for half, Tab to buy, Esc closes",
                  HEADING, width=bw - 4)
        if not self.pack:
            self.text(f, x0 + 2, y0 + 2, "Your pack is empty.", DIM)
        for i, item in enumerate(self.pack[:PACK_SIZE]):
            y = y0 + 1 + i
            price = item.get("sell", 0)
            self.text(f, x0 + 2, y, str((i + 1) % 10), DIM)
            self.text(f, x0 + 4, y, item["g"], tuple(item["c"]))
            name = item["name"] + (" (on)" if item["eq"] else "")
            self.text(f, x0 + 6, y, self.fit(name, 40), TEXT if price else DIM)
            offer = str(price) if price else "won't buy"
            self.text(f, x0 + bw - 2 - len(offer), y, offer, (255, 215, 90) if price else DIM)
        self.text(f, x0 + 2, y0 + rows - 1, f"{self.gold} {seasons.gold_name(self.season)}", (255, 215, 90))
        note = "What you sell is gone for good"
        self.text(f, x0 + bw - 2 - len(note), y0 + rows - 1, note, DIM)

    def _draw_help(self, f) -> None:
        bw, key_w = 68, 26
        rows = len(HELP_LINES) + 2
        x0, y0 = self._panel_pos(bw, rows)
        for j in range(rows):
            self.text(f, x0, y0 + j, " " * bw, TEXT, PANEL_BG)
        self.text(f, x0 + 2, y0, self._key_text("Controls (the game keeps running). {help} or Esc closes"), HEADING)
        for j, (keys, what) in enumerate(HELP_LINES):
            self.text(f, x0 + 2, y0 + 1 + j, self._key_text(keys), (255, 215, 90), width=key_w - 1)
            self.text(f, x0 + 2 + key_w, y0 + 1 + j, what, TEXT)
        self.text(f, x0 + 2, y0 + rows - 1, self._key_text(self.tip), DIM)

    def _draw_prompt(self, f) -> None:
        text, keys = self.prompt["text"], "y yes    n no"
        bw, rows = len(text) + 4, 4
        x0, y0 = self._panel_pos(bw, rows)
        for j in range(rows):
            self.text(f, x0, y0 + j, " " * bw, TEXT, PANEL_BG)
        self.text(f, x0 + 2, y0 + 1, text, (225, 140, 255))
        self.text(f, x0 + 2, y0 + 2, keys, DIM)

    def _draw_victory(self, f) -> None:
        lines = [f"{self.victory} escaped with the Amulet!", "The party wins.", "", *self.tally_lines(), "",
                 f"A new dungeon begins in about {VICTORY_SECONDS:.0f} seconds."]
        bw = max(len(s) for s in lines) + 4
        x0, y0 = MAP_X + (MAP_W - bw) // 2, MAP_Y + (MAP_H - len(lines) - 2) // 2
        for j in range(len(lines) + 2):
            self.text(f, x0, y0 + j, " " * bw, TEXT, WIN_BG)
        for j, s in enumerate(lines):
            self.text(f, x0 + 2, y0 + 1 + j, s, (255, 215, 90) if j == 0 else TEXT, WIN_BG)

    def _draw_console(self, f) -> None:
        bw, rows = CONSOLE_WIDTH, CONSOLE_ROWS
        x0, y0 = self._panel_pos(bw, rows)
        for j in range(rows):
            self.text(f, x0, y0 + j, " " * bw, TEXT, PANEL_BG)
        self.text(f, x0 + 2, y0, CONSOLE_TITLE, HEADING)
        self.text(f, x0 + bw - 1 - len(CONSOLE_CLOSE), y0, CONSOLE_CLOSE, HEADING)
        for j, (line, color) in enumerate(self._console_lines()):
            self.text(f, x0 + 2, y0 + 1 + j, line, color, width=bw - 4)
        _, _, found, at = self.console_suggestions()
        for x, y, width, i, name in self._suggestion_cells():
            picked = i == at
            self.text(f, x, y, f" {name}".ljust(width), (255, 255, 255) if picked else TEXT,
                      LINK_BG if picked else SUGGEST_BG)
        count = f"Tab {at + 1}/{len(found)}" if len(found) > 1 else "Tab" if found else ""
        self.text(f, x0 + 2, y0 + rows - 1, "> " + self.console_buf[-(bw - 9 - len(count)):] + "_", (255, 255, 255))
        if count:
            self.text(f, x0 + bw - 2 - len(count), y0 + rows - 1, count, DIM)
        link = self.console_link(self.mouse)
        if link:  # light up what a click would do
            _, _, x, y, width = link
            for i in range(width):
                f["bg"][x + i, y] = LINK_BG

    def _draw_death(self, f) -> None:
        if self.downed:
            lines = ["You are down!", self.death, "",
                     "A teammate can revive you by standing next to your",
                     f"bones ({BONES_GLYPH}) for {self.revive_seconds:.0f} seconds. You come back at half health",
                     "with all your gear.", "",
                     "If everyone goes down, the run restarts.", "", *self.tally_lines(), "",
                     self._key_text("Press {log} to see what happened.")]
        else:
            lines = ["You have died.", self.death, "", *self.tally_lines(), "", self._key_text("Press {log} to see what happened."),
                     "Waiting for the party.", "A new run starts when everyone has fallen."]

        bw = max(len(s) for s in lines) + 4
        x0 = MAP_X + (MAP_W - bw) // 2
        y0 = MAP_Y + (MAP_H - len(lines) - 2) // 2

        if self.downed:  # keep your bones in view while waiting to be revived
            me = self.me()
            y0 = MAP_Y if me is None or me["y"] >= MAP_H // 2 else MAP_Y + MAP_H - len(lines) - 2

        for j in range(len(lines) + 2):
            self.text(f, x0, y0 + j, " " * bw, TEXT, DEATH_BG)

        for j, s in enumerate(lines):
            self.text(f, x0 + 2, y0 + 1 + j, s, (255, 120, 120) if j == 0 else TEXT, DEATH_BG)
