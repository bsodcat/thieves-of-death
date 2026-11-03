"""The Togetherogue app: main menu, setup screens and the Server Tool.

   type python togetherogue.py   ->   or double-click Togetherogue.exe
"""
from __future__ import annotations

import socket
import sys
import time

import tcod.event

import client
from game import controls, seasons, settings
from game.constants import DEFAULT_DIFFICULTY, DIFFICULTIES
from game.entities import PLAYER_COLOR_NAMES, PLAYER_GLYPHS
from game.menu import DIM, GREEN, TEXT, WHITE, Form, Row
from game.version import AUTHOR, STARTED, VERSION
from server import ServerRunner

FONTS = {
    "Terminal (10x20)":      ("C:/Windows/Fonts/8514oem.fon", 10, 20),
    "Terminal small (8x12)": ("C:/Windows/Fonts/vgaoem.fon", 8, 12),
    "Terminal wide (12x16)": ("C:/Windows/Fonts/dosapp.fon", 12, 16),
    "Consolas (11x20)":      ("C:/Windows/Fonts/consola.ttf", 11, 20),
}
TYPED_WAIT = 0.05  # how long after a key press what it typed can take to arrive


def _difficulty_line(name: str) -> str:
    """What a difficulty means, in a line for the setup screen."""
    rules = DIFFICULTIES[name]
    speed = {2.0: "slow", 1.0: "fast"}.get(rules["monster_time"], "normal")
    health, _ = rules["toughness"]
    tough = "weaker" if health < 1 else "tougher" if health > 1 else "normal"
    revive = f"revive a teammate in {rules['revive']:.0f}s" if rules["revive"] else "no revives"
    heal = "you heal over time" if rules["regen"] else "no healing over time"
    monsters = ", ".join(w for w in (speed, tough) if w != "normal") or "normal"
    return f"{name}: {monsters} monsters; {heal}; {revive}."


SETUP_NOTE = "Leave the seed blank for a random dungeon.\n" + "\n".join(map(_difficulty_line, DIFFICULTIES))


class WindowClosed(Exception):
    pass


class FontChanged(Exception):
    pass


def load_font_choice(name: str):
    path, tw, th = FONTS.get(name, FONTS["Terminal (10x20)"])
    try:
        return client.load_font(path, tw, th)
    except Exception:  # missing from this system: fall back to whatever's available
        return client.load_tileset(None, 11, 20)


