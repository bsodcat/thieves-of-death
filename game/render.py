"""Client-side view: what this player knows, drawn into a frame buffer.

Nothing here imports tcod. The frame uses the same layout as a tcod
console's `rgb` array (ch / fg / bg, indexed [x, y]), so client.py just
copies it onto a tcod Console. That also lets the tests render screenshots
without a window.
"""
from __future__ import annotations

import textwrap
import time
from collections import deque

import numpy as np

from . import protocol, seasons
from .constants import (BONES_GLYPH, LOOK_Y, MAP_H, MAP_W, MAP_X, MAP_Y, MSG_LINES, PACK_SIZE, REVIVE_SECONDS,
                        SCREEN_H, SCREEN_W, SCORE_PER_GOLD, SIDEBAR_W, STEALTH_MAX, TICKS_PER_TURN)
from .entities import MONSTERS
from .tiles import BG, DESCRIPTIONS, FG, GLYPH, NAMES

FRAME_DTYPE = np.dtype([("ch", np.int32), ("fg", "3u1"), ("bg", "3u1")])

TEXT = (220, 220, 220)
PANEL_BG = (20, 20, 34)
DIM = (130, 130, 140)
HEADING = (180, 170, 140)
HELP_LINES = (
    ("Arrows, numpad, hjklyubn", "Move or attack; hold to keep going"),
    ("Two arrows together", "Move diagonally"),
    ("> or <", "Take the stairs, or walk into them"),
    ("1-9, 0", "Use the item in that pack slot"),
    ("i or t", "Show or hide your pack, or your tally"),
    ("d, then 1-0 or $", "Drop an item, or 25 gold"),
    ("Mouse", "Point at the map to identify it"),
    ("g", "Pick up what you're standing on"),
    ("Enter", "Chat"),
    ("? or F1", "Show or hide this help"),
    ("Esc", "Close a panel or cancel"),
    ("Q twice", "Leave the game"),
)
HELP_TIP = "Stand still to build stealth. Attacks empty it; gear limits it."

