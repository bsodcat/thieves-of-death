"""Client-side view: what this player knows, drawn into a frame buffer.

Nothing here imports tcod. The frame uses the same layout as a tcod
console's `rgb` array (ch / fg / bg, indexed [x, y]), so client.py just
copies it onto a tcod Console. That also lets the tests render screenshots
without a window.
"""
from __future__ import annotations

import math
import random
import textwrap
import time
from collections import deque

import numpy as np

from . import pathing, protocol, seasons
from .constants import (ATTACK_STAMINA, BONES_GLYPH, LOOK_Y, MAP_H, MAP_W, MAP_X, MAP_Y, MSG_LINES, PACK_SIZE,
                        REVIVE_SECONDS, SCREEN_H, SCREEN_W, SCORE_PER_GOLD, SIDEBAR_W, STAMINA_MAX, STEALTH_MAX,
                        TICKS_PER_TURN, VICTORY_SECONDS)
from .entities import MONSTERS
from .tiles import (ALTAR, BG, DEEP, DESCRIPTIONS, FG, GLYPH, LAVA, NAMES, POND, SHALLOW, STAIRS_DOWN, STAIRS_UP,
                    TOWER_WALL, WALKABLE)

FRAME_DTYPE = np.dtype([("ch", np.int32), ("fg", "3u1"), ("bg", "3u1")])

TEXT = (220, 220, 220)
PANEL_BG = (20, 20, 34)
DIM = (130, 130, 140)
HEADING = (180, 170, 140)
HELP_LINES = (
    ("Arrows, numpad, hjklyubn", "Move or attack; hold to keep going"),
    ("Two arrows together", "Move diagonally"),
    ("Hold Shift", "Sprint, while you have the stamina"),
    ("> or <", "Take the stairs, or walk into them"),
    ("1-9, 0", "Use the item in that pack slot"),
    ("i or t", "Show or hide your pack, or your tally"),
    ("d, then 1-0 or $", "Drop an item, or 25 gold"),
    ("Mouse", "Point to identify, hold right to walk"),
    ("g", "Pick up what you're standing on"),
    ("Enter, or ` or F2", "Chat, or the test console (host only)"),
    ("? or F1, Esc", "Show or hide this help, or close a panel"),
    ("Q twice", "Leave the game"),
)
HELP_TIPS = (
    "Stand still to build stealth. Attacks empty it; gear limits it.",
    "Monsters notice you from further away in torchlight.",
    "Hold Shift to sprint. It burns stamina and drains stealth fast.",
    "With too little stamina, your attacks take twice as long.",
    "Stamina only refills once you stop spending it.",
    "A sneak attack on an unaware monster does triple damage.",
    "Walking over potions and gold collects them. Gear needs g.",
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
    "A wand aims itself at the nearest enemy you can see.",
    "Past floor 50, a pit might drop you straight into lava.",
    "Every move lowers your score. Gold raises it.",
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
    "Water and lava walking potions turn up around floors 20 to 40.",
)

LOOK_HINT = "Point the mouse at the map to identify what's there."
HOVER_BG = (70, 70, 100)
TORCH_GLOW = np.array((70, 38, 8), np.float32)    # added to the background at full brightness
TORCH_TEXT = (255, 180, 70)
DEATH_BG = (40, 10, 10)
BOLT_SECONDS = 0.35
FLAME = (255, 120, 20)
BOLT_COLORS = {"fire": FLAME, "blink": (230, 120, 255), "frost": (150, 215, 255), "sparkle": (150, 255, 240)}
SPARKLE = (90, 240, 220)
# Each animated tile cycles through glyphs that look alike: (tile, glyphs, steps a second).
RIPPLES = ((DEEP, (0x2248, ord("~"), 0x2248, 0x2248), 3), (SHALLOW, (ord("~"), 0x2248, ord("~"), ord("-")), 2),
           (LAVA, (0x2248, ord("~"), 0x2591, 0x2248), 4), (POND, (0x2248, ord("*"), ord("~"), 0xB7), 6))
