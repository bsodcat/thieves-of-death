"""Game client: draws what the server says you can see and sends your input.

    python client.py --name Alice                      # connect to localhost
    python client.py --name Bob --host 192.168.1.20    # connect to a friend
    python client.py --font path/to/font.ttf --tile 12x24
    python client.py --font C:/Windows/Fonts/dosapp.fon --tile 12x16
"""
from __future__ import annotations

import argparse
import os
import queue
import socket
import sys
import threading
import time

import tcod.console
import tcod.context
import tcod.event
import tcod.tileset

from game import fon, protocol
from game.constants import DEFAULT_PORT, PROTOCOL_VERSION, SCREEN_H, SCREEN_W
from game.render import ClientView

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_CANDIDATES = [
    os.path.join(HERE, "fonts", "font.ttf"),
    "C:/Windows/Fonts/8514oem.fon",  # the classic Terminal font, 10x20
    "C:/Windows/Fonts/consola.ttf",
    "C:/Windows/Fonts/lucon.ttf",
    "C:/Windows/Fonts/cour.ttf",
    "/System/Library/Fonts/Monaco.ttf",
    "/System/Library/Fonts/Supplemental/Courier New.ttf",
    "/Library/Fonts/Courier New.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
    "/usr/share/fonts/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
]

# Single-character commands arrive as text, so they work on any keyboard layout.
CHAR_ACTIONS = {">": "descend", "<": "ascend", "g": "pickup", "Q": "quit"}

# Two fingers never leave a diagonal at the same moment. Waiting this long before acting
# on a partial release stops the last key from stepping you along it by accident.
RELEASE_GRACE = 0.05
# The server drops a held direction that hits something. While auto-walking, it's sent again
# after this long with no new position, so a blocked route recovers by itself.
AUTO_RESEND = 0.3


def build_keymap() -> dict:
    """Movement keys. These are tracked as held or released, so holding one keeps moving."""
    keys = tcod.event.KeySym
    table = {
        ("UP", "KP_8", "k"): (0, -1), ("DOWN", "KP_2", "j"): (0, 1),
        ("LEFT", "KP_4", "h"): (-1, 0), ("RIGHT", "KP_6", "l"): (1, 0),
        ("HOME", "KP_7", "y"): (-1, -1), ("PAGEUP", "KP_9", "u"): (1, -1),
        ("END", "KP_1", "b"): (-1, 1), ("PAGEDOWN", "KP_3", "n"): (1, 1),
    }
    out = {}
    for names, action in table.items():
        for name in names:
            sym = getattr(keys, name, None)
            if sym is not None:
                out[sym] = action
    return out


def key_set(*names) -> set:
    return {s for s in (getattr(tcod.event.KeySym, n, None) for n in names) if s is not None}


def build_slot_keys() -> dict:
    """The number row, by key rather than text, so the numpad's arrows never use an item."""
    keys = tcod.event.KeySym
    return {getattr(keys, f"N{d}"): (d - 1) % 10 for d in range(10)}


def held_direction(held: dict) -> tuple[int, int]:
    """Combines held keys, so up + right moves diagonally. Opposite keys: the newest wins."""
    dx = sum(d[0] for d in held.values())
    dy = sum(d[1] for d in held.values())
    if not (dx or dy):
        return next(reversed(held.values()))
    return (dx > 0) - (dx < 0), (dy > 0) - (dy < 0)


class Net:
    """Socket I/O on a background thread; the main thread polls a queue."""

    def __init__(self, host: str, port: int, name: str, timeout: float = 10, look: dict | None = None):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(None)
        self.inbox: queue.Queue = queue.Queue()
        self.send_lock = threading.Lock()
        self.send({"t": "hello", "name": name, "version": PROTOCOL_VERSION, **(look or {})})
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self) -> None:
        try:
            with self.sock.makefile("r", encoding="utf-8", newline="\n") as f:
                for line in f:
                    try:
                        msg = protocol.decode(line)
                    except ValueError:
                        continue
                    if msg.get("t") == "ping":  # answered here, so ping doesn't include drawing a frame
                        self.send({"t": "pong", "n": msg.get("n")})
                    else:
                        self.inbox.put(msg)
        except OSError:
            pass
        self.inbox.put({"t": "_disconnected"})

    def send(self, msg: dict) -> None:
        try:
            with self.send_lock:  # the reader thread answers pings
                self.sock.sendall(protocol.encode(msg))
        except OSError:
            pass

    def close(self) -> None:
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
            self.sock.close()
        except OSError:
            pass

    def poll(self):
        while True:
            try:
                yield self.inbox.get_nowait()
            except queue.Empty:
                return