LOOK_HINT = "Point the mouse at the map to identify what's there."
HOVER_BG = (70, 70, 100)
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
        self.show_help = False
        self.show_tally = False
        self.season = None
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
            shape = (msg["w"], msg["h"])
            self.levels[msg["depth"]] = protocol.unpack_u8(msg["tiles"], shape)
            self.seen.setdefault(msg["depth"], np.zeros(shape, dtype=bool))
        elif t == "state":
            self.depth = msg["depth"]
            self.visible = protocol.unpack_bool(msg["visible"], (MAP_W, MAP_H))
            if self.depth in self.seen:
                self.seen[self.depth] |= self.visible
            memory = self.item_memory.setdefault(self.depth, {})
            for pos in [pos for pos in memory if self.visible[pos]]:
                del memory[pos]  # visible tiles are about to be reported afresh
            for item in msg.get("items", ()):
                memory[(item["x"], item["y"])] = item
            self.ents, self.party, self.status = msg["ents"], msg["party"], msg["status"]
            self.alive, self.death = msg["alive"], msg.get("death", "")
            self.downed = msg.get("downed", False)
            self.turns, self.kills = msg.get("turns", 0), msg.get("kills", 0)
            self.haste, self.stealth = msg.get("haste", False), msg.get("stealth", 0)
            self.score, self.score_gold = msg.get("score", 0), msg.get("score_gold", 0)
            self.tally, self.hardest = msg.get("tally", {}), msg.get("hardest", "")
            self.season = msg.get("season")
            self.detect = msg.get("detect", 0)
            self.clock_base, self.clock_at = msg.get("time", 0.0), time.monotonic()
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

    def me(self) -> dict | None:
        return next((e for e in self.ents if e["id"] == self.my_id), None)

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
        if not self.alive:
            self._draw_death(f)
        if self.show_tally:
            self._draw_tally(f)
        if self.show_help:
            self._draw_help(f)
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
        me = self.me()
        if me is not None:  # gentle light falloff around you
            xs, ys = np.indices((MAP_W, MAP_H))
            light = np.clip(1.15 - np.hypot(xs - me["x"], ys - me["y"]) / 28.0, 0.55, 1.0)[..., None]
        else:
            light = 1.0
        # Remembered tiles: dark and bluish, like Brogue's magic-mapped memory.
        mem_fg = fg.mean(axis=-1, keepdims=True) * 0.32 + np.array([12, 14, 34], np.float32)
        mem_bg = bg * 0.22 + np.array([0, 0, 10], np.float32)
        v, s = vis[..., None], seen[..., None]
        out_fg = np.where(v, fg * light, np.where(s, mem_fg, 0))
        out_bg = np.where(v, bg * light, np.where(s, mem_bg, 0))
        area = (slice(MAP_X, MAP_X + MAP_W), slice(MAP_Y, MAP_Y + MAP_H))
        f["ch"][area] = np.where(vis | seen, ch, ord(" "))
        f["fg"][area] = np.clip(out_fg, 0, 255).astype(np.uint8)
        f["bg"][area] = np.clip(out_bg, 0, 255).astype(np.uint8)

        for (x, y), item in self.item_memory.get(self.depth, {}).items():
            f["ch"][MAP_X + x, MAP_Y + y] = ord(item["g"])
            f["fg"][MAP_X + x, MAP_Y + y] = item["c"] if vis[x, y] else scale(item["c"], 0.45)

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

        hover = self.hovered()
        if hover is not None:
            f["bg"][MAP_X + hover[0], MAP_Y + hover[1]] = HOVER_BG

    # --------------------------------------------------------------- look

    def hovered(self) -> tuple[int, int] | None:
        """The map tile under the pointer, if it's over the map."""
        if self.mouse is None:
            return None
        x, y = self.mouse[0] - MAP_X, self.mouse[1] - MAP_Y
        return (x, y) if 0 <= x < MAP_W and 0 <= y < MAP_H else None

    def _describe_actor(self, e: dict) -> list:
        color = tuple(e["c"])
        if e["st"] == "down":
            if e["id"] == self.my_id:
                return [(f"{e['g']} Your bones", color), ("A teammate can stand here to revive you.", TEXT)]
            return [(f"{e['g']} {e['name']}'s bones", color),
                    (f"Stand next to them for {REVIVE_SECONDS:.0f} seconds to revive them.", TEXT)]
        if e["p"]:
            name = "You" if e["id"] == self.my_id else e["name"]
            return [(f"{e['g']} {name}", color), (f"Health {e['hp']}/{e['mhp']}", TEXT)]
        lines = [(f"{e['g']} {e['name'].capitalize()}", color),
                 (f"Health {e['hp']}/{e['mhp']}", TEXT),
                 (STATE_NAMES.get(e["st"], ""), (255, 170, 80) if e["st"] == "hunting" else DIM)]
        kind = e.get("kind") or e["name"]
        t = MONSTERS.get(kind)
        if t:
            speed = " Fast." if t["move"] < TICKS_PER_TURN else ""
            speed += " Slow hits." if t["attack"] > TICKS_PER_TURN else ""
            desc = seasons.monster_description(kind, self.season, t["desc"])
            lines.append((f"{desc} Hits for {t['damage'][0]}-{t['damage'][1]}.{speed}", TEXT))
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
        if tiles is None or seen is None or not seen[x, y]:
            actor = next((e for e in self.ents if (e["x"], e["y"]) == (x, y)), None)
            if actor is None:
                return [("Unexplored", DIM), ("You haven't seen this yet.", DIM)]
            return self._describe_actor(actor)  # an ally you can sense through walls
        lines = []
        for e in self.ents:
            if (e["x"], e["y"]) == (x, y) and (e["seen"] or e["p"]):
                lines += self._describe_actor(e)
        in_sight = bool(self.visible[x, y])
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
            clock = f"Time {format_clock(self.clock())}"
            self.text(f, 1, y, clock, (255, 255, 255))
            if self.haste:
                self.text(f, len(clock) + 2, y, "Haste", (120, 220, 255))
            y += 1
            self.text(f, 1, y, f"Depth {self.depth}  Gold {self.gold}", TEXT, width=w - 1)
            y += 1
            self.text(f, 1, y, f"Dmg {self.dmg}  Armor {self.defense}", TEXT, width=w - 1)
            y += 1
            self.text(f, 1, y, f"Detection {self.detect} tiles", TEXT, width=w - 1)
            y += 1
            self.text(f, 1, y, f"Moves {self.turns}  Kills {self.kills}", DIM, width=w - 1)
            y += 1
            self.text(f, 1, y, f"Score {self.score}", (255, 215, 90), width=w - 1)
            y += 2

        if self.party:
            self.text(f, 1, y, "Players", HEADING)
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
        mons = [e for e in self.ents if not e["p"] and e["seen"]]
        if me_e:
            mons.sort(key=lambda e: max(abs(e["x"] - me_e["x"]), abs(e["y"] - me_e["y"])))
        for e in mons:
            if y >= LOOK_Y - 2:
                break
            self.text(f, 1, y, e["g"], tuple(e["c"]))
            self.text(f, 3, y, e["name"], TEXT, width=w - 3)
            y += 1
            self.bar(f, 0, y, w, e["hp"] / e["mhp"], "asleep" if e["st"] == "sleeping" else "", (130, 40, 40))
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
        return f"Score {self.score}  ({self.turns} moves + {self.score_gold} gold x {SCORE_PER_GOLD})"

    def tally_lines(self) -> list[str]:
        hardest = self.hardest or "none yet"
        return [self.score_line(), f"Kills {self.kills}   Hardest enemy fought: {hardest}"]

    def _draw_tally(self, f) -> None:
        kills = sorted(self.tally.items(), key=lambda kv: (-kv[1], kv[0]))
        bw, rows = 50, min(14, 6 + len(kills))
        x0, y0 = self._panel_pos(bw, rows)
        for j in range(rows):
            self.text(f, x0, y0 + j, " " * bw, TEXT, PANEL_BG)
        self.text(f, x0 + 2, y0, "Tally: t closes", HEADING)
        self.text(f, x0 + 2, y0 + 1, self.score_line(), (255, 215, 90), width=bw - 4)
        self.text(f, x0 + 2, y0 + 2, f"Hardest enemy fought: {self.hardest or 'none yet'}", TEXT, width=bw - 4)
        self.text(f, x0 + 2, y0 + 3, f"Kills: {self.kills}", TEXT)
        for j, (name, count) in enumerate(kills[:rows - 5]):
            self.text(f, x0 + 4, y0 + 4 + j, f"{name}", TEXT)
            self.text(f, x0 + 24, y0 + 4 + j, f"{count}", (255, 255, 255))

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
        self.text(f, x0 + 2, y0 + rows - 1, HELP_TIP, DIM)

    def _draw_death(self, f) -> None:
        if self.downed:
            lines = ["You are down!", self.death, "",
                     f"A teammate can revive you by standing next to your",
                     f"bones ({BONES_GLYPH}) for {REVIVE_SECONDS:.0f} seconds. You come back at half health",
                     "with all your gear.", "",
                     "If everyone goes down, the run restarts.", "", *self.tally_lines()]
        else:
            lines = ["You have died.", self.death, "", *self.tally_lines(), "", "Waiting for the party.",
                     "A new run starts when everyone has fallen."]
                     
        bw = max(len(s) for s in lines) + 4
        x0 = MAP_X + (MAP_W - bw) // 2
        y0 = MAP_Y + (MAP_H - len(lines) - 2) // 2
        
        if self.downed:  # keep MY BONED in view for revival
            me = self.me()
            y0 = MAP_Y if me is None or me["y"] >= MAP_H // 2 else MAP_Y + MAP_H - len(lines) - 2
            
        for j in range(len(lines) + 2):
            self.text(f, x0, y0 + j, " " * bw, TEXT, (40,10, 10))
            
        for j, s in enumerate(lines):
            self.text(f, x0 + 2, y0 + 1 + j, s, (255, 120, 120) if j == 0 else TEXT, (40, 10, 10))
