"""The action log: one line of shorthand for each thing that happens in a run.

The world writes the lines (World.note). Each player's game saves its own copy, so joining
someone else's game still leaves you a file, and a server with nobody at it saves one too.
"""
from __future__ import annotations

import os
import time

from .settings import default_path

KEEP_FILES = 200    # the oldest logs go once there are more than this
LEGEND = ("# time since the run began (h:mm:ss.s), floor, who, what happened",
          "# 3/20 is health left of max, and -5 is damage. goblin#14 is one particular goblin",
          "# CONSOLE marks test commands, and ERROR marks something going wrong in the game itself")


def default_folder() -> str:
    return os.path.join(os.path.dirname(default_path()), "logs")


class Ledger:
    """Saves log messages to a text file, starting a new file for each run."""

    def __init__(self, folder: str | None = None):
        self.folder = folder or default_folder()
        self.path = ""
        self.run: tuple | None = None

    def apply(self, msg: dict) -> None:
        if msg.get("t") != "log":
            return
        if "head" not in msg:
            self._write(msg["line"])
        elif (msg["run"], msg["seed"]) != self.run:
            self.run = msg["run"], msg["seed"]
            self.path = os.path.join(self.folder, f"{time.strftime('%Y-%m-%d_%H-%M-%S')}_seed{msg['seed']}.txt")
            self._write("\n".join([f"# {msg['head']}", *LEGEND]))
            self._prune()

    def _write(self, text: str) -> None:
        if not self.path:
            return
        try:  # reopened each time, so a crash can't lose the lines leading up to it
            os.makedirs(self.folder, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(text + "\n")
        except OSError:
            pass  # not being able to write shouldn't stop anyone playing

    def _prune(self) -> None:
        try:
            names = sorted(n for n in os.listdir(self.folder) if n.endswith(".txt"))
            for name in names[:-KEEP_FILES]:
                os.remove(os.path.join(self.folder, name))
        except OSError:
            pass