ICE = (70, 130, 190)
AURA = np.array((165, 60, 250), np.float32)      # added to the background right beside an altar
AURA_RADIUS = 5.0
ULTRABRIGHT = 1.5
WARNING_RED = (255, 50, 40)
WARNING_RISE = 3          # the warning builds as (share of the swing gone) ** this
WARNING_BLINKS = 4.5      # how fast the blinking speeds up: more is more frantic
MARK_MONSTER, MARK_ITEM = (150, 30, 45), (125, 105, 15)   # behind whatever reveal is showing you
GAS = np.array((50, 120, 30), np.float32)
WIN_BG = (30, 26, 6)
CONSOLE_WIDTH, CONSOLE_ROWS = 72, 14
WALK_ON_WATER, WALK_ON_LAVA = (120, 190, 255), (255, 130, 40)
XS, YS = np.indices((MAP_W, MAP_H))
FLOAT_DIM, FLOAT_BRIGHT, FLOAT_SHADOW = (30, 50, 110), (90, 150, 240), (6, 6, 14)
FLOAT_TEXT = (190, 170, 255)
STATE_NAMES = {"sleeping": "Asleep", "wandering": "Wandering", "hunting": "Hunting you"}

STATUS_COLORS = {"go": (140, 230, 140), "revive": (255, 215, 90), "dead": (255, 100, 100)}


def scale(color, k: float) -> tuple:
    return tuple(int(max(0, min(255, c * k))) for c in color)


def format_clock(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02}:{secs:02}" if hours else f"{minutes:02}:{secs:02}"


