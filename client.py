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

from game import controls, fon, protocol, settings
from game.constants import DEFAULT_PORT, PROTOCOL_VERSION, SCREEN_H, SCREEN_W
from game.ledger import Ledger
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

# Commands that go straight to the server, and what they're called there.
SERVER_ACTIONS = {"pickup": "pickup", "quit": "quit", "heal": "quickheal", "sort": "sort"}

# Two fingers never leave a diagonal at the same moment. Waiting this long before acting
# on a partial release stops the last key from stepping you along it by accident.
RELEASE_GRACE = 0.05
# The server drops a held direction that hits something. While auto-walking, it's sent again
# after this long with no new position, so a blocked route recovers by itself.
AUTO_RESEND = 0.3


def build_keymap(bindings: dict) -> dict:
    """Movement keys. These are tracked as held or released, so holding one keeps moving.
    Yours come first, then the fixed ones, except any you've given another job."""
    keys = tcod.event.KeySym
    taken = {controls.key_id(action, key) for action, key in bindings.items()}
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
            if sym is not None and name not in taken:
                out[sym] = action
    for action, step in controls.DIRECTIONS.items():
        sym = getattr(keys, bindings[action], None)
        if sym is not None:
            out[sym] = step
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

    def __init__(self, host: str, port: int, name: str, timeout: float = 10, look: dict | None = None,
                 password: str = ""):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(None)
        self.inbox: queue.Queue = queue.Queue()
        self.send_lock = threading.Lock()
        self.send({"t": "hello", "name": name, "version": PROTOCOL_VERSION, "password": password, **(look or {})})
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