def load_fon(path: str, tw: int, th: int) -> tcod.tileset.Tileset:
    width, height, tiles = fon.load(path, (tw, th))
    tileset = tcod.tileset.Tileset(width, height)
    for code, tile in tiles.items():
        tileset[tcod.tileset.CHARMAP_CP437[code]] = tile
    return tileset


def load_font(path: str, tw: int, th: int) -> tcod.tileset.Tileset:
    lower = path.lower()
    if lower.endswith((".ttf", ".otf")):
        return tcod.tileset.load_truetype_font(path, tw, th)
    if lower.endswith(".fon"):
        return load_fon(path, tw, th)
    return tcod.tileset.load_tilesheet(path, 16, 16, tcod.tileset.CHARMAP_CP437)


def load_tileset(path: str | None, tw: int, th: int):
    if path:
        return load_font(path, tw, th)
    for cand in FONT_CANDIDATES:
        if os.path.exists(cand):
            try:
                return load_font(cand, tw, th)
            except Exception:
                continue
    return None  # let libtcod pick its fallback font


def open_window(tileset):
    """The game window. Use it in a `with` block; pair it with new_console()."""
    context = tcod.context.new(columns=SCREEN_W, rows=SCREEN_H, tileset=tileset,
                               title="Togetherogue", vsync=True)
    window = getattr(context, "sdl_window", None)
    if window is not None and hasattr(window, "start_text_input"):
        try:  # needed on SDL3-based tcod versions; harmless elsewhere
            window.start_text_input()
        except Exception:
            pass
    return context


def new_console() -> tcod.console.Console:
    return tcod.console.Console(SCREEN_W, SCREEN_H, order="F")