class ClientView:
    def __init__(self) -> None:
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
        self.season = None
        self.shop: list | None = None             # the merchant's stock while you're at the shop
        self.shop_name = ""
        self.shop_pos = (0, 0)
        self.levitate = False
        self.waterwalk = self.lavawalk = False
        self.bolts: list[tuple] = []              # (tiles, when, color) of magic still on screen
        self.gas: list = []                       # tiles of toxic gas in sight
        self.prompt: dict | None = None           # a yes or no question waiting for an answer
        self.bright = False                       # console: draw the whole floor fully lit
        self.victory = ""                         # who won the run
        self.console_open = False
        self.console_buf = ""
        self.console_log: deque = deque(maxlen=200)
        self.console_history: list[str] = []
        self.console_back = 0                     # how far back up the history you've gone
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
        elif t == "level":
            if msg.get("run") != self.run:  # new dungeon: forget the old map
                self.run = msg.get("run")
                self.levels.clear()
                self.seen.clear()
                self.item_memory.clear()
                self.lights.clear()
            shape = (msg["w"], msg["h"])
            self.levels[msg["depth"]] = protocol.unpack_u8(msg["tiles"], shape)
            self.lights[msg["depth"]] = [protocol.unpack_u8(m, shape) / 255 for m in msg.get("lights", ())]
            self.seen.setdefault(msg["depth"], np.zeros(shape, dtype=bool))
        elif t == "tiles":
            tiles = self.levels.get(msg["depth"])
            if tiles is not None:
                for x, y, tile in msg["cells"]:
                    tiles[x, y] = tile
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
            self.waterwalk, self.lavawalk = msg.get("waterwalk", False), msg.get("lavawalk", False)
            self.stamina, self.lit = msg.get("stamina", STAMINA_MAX), msg.get("lit", False)
            self.detect = msg.get("detect", 0)
            self.clock_base, self.clock_at = msg.get("time", 0.0), time.monotonic()
        elif t == "shop":
            self.shop, self.shop_name, self.shop_pos = msg["stock"], msg["name"], (msg["x"], msg["y"])
            self.show_pack = self.drop_mode = self.show_help = self.show_tally = False
        elif t == "fx":
            self.bolts.append((msg["cells"], time.monotonic(), BOLT_COLORS.get(msg.get("kind"), FLAME)))
        elif t == "console":
            for line in textwrap.wrap(msg["text"], CONSOLE_WIDTH - 4, replace_whitespace=False, drop_whitespace=False):
                self.console_log.append((line, tuple(msg.get("c", TEXT))))
        elif t == "prompt":
            self.prompt = msg
        elif t == "reject":
            self.messages.append((msg["text"], (255, 90, 90)))
        elif t == "pack":
            self.pack, self.gold, self.defense = msg["pack"], msg["gold"], msg["defense"]
            self.dmg, self.stealth_cap = msg["dmg"], msg.get("stealth_cap", STEALTH_MAX)
        elif t == "msg":
            self.messages.append((msg["text"], tuple(msg.get("c", TEXT))))
        elif t == "_disconnected":
            self.connected = False
            self.messages.append(("Disconnected from the server.", (255, 90, 90)))

    def console_submit(self) -> str:
        """Takes the typed line. Returns what to send the server, if anything."""
        text, self.console_buf, self.console_back = self.console_buf.strip(), "", 0
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

    def toggle_help(self) -> None:
        """Each time the help opens it shows the next tip, in a shuffled order."""
        self.show_help = not self.show_help
        self.show_pack = self.drop_mode = self.show_tally = False
        if self.show_help:
            if not self.tips:
                self.tips = random.sample([t for t in HELP_TIPS if t != self.tip], len(HELP_TIPS) - 1)
            self.tip = self.tips.pop()

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
        others = {(e["x"], e["y"]) for e in self.ents
                  if e["id"] != self.my_id and e["st"] != "down" and (e["seen"] or e["p"])}
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
        v, s = vis[..., None], seen[..., None]
        lit_fg, lit_bg = fg * light, bg * light
        glow = self._torchlight()
        if glow is not None:
            lit_fg = lit_fg * (1 + 0.6 * glow)
            lit_bg = lit_bg * (1 + 0.8 * glow) + glow * TORCH_GLOW
        for x, y in np.argwhere(tiles == ALTAR):
            pulse = 0.75 + 0.25 * math.sin(time.monotonic() * 3 + x)
            lit_bg = lit_bg + (np.clip(1 - np.hypot(XS - x, YS - y) / AURA_RADIUS, 0, 1) * pulse)[..., None] * AURA
        out_fg = np.where(v, lit_fg, np.where(s, mem_fg, 0))
        out_bg = np.where(v, lit_bg, np.where(s, mem_bg, 0))
        area = (slice(MAP_X, MAP_X + MAP_W), slice(MAP_Y, MAP_Y + MAP_H))
        f["ch"][area] = np.where(vis | seen, ch, ord(" "))
        f["fg"][area] = np.clip(out_fg, 0, 255).astype(np.uint8)
        f["bg"][area] = np.clip(out_bg, 0, 255).astype(np.uint8)

        for x, y, thickness in self.gas:  # fades to nothing, and thins to specks on the way
            share = thickness / 9
            at = (MAP_X + x, MAP_Y + y)
            f["bg"][at] = np.clip(f["bg"][at] * (1 - 0.5 * share) + GAS * share, 0, 255).astype(np.uint8)
            if thickness > 1:
                f["ch"][at] = 0x2592 if thickness > 5 else 0x2591
                f["fg"][at] = np.clip(GAS * (0.6 + share), 0, 255).astype(np.uint8)

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
            heat = self.warning(e)
            if heat:
                at = (MAP_X + e["x"], MAP_Y + e["y"])
                f["fg"][at] = [int(c + (r - c) * min(1.0, heat * 2)) for c, r in zip(color, WARNING_RED)]
                f["bg"][at] = scale(WARNING_RED, heat)
            if e.get("lev"):
                self._draw_float(f, e)
            if e.get("burn"):
                f["bg"][MAP_X + e["x"], MAP_Y + e["y"]] = scale(FLAME, 0.7 + 0.3 * math.sin(time.monotonic() * 11))
            if e.get("frozen"):
                f["bg"][MAP_X + e["x"], MAP_Y + e["y"]] = ICE
            if e.get("ward"):
                self._draw_sparkle(f, e)
        self._draw_bolts(f)

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

    @staticmethod
    def _draw_sparkle(f, e: dict) -> None:
        """Motes of teal light come and go around someone warded."""
        tick = int(time.monotonic() * 7)
        for i, (dx, dy) in enumerate(((-1, -1), (1, -1), (-1, 1), (1, 1), (0, -1), (0, 1), (-1, 0), (1, 0))):
            x, y = e["x"] + dx, e["y"] + dy
            if (tick * 5 + i * 3) % 4 == 0 and 0 <= x < MAP_W and 0 <= y < MAP_H:
                f["ch"][MAP_X + x, MAP_Y + y] = ord("*")
                f["fg"][MAP_X + x, MAP_Y + y] = SPARKLE

    def _draw_bolts(self, f) -> None:
        now = time.monotonic()
        self.bolts = [b for b in self.bolts if now - b[1] < BOLT_SECONDS]
        for cells, fired, color in self.bolts:
            heat = 1 - (now - fired) / BOLT_SECONDS
            for x, y in cells:
                f["bg"][MAP_X + x, MAP_Y + y] = scale(color, heat)

    def warning(self, e: dict) -> float:
        """How strongly a monster should show it's about to hit you, from 0 to 1. Both the red
        and the speed of the blinking climb exponentially as the moment gets close."""
        if "strike" not in e:
            return 0.0
        left = e["strike"] - (time.monotonic() - self.clock_at)
        share = max(0.0, min(1.0, 1 - left / e["swing"]))
        blink = 0.65 + 0.35 * math.cos(math.exp(share * WARNING_BLINKS))
        return share ** WARNING_RISE * blink

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
            return [(f"{e['g']} {e['name'].capitalize()}", color), ("Walk into them to see what's for sale.", TEXT)]
        if e["st"] == "down":
            if e["id"] == self.my_id:
                return [(f"{e['g']} Your bones", color), ("A teammate can stand here to revive you.", TEXT)]
            return [(f"{e['g']} {e['name']}'s bones", color),
                    (f"Stand next to them for {REVIVE_SECONDS:.0f} seconds to revive them.", TEXT)]
        if e["p"]:
            name = "You" if e["id"] == self.my_id else e["name"]
            lines = [(f"{e['g']} {name}", color), (f"Health {e['hp']}/{e['mhp']}", TEXT)]
            if e.get("lev"):
                lines.append(("Levitating", FLOAT_TEXT))
            if e.get("ward"):
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
        if e.get("burn"):
            lines.append(("On fire", FLAME))
        if e.get("frozen"):
            lines.append(("Frozen solid", ICE))
        return lines

    @staticmethod
    def _describe_item(item: dict, in_sight: bool) -> list:
        how = "Walk over it to collect." if item.get("auto") else "Stand on it and press g."
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
            self.text(f, 1, y, me["name"], tuple(me["c"]), width=w - 1)
            y += 1
            self.bar(f, 0, y, w, me["hp"] / me["mhp"], f"Health {me['hp']}/{me['mhp']}", (160, 30, 30))
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
                self.text(f, 3, y, q["name"], TEXT, width=w - 4)
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
            self.text(f, 3, y, e["name"], TEXT, width=w - 3)
            y += 1
            label = {"sleeping": "asleep", "merchant": "shop"}.get(e["st"], "")
            self.bar(f, 0, y, w, e["hp"] / e["mhp"], label, (130, 100, 30) if e["st"] == "merchant" else (130, 40, 40))
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
                      "arrows/numpad/hjklyubn  1-0 use  i pack  t tally  d drop  g get  ? help  Q quit",
                      DIM, width=MAP_W)

    def _draw_pack(self, f) -> None:
        """The game keeps running behind this, so it stays clear of you; see _panel_pos."""
        bw, panel_bg = 62, PANEL_BG
        rows = PACK_SIZE + 4
        x0, y0 = self._panel_pos(bw, rows)
        title = "Drop what? 1-0, $ for gold, Esc cancels" if self.drop_mode else "Pack: 1-0 use or equip, i closes"
        for j in range(rows):
            self.text(f, x0, y0 + j, " " * bw, TEXT, panel_bg)
        self.text(f, x0 + 2, y0 + 1, title, HEADING, width=bw - 4)
        for i in range(PACK_SIZE):
            y = y0 + 2 + i
            self.text(f, x0 + 2, y, str((i + 1) % 10), DIM)
            if i >= len(self.pack):
                continue
            item = self.pack[i]
            self.text(f, x0 + 4, y, item["g"], tuple(item["c"]))
            self.text(f, x0 + 6, y, item["name"], (255, 255, 255) if item["eq"] else TEXT, width=26)
            note = item["info"] + (" (on)" if item["eq"] else "")
            self.text(f, x0 + bw - 2 - len(note), y, note, DIM)
        self.text(f, x0 + 2, y0 + rows - 1, f"{self.gold} {seasons.gold_name(self.season)}", (255, 215, 90))
        note = f"Equipped gear limits stealth to {self.stealth_cap}%"
        self.text(f, x0 + bw - 2 - len(note), y0 + rows - 1, note, DIM)

    def _panel_pos(self, width: int, height: int) -> tuple[int, int]:
        """Where a panel goes to leave your character in view.
        Panels are under half the map's height, so taking the
        half your character is not in always clears away from you."""
        me = self.me()
        x = MAP_X if me is not None and me["x"] >= MAP_W // 2 else MAP_X + MAP_W - width
        y = MAP_Y + MAP_H - height if me is not None and me["y"] < MAP_H // 2 else MAP_Y
        return x, y

    def score_line(self) -> str:
        return f"Score {self.score}  ({self.score_gold} gold x {SCORE_PER_GOLD}, cut by {self.turns} moves)"

    def tally_lines(self) -> list[str]:
        hardest = self.hardest or "none yet"
        return [self.score_line(), f"Kills {self.kills}   Hardest enemy fought: {hardest}"]

    def _draw_tally(self, f) -> None:
        kills = sorted(self.tally.items(), key=lambda kv: (-kv[1], kv[0]))
        bw, rows = 50, min(14, 6 + (len(kills) + 1) // 2)
        x0, y0 = self._panel_pos(bw, rows)
        for j in range(rows):
            self.text(f, x0, y0 + j, " " * bw, TEXT, PANEL_BG)
        self.text(f, x0 + 2, y0, "Tally: t closes", HEADING)
        self.text(f, x0 + 2, y0 + 1, self.score_line(), (255, 215, 90), width=bw - 4)
        self.text(f, x0 + 2, y0 + 2, f"Hardest enemy fought: {self.hardest or 'none yet'}", TEXT, width=bw - 4)
        self.text(f, x0 + 2, y0 + 3, f"Kills: {self.kills}", TEXT)
        per_column = rows - 5
        for j, (name, count) in enumerate(kills[:per_column * 2]):
            x, y = x0 + 2 + 23 * (j // per_column), y0 + 4 + j % per_column
            self.text(f, x, y, name, TEXT, width=16)
            self.text(f, x + 17, y, f"{count}", (255, 255, 255))

    def _draw_shop(self, f) -> None:
        bw, rows = 62, len(self.shop) + 4 if self.shop else 5
        x0, y0 = self._panel_pos(bw, rows)
        for j in range(rows):
            self.text(f, x0, y0 + j, " " * bw, TEXT, PANEL_BG)
        self.text(f, x0 + 2, y0, f"{self.shop_name.capitalize()}: 1-0 buy, Esc closes", HEADING, width=bw - 4)
        if not self.shop:
            self.text(f, x0 + 2, y0 + 2, "Sold out.", DIM)
        for i, item in enumerate(self.shop[:10]):
            y = y0 + 1 + i
            affordable = self.gold >= item["price"]
            self.text(f, x0 + 2, y, str((i + 1) % 10), DIM)
            self.text(f, x0 + 4, y, item["g"], tuple(item["c"]))
            self.text(f, x0 + 6, y, item["name"], TEXT if affordable else DIM, width=21)
            self.text(f, x0 + 28, y, item["info"], DIM)
            price = str(item["price"])
            self.text(f, x0 + bw - 2 - len(price), y, price, (255, 215, 90) if affordable else (200, 80, 80))
        self.text(f, x0 + 2, y0 + rows - 1, f"{self.gold} {seasons.gold_name(self.season)}", (255, 215, 90))
        note = "Spending lowers your score"
        self.text(f, x0 + bw - 2 - len(note), y0 + rows - 1, note, DIM)

    def _draw_help(self, f) -> None:
        bw, key_w = 68, 26
        rows = len(HELP_LINES) + 2
        x0, y0 = self._panel_pos(bw, rows)
        for j in range(rows):
            self.text(f, x0, y0 + j, " " * bw, TEXT, PANEL_BG)
        self.text(f, x0 + 2, y0, "Controls (the game keeps running). ? or Esc closes", HEADING)
        for j, (keys, what) in enumerate(HELP_LINES):
            self.text(f, x0 + 2, y0 + 1 + j, keys, (255, 215, 90))
            self.text(f, x0 + 2 + key_w, y0 + 1 + j, what, TEXT)
        self.text(f, x0 + 2, y0 + rows - 1, self.tip, DIM)

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
        self.text(f, x0 + 2, y0, "Test console. Type help for commands, Esc closes", HEADING)
        for j, (line, color) in enumerate(list(self.console_log)[-(rows - 2):]):
            self.text(f, x0 + 2, y0 + 1 + j, line, color, width=bw - 4)
        self.text(f, x0 + 2, y0 + rows - 1, "> " + self.console_buf[-(bw - 7):] + "_", (255, 255, 255))

    def _draw_death(self, f) -> None:
        if self.downed:
            lines = ["You are down!", self.death, "",
                     "A teammate can revive you by standing next to your",
                     f"bones ({BONES_GLYPH}) for {REVIVE_SECONDS:.0f} seconds. You come back at half health",
                     "with all your gear.", "",
                     "If everyone goes down, the run restarts.", "", *self.tally_lines()]
        else:
            lines = ["You have died.", self.death, "", *self.tally_lines(), "", "Waiting for the party.",
                     "A new run starts when everyone has fallen."]

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
