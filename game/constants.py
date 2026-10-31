"""Tunable constants shared by the server and the client."""

# Brogue's own layout: a 100x34 window with a 20-column sidebar,
# 3 message lines on top and a 79x29 dungeon.
MAP_W, MAP_H = 79, 29
SCREEN_W, SCREEN_H = 100, 34
SIDEBAR_W = 20
MSG_LINES = 3
MAP_X, MAP_Y = SIDEBAR_W + 1, MSG_LINES
LOOK_Y = SCREEN_H - 10     # the bottom of the sidebar is kept for the Look panel

# Time. Everything costs "ticks"; a normal move or attack is 100.
TICKS_PER_TURN = 100

# Real time. TURN_SECONDS is how long a normal move takes: lower it for a
# faster game. MONSTER_TIME slows monsters relative to players (1.0 = equal).
TURN_SECONDS = 0.16
TICKS_PER_SECOND = TICKS_PER_TURN / TURN_SECONDS
MONSTER_TIME = 1.5
TICK_RATE = 30             # server updates per second
PING_SECONDS = 1.0         # how often each player's ping is measured
PING_TIMEOUT = 5.0         # give up on an unanswered ping after this long

# Seconds between the whole party dying and a fresh dungeon.
RESET_DELAY = 4.0

# Items.
PACK_SIZE = 10             # slots, one per number key; potions of a kind share a slot
GOLD_DROP = 25             # gold dropped at a time

# Stealth. The bar fills while you stand still and drains as you move; attacking
# empties it. A full bar shrinks monster detection range to STEALTH_RANGE_MIN of normal.
# Equipped gear makes noise (see items.py), which lowers how far the bar can fill.
STEALTH_MAX = 100
STEALTH_FILL_SECONDS = 3.0 # empty to full
STEALTH_MOVE_DRAIN = 20    # lost per step
STEALTH_RANGE_MIN = 0.3

# Game modes. In Revive, a fallen player stays on the map as bones until a teammate
# stands next to them for REVIVE_SECONDS. Classic is permanent until the next run.
GAME_MODES = ("Classic", "Revive")
REVIVE_SECONDS = 3.0
REVIVE_HEALTH = 0.5        # share of full health a revived player comes back with
BONES_GLYPH = "%"

# Score = moves * SCORE_PER_MOVE + gold carried * SCORE_PER_GOLD.
SCORE_PER_MOVE = 1
SCORE_PER_GOLD = 10

# Combat and monsters.
DEEPEST_TABLE = 26         # the monster and item lists end here; deeper floors reuse this one
REGEN_TURNS = 300          # turns for a player to regenerate from 0 to full
DEFENSE_FACTOR = 0.987     # hit% = accuracy * DEFENSE_FACTOR ** defense
NOTICE_RANGE_SLEEPING = 7
NOTICE_RANGE_AWAKE = 14

PROTOCOL_VERSION = 11
DEFAULT_PORT = 5555