def play(context, console, net: Net, leave_note: str = "", intro: tuple = ()) -> bool:
    """Runs the game until the player leaves. Returns False if they closed the window."""
    view = ClientView()
    for line in intro:
        view.messages.append((line, (140, 230, 140)))
    keymap = build_keymap()
    slot_keys = build_slot_keys()
    enter_keys = key_set("RETURN", "KP_ENTER", "RETURN2")
    escape_keys = key_set("ESCAPE")
    backspace_keys = key_set("BACKSPACE")
    help_keys = key_set("F1")
    sprint_keys = key_set("LSHIFT", "RSHIFT")
    held: dict = {}   # movement keys currently down, oldest first
    sent_dir = None   # the direction the server thinks is held
    settle_at = 0.0   # when a partial release takes effect
    auto_walk = False   # right mouse button is held
    auto_press = False  # the walk has only just started
    auto_depth = 0      # the floor it started on; it ends if that changes
    last_hold_at = 0.0
    sprinting = False

    def send_sprint(on):
        nonlocal sprinting
        if on != sprinting:
            sprinting = on
            net.send({"t": "act", "a": "sprint", "on": on})

    def send_hold(direction, press=False):
        dx, dy = direction or (0, 0)
        net.send({"t": "act", "a": "hold", "dx": dx, "dy": dy, "press": press})

    while True:
        for msg in net.poll():
            view.apply(msg)

        frame = view.draw()
        console.rgb["ch"] = frame["ch"]
        console.rgb["fg"] = frame["fg"]
        console.rgb["bg"] = frame["bg"]
        context.present(console, keep_aspect=True)

        for event in tcod.event.get():
            if isinstance(event, tcod.event.Quit):
                return False
            if isinstance(event, tcod.event.WindowEvent) and event.type == "WindowFocusLost":
                held.clear()  # the key-up would go to the other window
                auto_walk = False
                send_sprint(False)
            if isinstance(event, tcod.event.WindowEvent) and event.type == "WindowLeave":
                view.mouse = None
            if isinstance(event, (tcod.event.MouseMotion, tcod.event.MouseButtonDown)):
                tile = context.convert_event(event).position
                view.mouse = (int(tile[0]), int(tile[1]))
            if isinstance(event, tcod.event.MouseButtonDown) and event.button == tcod.event.MouseButton.RIGHT:
                auto_walk, auto_press, auto_depth = True, True, view.depth
            if isinstance(event, tcod.event.MouseButtonUp) and event.button == tcod.event.MouseButton.RIGHT:
                auto_walk = False
            if isinstance(event, tcod.event.KeyUp):
                if event.sym in sprint_keys:
                    send_sprint(False)
                held.pop(event.sym, None)
                settle_at = time.monotonic() + RELEASE_GRACE
            action = None
            if view.chat_mode:
                if isinstance(event, tcod.event.TextInput):
                    view.chat_buf = (view.chat_buf + event.text)[:200]
                elif isinstance(event, tcod.event.KeyDown):
                    if event.sym in enter_keys:
                        if view.chat_buf.strip():
                            net.send({"t": "chat", "text": view.chat_buf})
                        view.chat_mode, view.chat_buf = False, ""
                    elif event.sym in escape_keys:
                        view.chat_mode, view.chat_buf = False, ""
                    elif event.sym in backspace_keys:
                        view.chat_buf = view.chat_buf[:-1]
                continue
            if isinstance(event, tcod.event.KeyDown):
                if event.sym in sprint_keys:
                    send_sprint(True)
                if event.sym in enter_keys:
                    view.chat_mode, view.chat_buf = True, ""
                    held.clear()
                    auto_walk = False
                    send_sprint(False)
                    continue
                if event.sym in escape_keys:
                    if not view.connected:
                        return True
                    view.show_pack = view.drop_mode = view.show_help = view.show_tally = False
                    view.shop = None
                    view.leave_prompt = ""
                elif event.sym in help_keys and not event.repeat:
                    view.toggle_help()
                elif event.sym in keymap and not event.repeat:
                    held[event.sym] = keymap[event.sym]
                    sent_dir = held_direction(held)
                    send_hold(sent_dir, press=True)  # here, so even the shortest tap counts
                elif event.sym in slot_keys and not event.repeat \
                        and not event.mod & tcod.event.Modifier.SHIFT:  # shift+4 is $
                    slot = slot_keys[event.sym]
                    if view.shop is not None:
                        if slot < len(view.shop):
                            net.send({"t": "act", "a": "buy", "id": view.shop[slot]["id"]})
                    else:
                        verb = "drop" if view.drop_mode else "use"
                        net.send({"t": "act", "a": verb, "slot": slot})
                        view.drop_mode = False
            elif isinstance(event, tcod.event.TextInput):
                if view.leave_prompt:
                    if event.text in ("q", "Q"):
                        return True
                    view.leave_prompt = ""
                elif event.text == "?":
                    view.toggle_help()
                elif event.text == "t":
                    view.show_tally = not view.show_tally
                    view.show_pack = view.drop_mode = view.show_help = False
                elif event.text == "i":
                    view.show_pack = not view.show_pack
                    view.drop_mode = view.show_help = view.show_tally = False
                elif event.text == "d":
                    view.drop_mode = True
                    view.show_help = view.show_tally = False
                    view.shop = None
                elif event.text == "$" and view.drop_mode:
                    action, view.drop_mode = "dropgold", False
                else:
                    action = CHAR_ACTIONS.get(event.text)
            if action == "quit":
                if not view.connected:
                    return True
                view.leave_prompt = f"Press Q again to leave{leave_note}, Esc to stay."
            elif action:
                net.send({"t": "act", "a": action})

        if view.depth != auto_depth:
            auto_walk = False  # took the stairs; don't wander off on the new floor
        target = view.hovered() if auto_walk else None
        auto_dir = view.walk_step(*target) if target else None
        wanted = held_direction(held) if held else auto_dir
        now = time.monotonic()
        if wanted != sent_dir and (wanted is None or auto_press or now >= settle_at):
            sent_dir = wanted
            send_hold(sent_dir, press=auto_press and wanted is not None)
            last_hold_at = now
        elif auto_dir is not None and wanted == sent_dir and now - last_hold_at >= AUTO_RESEND:
            send_hold(sent_dir)
            last_hold_at = now
        auto_press = False

        time.sleep(1 / 120)  # in case vsync isn't available


def main() -> None:
    ap = argparse.ArgumentParser(description="Togetherogue client")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--name", default=os.environ.get("USER") or os.environ.get("USERNAME") or "Adventurer")
    ap.add_argument("--font", help="a .ttf font, a Windows .fon bitmap font, or a 16x16 CP437 tilesheet .png")
    ap.add_argument("--tile", default="11x20", help="cell size in pixels for TTF fonts, or which size to use from a .fon, e.g. 12x16")
    args = ap.parse_args()
    tw, th = (int(v) for v in args.tile.lower().split("x"))

    try:
        net = Net(args.host, args.port, args.name)
    except OSError as exc:
        sys.exit(f"Could not connect to {args.host}:{args.port}: {exc}")

    with open_window(load_tileset(args.font, tw, th)) as context:
        play(context, new_console(), net)
    net.close()


if __name__ == "__main__":
    main()