def play(context, console, net: Net, leave_note: str = "", intro: tuple = (), config: dict | None = None) -> bool:
    """Runs the game until the player leaves. Returns False if they closed the window."""
    bindings = controls.load(config or {})
    view = ClientView(config)
    ledger = Ledger()
    for line in intro:
        view.messages.append((line, (140, 230, 140)))
    keymap = build_keymap(bindings)
    pressed = {action: key for action, key in bindings.items() if action not in controls.HELD}
    typed_keys = {key: action for action, key in pressed.items() if len(key) == 1}
    named_keys = {getattr(tcod.event.KeySym, key, None): action for action, key in pressed.items() if len(key) > 1}
    slot_keys = build_slot_keys()
    enter_keys = key_set("RETURN", "KP_ENTER", "RETURN2")
    escape_keys = key_set("ESCAPE")
    tab_keys = key_set("TAB")
    backspace_keys = key_set("BACKSPACE")
    help_keys = key_set("F1")
    sprint_keys = key_set(bindings["sprint"], "RSHIFT")
    console_keys = key_set("GRAVE", "F2")
    yes_keys, no_keys = key_set("y") | enter_keys, key_set("n") | escape_keys
    up_keys, down_keys = key_set("UP"), key_set("DOWN")
    log_up_keys, log_down_keys = up_keys | key_set("PAGEUP"), down_keys | key_set("PAGEDOWN")
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
            ledger.apply(msg)
            view.log_path = ledger.path

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
            if isinstance(event, tcod.event.MouseButtonDown) and event.button == tcod.event.MouseButton.LEFT \
                    and not view.console_open and not view.chat_mode:
                slot = view.pack_slot_at(view.mouse)
                if slot is not None:
                    net.send({"t": "act", "a": "drop" if view.drop_mode else "use", "slot": slot})
                    view.drop_mode = False
            if isinstance(event, tcod.event.MouseButtonDown) and event.button == tcod.event.MouseButton.RIGHT:
                auto_walk, auto_press, auto_depth = True, True, view.depth
            if isinstance(event, tcod.event.MouseButtonUp) and event.button == tcod.event.MouseButton.RIGHT:
                auto_walk = False
            if isinstance(event, tcod.event.KeyUp):
                if event.sym in sprint_keys:
                    send_sprint(False)
                held.pop(event.sym, None)
                settle_at = time.monotonic() + RELEASE_GRACE
            if isinstance(event, tcod.event.MouseWheel):
                view.wheel(event.y)
            action = command = None
            if view.console_open:
                if isinstance(event, tcod.event.MouseButtonDown) and event.button == tcod.event.MouseButton.LEFT:
                    clicked = view.console_click(view.mouse)
                    if clicked == "close":
                        view.console_open = False
                    elif clicked:  # runs it, and keeps what was being typed
                        typed, view.console_buf = view.console_buf, clicked
                        net.send({"t": "cmd", "text": view.console_submit()})
                        view.console_buf = typed
                elif isinstance(event, tcod.event.TextInput):
                    if event.text not in ("`", "~"):  # the key that opened it
                        view.console_buf = (view.console_buf + event.text)[:200]
                elif isinstance(event, tcod.event.KeyDown):
                    if event.sym in enter_keys:
                        text = view.console_submit()
                        if text:
                            net.send({"t": "cmd", "text": text})
                    elif event.sym in escape_keys or (event.sym in console_keys and not event.repeat):
                        view.console_open = False
                    elif event.sym in backspace_keys:
                        view.console_buf = view.console_buf[:-1]
                    elif event.sym in tab_keys:
                        view.console_complete()
                    elif event.sym in up_keys:
                        view.console_recall(1)
                    elif event.sym in down_keys:
                        view.console_recall(-1)
                continue
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
                if view.prompt is not None and event.sym in yes_keys | no_keys:
                    if event.sym in yes_keys:
                        net.send({"t": "act", "a": "enhance", "x": view.prompt["x"], "y": view.prompt["y"]})
                    view.prompt = None
                    continue
                if event.sym in console_keys and not event.repeat:
                    view.console_open, view.console_buf = True, ""
                    held.clear()
                    auto_walk = False
                    send_sprint(False)
                    continue
                if event.sym in enter_keys and view.status[:1] == ["over"]:
                    if not event.repeat:
                        net.send({"t": "act", "a": "ready"})
                    continue
                if event.sym in enter_keys:
                    view.chat_mode, view.chat_buf = True, ""
                    held.clear()
                    auto_walk = False
                    send_sprint(False)
                    continue
                if event.sym in escape_keys:
                    if not view.connected:
                        return True
                    view.show_pack = view.drop_mode = view.show_help = view.show_tally = view.show_log = False
                    view.shop = None
                    view.leave_prompt = ""
                elif event.sym in tab_keys and view.shop is not None:
                    view.toggle_selling()
                elif view.show_log and event.sym in log_up_keys | log_down_keys:
                    view.scroll_log(1 if event.sym in log_up_keys else -1)
                elif event.sym in help_keys and not event.repeat:
                    view.toggle_help()
                elif event.sym in named_keys and not event.repeat:
                    command = named_keys[event.sym]
                elif event.sym in keymap and not event.repeat:
                    held[event.sym] = keymap[event.sym]
                    sent_dir = held_direction(held)
                    send_hold(sent_dir, press=True)  # here, so even the shortest tap counts
                elif event.sym in slot_keys and not event.repeat \
                        and not event.mod & tcod.event.Modifier.SHIFT:  # shift+4 is $
                    slot = slot_keys[event.sym]
                    if view.shop is not None and view.shop_selling:
                        if slot < len(view.pack):
                            net.send({"t": "act", "a": "sell", "slot": slot})
                    elif view.shop is not None:
                        if slot < len(view.shop):
                            net.send({"t": "act", "a": "buy", "id": view.shop[slot]["id"]})
                    else:
                        verb = "drop" if view.drop_mode else "use"
                        net.send({"t": "act", "a": verb, "slot": slot})
                        view.drop_mode = False
            elif isinstance(event, tcod.event.TextInput):
                if view.leave_prompt:
                    if event.text in ("q", "Q") or typed_keys.get(event.text) == "quit":
                        return True
                    view.leave_prompt = ""
                elif event.text == "$" and view.drop_mode:
                    action, view.drop_mode = "dropgold", False
                else:
                    command = typed_keys.get(event.text)
            if command == "help":
                view.toggle_help()
            elif command == "tally":
                view.show_tally = not view.show_tally
                view.show_pack = view.drop_mode = view.show_help = view.show_log = False
            elif command == "log":
                view.toggle_log()
            elif command == "pack":
                view.show_pack = not view.show_pack
                view.drop_mode = view.show_help = view.show_tally = view.show_log = False
            elif command == "drop":
                view.drop_mode = True
                view.show_help = view.show_tally = view.show_log = False
                view.shop = None
            elif command:
                action = SERVER_ACTIONS[command]
            if action == "quit":
                if not view.connected:
                    return True
                view.leave_prompt = f"Press {view.keys['quit']} again to leave{leave_note}, Esc to stay."
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
    ap.add_argument("--password", default="", help="the server's password, if it has one")
    ap.add_argument("--font", help="a .ttf font, a Windows .fon bitmap font, or a 16x16 CP437 tilesheet .png")
    ap.add_argument("--tile", default="11x20", help="cell size in pixels for TTF fonts, or which size to use from a .fon, e.g. 12x16")
    args = ap.parse_args()
    tw, th = (int(v) for v in args.tile.lower().split("x"))

    try:
        net = Net(args.host, args.port, args.name, password=args.password)
    except OSError as exc:
        sys.exit(f"Could not connect to {args.host}:{args.port}: {exc}")

    with open_window(load_tileset(args.font, tw, th)) as context:
        play(context, new_console(), net, config=settings.load())
    net.close()


if __name__ == "__main__":
    main()