def primary_address() -> str | None:
    """The address of the network adapter that reaches the outside world. Connecting a UDP
    socket only picks a route; it doesn't send anything."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            return s.getsockname()[0]
    except OSError:
        return None


def lan_addresses() -> list[str]:
    """Addresses friends can reach, best first. Virtual adapters would otherwise come first."""
    try:
        found = socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        found = []
    primary = primary_address()
    ordered = ([primary] if primary else []) + [a for a in found if a != primary]
    return [a for a in ordered if not a.startswith(("127.", "169.254.", "0."))]


def parse_port(text: str) -> int:
    if not text.isdigit() or not 1 <= int(text) <= 65535:
        raise ValueError("The port must be a number from 1 to 65535.")
    return int(text)


def parse_setup(values: dict) -> tuple[int, int | None, str]:
    """(port, seed, difficulty) from a setup form. Raises ValueError with a message to show."""
    difficulty = values.get("difficulty")
    return (parse_port(values["port"]), int(values["seed"]) if values["seed"] else None,
            difficulty if difficulty in DIFFICULTIES else DEFAULT_DIFFICULTY)


def title_footer() -> str:
    return f"Version {VERSION}   {STARTED}   Made by {AUTHOR}"


def port_error(port: int) -> str:
    return f"Port {port} is in use. Is a server already running? Try another port."


class App:
    def __init__(self, context, console, config: dict):
        self.context, self.console, self.config = context, console, config

    def season_fn(self):
        """The holiday theme to use, unless the player has turned them off."""
        return seasons.current() if self.config["holiday_themes"] == "On" else None

    def remember(self, values: dict) -> None:
        self.config.update(values)
        settings.save(self.config)

    def inputs(self) -> list:
        """This frame's input, as (name, value) pairs for a Form."""
        keys = tcod.event.KeySym
        names = {keys.UP: "up", keys.DOWN: "down", keys.TAB: "down", keys.LEFT: "left", keys.RIGHT: "right",
                 keys.RETURN: "enter", keys.KP_ENTER: "enter", keys.ESCAPE: "back", keys.BACKSPACE: "backspace"}
        found = []
        for event in tcod.event.get():
            if isinstance(event, tcod.event.Quit):
                raise WindowClosed
            if isinstance(event, tcod.event.KeyDown) and event.sym in names:
                found.append((names[event.sym], None))
            elif isinstance(event, tcod.event.TextInput):
                found.extend(("text", c) for c in event.text)
            elif isinstance(event, tcod.event.MouseMotion):
                found.append(("hover", int(self.context.convert_event(event).position[1])))
            elif isinstance(event, tcod.event.MouseButtonDown):
                found.append(("click", int(self.context.convert_event(event).position[1])))
        return found

    def present(self, form: Form, extra=None) -> None:
        form.draw(self.console)
        if extra:
            extra(self.console)
        self.context.present(self.console, keep_aspect=True)

    def show(self, form: Form, extra=None, timeout: float | None = None) -> str | None:
        """Runs a form until it returns an action, or for `timeout` seconds."""
        end = None if timeout is None else time.monotonic() + timeout
        while end is None or time.monotonic() < end:
            self.present(form, extra)
            for name, value in self.inputs():
                action = form.handle(name, value)
                if action:
                    return action
            time.sleep(1 / 60)
        return None

    # ----------------------------- Screens -------------------------------

    def main_menu(self) -> None:
        form = Form("", [Row("Host Game", action="host"), Row("Join Game", action="join"),
                         Row("Character", action="character"), Row("Server Tool", action="tool"),
                         Row("Options", action="options"), Row("Quit", action="quit")])
        form.footer = title_footer()
        screens = {"host": self.host_game, "join": self.join_game, "character": self.character,
                   "tool": self.server_tool, "options": self.options}
        while True:
            form.title = seasons.greeting(self.season_fn())  # options may have just changed
            action = self.show(form)
            if action == "quit":
                return
            if action in screens:
                screens[action]()

    def setup_rows(self) -> list:
        c = self.config
        return [Row("Port", "port", c["port"], digits=True, limit=5),
                Row("Dungeon seed", "seed", c["seed"], digits=True, limit=10),
                Row("Difficulty", "difficulty", c["difficulty"], choices=tuple(DIFFICULTIES))]

    def look(self) -> dict:
        return {"aim": self.config["ranged_target"], "glyph": self.config["shape"], "color": self.config["color"],
                "pickup": controls.labels(controls.load(self.config))["pickup"]}

    def run_game(self, net, leave_note: str = "", intro: tuple = ()) -> None:
        try:
            if not client.play(self.context, self.console, net, leave_note, intro, self.config):
                raise WindowClosed
        finally:
            net.close()

    def host_game(self) -> None:
        form = Form("Host a Game",
                    [Row("Your name", "name", self.config["name"], limit=16), *self.setup_rows(),
                     Row("Start Game", action="go"), Row("Back", action="back")],
                    note=SETUP_NOTE)
        while self.show(form) == "go":
            values = form.values()
            self.remember(values)
            try:
                port, seed, difficulty = parse_setup(values)
            except ValueError as exc:
                form.error = str(exc)
                continue
            runner = ServerRunner(port, seed, difficulty=difficulty, season_fn=self.season_fn)
            try:
                runner.start()
            except OSError:
                form.error = port_error(port)
                continue
            try:
                net = client.Net("127.0.0.1", runner.port, values["name"], look=self.look())
                shares = [f"Friends can join at {a}, port {runner.port}." for a in lan_addresses()[:1]]
                self.run_game(net, " (this ends the game for everyone)", tuple(shares))
            finally:
                runner.stop()
            return

    def join_game(self) -> None:
        c = self.config
        form = Form("Join a Game",
                    [Row("Your name", "name", c["name"], limit=16), Row("Address", "address", c["address"], limit=40),
                     Row("Port", "port", c["port"], digits=True, limit=5),
                     Row("Connect", action="go"), Row("Back", action="back")],
                    note="Ask the host for their address and port.")
        while self.show(form) == "go":
            values = form.values()
            self.remember(values)
            form.error = ""
            try:
                port = parse_port(values["port"])
            except ValueError as exc:
                form.error = str(exc)
                continue
            form.message = f"Connecting to {values['address']}..."
            self.present(form)
            form.message = ""
            try:
                net = client.Net(values["address"], port, values["name"], timeout=5, look=self.look())
            except OSError:
                form.error = f"Couldn't reach {values['address']}:{port}. Check the address and that it's running."
                continue
            self.run_game(net)
            return

    def server_tool(self) -> None:
        form = Form("Server Tool", [*self.setup_rows(), Row("Start Server", action="go"), Row("Back", action="back")],
                    note="Runs a server without playing.\n" + SETUP_NOTE)
        while self.show(form) == "go":
            values = form.values()
            self.remember(values)
            try:
                port, seed, difficulty = parse_setup(values)
            except ValueError as exc:
                form.error = str(exc)
                continue
            runner = ServerRunner(port, seed, difficulty=difficulty, season_fn=self.season_fn)
            try:
                runner.start()
            except OSError:
                form.error = port_error(port)
                continue
            try:
                self.server_status(runner)
            finally:
                runner.stop()
            return

    def server_status(self, runner: ServerRunner) -> None:
        form = Form("Server Running", [Row("Stop Server", action="stop")])
        addresses = lan_addresses()
        armed = False

        def extra(console) -> None:
            status = runner.status
            y = 12
            console.print(20, y, f"Port {runner.port}    Seed {status['seed']}    Run {status['run']}"
                                 f"    {status['difficulty']}", fg=WHITE)
            y += 1
            shown = ", ".join(addresses[:2]) or "no network found"
            console.print(20, y, f"On your network, friends join at: {shown}", fg=GREEN)
            y += 1
            console.print(20, y, f"Over the internet, forward TCP port {runner.port} on your router.", fg=DIM)
            y += 2
            console.print(20, y, f"Players ({len(status['players'])})", fg=WHITE)
            y += 1
            for p in status["players"][:6]:
                ping = "--" if p["ping"] is None else f"{p['ping']}ms"
                health = f"{p['hp']}/{p['mhp']}" if p["alive"] else "down" if p["down"] else "dead"
                console.print(20, y, f"{p['name']:<18}Floor {p['depth']:<4}{ping:<9}{health}", fg=TEXT)
                y += 1
            y = max(y, 24) + 1
            console.print(20, y, "Log", fg=WHITE)
            for line in list(runner.log)[-6:]:
                y += 1
                console.print(20, y, line[:70], fg=DIM)

        while True:
            action = self.show(form, extra)
            if action == "back":
                continue  # stopping is a button, so Esc can't drop everyone by accident
            if action == "stop":
                if runner.status["players"] and not armed:
                    armed = True
                    form.rows[0].label = "Players are connected: click again to stop"
                    continue
                return

    def character(self) -> None:
        c = self.config
        form = Form("Create Your Character",
                    [Row("Name", "name", c["name"], limit=16),
                     Row("Shape", "shape", c["shape"], choices=PLAYER_GLYPHS),
                     Row("Color", "color", c["color"], choices=tuple(PLAYER_COLOR_NAMES)),
                     Row("Save", action="save"), Row("Back", action="back")],
                    note="Use left and right to look through shapes and colors.")

        def preview(console) -> None:
            # The character standing in a little room, as they'll look in the dungeon.
            x0, y0 = 45, 22
            values = form.values()
            for x in range(9):
                for y in range(5):
                    wall = x in (0, 8) or y in (0, 4)
                    console.print(x0 + x, y0 + y, "#" if wall else "\u00b7", fg=(150, 140, 128) if wall else (88, 88, 104),
                                  bg=(44, 40, 36) if wall else (16, 16, 22))
            console.print(x0 + 4, y0 + 2, values["shape"], fg=PLAYER_COLOR_NAMES.get(values["color"], WHITE),
                          bg=(16, 16, 22))

        if self.show(form, preview) == "save":
            self.remember(form.values())

    def options(self) -> None:
        form = Form("Options", [Row("Font", "font", self.config["font"], choices=tuple(FONTS)),
                                Row("Holiday themes", "holiday_themes", self.config["holiday_themes"],
                                    choices=("On", "Off")),
                                Row("Ranged weapons aim at", "ranged_target", self.config["ranged_target"],
                                    choices=("Strongest", "Weakest")),
                                Row("Controls", action="controls"),
                                Row("Save", action="save"), Row("Back", action="back")],
                    note="Holiday themes follow the host's setting.")
        action = self.show(form)
        while action == "controls":
            self.controls_screen()
            action = self.show(form)
        if action != "save":
            return
        changed = form.values()["font"] != self.config["font"]
        self.remember(form.values())
        if changed:
            raise FontChanged


    def controls_screen(self) -> None:
        """Pick a row, then press the key for it. Each change saves straight away."""
        def rows() -> list:
            shown = controls.labels(keys)
            return [*(Row(name, value=shown[action], action=f"bind {action}") for action, name, _ in controls.ACTIONS),
                    Row("Reset to defaults", action="reset"), Row("Back", action="back")]

        keys = controls.load(self.config)
        form = Form("Controls", rows(), top=7, step=1,
                    note="Choose one and press its new key. Arrows, numpad and hjkl keep working.")
        while True:
            action = self.show(form)
            if action == "back":
                return
            form.error = form.message = ""
            if action == "reset":
                keys = controls.defaults()
            else:
                bind = action.split()[1]
                form.message = "Press a key, or Esc to cancel."
                self.present(form)
                pressed = self.read_key(bind in controls.HELD)
                form.message = ""
                if pressed is None:
                    continue
                form.error = controls.assign(keys, bind, *pressed)
            index = form.index
            form.rows = rows()
            form.index = index
            self.remember({controls.setting(a): key for a, key in keys.items()})

    def read_key(self, held: bool) -> tuple[str, str] | None:
        """The next key pressed, as its name and what it typed, or None for Esc. Unless it's for
        holding down, Shift alone doesn't count, as it may be on the way to a key like >."""
        shifts = (tcod.event.KeySym.LSHIFT, tcod.event.KeySym.RSHIFT)
        name = None
        wait_until = None
        text = ""
        while wait_until is None or time.monotonic() < wait_until:
            for event in tcod.event.get():
                if isinstance(event, tcod.event.Quit):
                    raise WindowClosed
                if isinstance(event, tcod.event.KeyDown) and name is None and (held or event.sym not in shifts):
                    if event.sym == tcod.event.KeySym.ESCAPE:
                        return None
                    name = event.sym.name
                    wait_until = time.monotonic() + TYPED_WAIT  # what it types comes as its own event
                elif isinstance(event, tcod.event.TextInput) and name is not None and not text:
                    text = event.text
            time.sleep(1 / 120)
        return name, text


def self_test() -> int:
    """For checking a built exe, which has no terminal: exit code 0 means the game works."""
    runner = ServerRunner(0, host="127.0.0.1")
    runner.start()
    try:
        net = client.Net("127.0.0.1", runner.port, "SelfTest")
        end = time.monotonic() + 5
        while time.monotonic() < end:
            if any(m.get("t") == "state" for m in net.poll()):
                load_font_choice("Terminal (10x20)")
                return 0
            time.sleep(0.01)
        return 1
    finally:
        runner.stop()


def main() -> None:
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    config = settings.load()
    while True:
        with client.open_window(load_font_choice(config["font"])) as context:
            try:
                App(context, client.new_console(), config).main_menu()
                return
            except WindowClosed:
                return
            except FontChanged:
                pass  # reopen with the new font


if __name__ == "__main__":
    main()
