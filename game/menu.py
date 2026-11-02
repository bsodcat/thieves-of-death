"""Menu forms: a list of text fields, choices and buttons.

Nothing here imports tcod. Input arrives as (name, value) pairs, so the tests can
drive a form without a window, and drawing needs only a console's `print`.
"""
from __future__ import annotations

from dataclasses import dataclass

from .constants import SCREEN_H, SCREEN_W

TITLE_Y = 3
ROW_Y = 9
ROW_STEP = 2
LABEL_X = 26
VALUE_X = 46

WHITE = (255, 255, 255)
TEXT = (200, 200, 200)
DIM = (130, 130, 140)
GOLD = (255, 215, 90)
RED = (255, 100, 100)
GREEN = (140, 230, 140)
FIELD_BG = (30, 30, 46)
SELECTED_BG = (50, 50, 90)


@dataclass
class Row:
    label: str
    key: str = ""            # the name in Form.values()
    value: str = ""
    choices: tuple = ()      # set for a choice row
    digits: bool = False     # text rows: numbers only
    limit: int = 30
    action: str = ""         # set for a button

    @property
    def is_text(self) -> bool:
        return not self.action and not self.choices


class Form:
    def __init__(self, title: str, rows: list, note: str = "", top: int = ROW_Y, step: int = ROW_STEP):
        self.title, self.rows, self.note = title, rows, note
        self.top, self.step = top, step
        self.index = 0
        self.error = ""
        self.message = ""
        self.footer = ""         # a line at the very bottom of the screen

    @property
    def row(self) -> Row:
        return self.rows[self.index]

    def values(self) -> dict:
        return {r.key: r.value for r in self.rows if r.key}

    def _cycle(self, step: int) -> None:
        row = self.row
        if row.choices:
            at = row.choices.index(row.value) if row.value in row.choices else 0
            row.value = row.choices[(at + step) % len(row.choices)]

    def row_at(self, y: int) -> int | None:
        for i in range(len(self.rows)):
            if y == self.top + i * self.step:
                return i
        return None

    def handle(self, name: str, value=None) -> str | None:
        """Takes one input. Returns a button's action, "back", or None."""
        if name == "up":
            self.index = (self.index - 1) % len(self.rows)
        elif name == "down":
            self.index = (self.index + 1) % len(self.rows)
        elif name in ("left", "right"):
            self._cycle(-1 if name == "left" else 1)
        elif name == "back":
            return "back"
        elif name == "backspace":
            if self.row.is_text:
                self.row.value = self.row.value[:-1]
        elif name == "text":
            row = self.row
            if row.is_text and value.isprintable() and (value.isdigit() or not row.digits):
                row.value = (row.value + value)[:row.limit]
        elif name == "enter":
            if self.row.action:
                return self.row.action
            if self.row.choices:
                self._cycle(1)
            else:
                self.index = (self.index + 1) % len(self.rows)
        elif name in ("hover", "click"):
            at = self.row_at(value)
            if at is None:
                return None
            self.index = at
            if name == "click":
                return self.handle("enter") if not self.row.is_text else None
        return None

    def draw(self, console) -> None:
        console.clear()
        title = "T O G E T H E R O G U E"
        console.print((SCREEN_W - len(title)) // 2, TITLE_Y, title, fg=GOLD)
        console.print((SCREEN_W - len(self.title)) // 2, TITLE_Y + 2, self.title, fg=WHITE)
        for i, row in enumerate(self.rows):
            y = self.top + i * self.step
            selected = i == self.index
            if row.action and row.value:  # a button that shows a setting, such as a key
                console.print(LABEL_X, y, row.label, fg=WHITE if selected else TEXT)
                console.print(VALUE_X, y, f" {row.value} ", fg=WHITE, bg=SELECTED_BG if selected else FIELD_BG)
                continue
            if row.action:
                text = f"  {row.label}  "
                x = (SCREEN_W - len(text)) // 2
                console.print(x, y, text, fg=WHITE if selected else TEXT, bg=SELECTED_BG if selected else None)
                continue
            console.print(LABEL_X, y, row.label, fg=WHITE if selected else TEXT)
            shown = f"< {row.value} >" if row.choices else row.value + ("_" if selected else "")
            console.print(VALUE_X, y, shown.ljust(row.limit + 1 if row.is_text else len(shown)), fg=WHITE,
                          bg=SELECTED_BG if selected else FIELD_BG)
        y = self.top + len(self.rows) * self.step + 1
        for text, color in ((self.note, DIM), (self.error, RED), (self.message, GREEN)):
            for line in text.splitlines():
                console.print(LABEL_X, y, line, fg=color)
                y += 1
        if self.footer:
            console.print((SCREEN_W - len(self.footer)) // 2, SCREEN_H - 2, self.footer, fg=DIM)
