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

# Merchants. Each MERCHANT_EVERY floors, one may be waiting. The levitation potion
# shows up in LEVITATION_STOCK_CHANCE of their shops.
MERCHANT_EVERY = 5
MERCHANT_CHANCE = 0.6
MERCHANT_STOCK = (3, 5)
LEVITATION_STOCK_CHANCE = 0.3

# Terrain. The chance of each on a floor, and how many pits a floor with them gets.
LAKE_CHANCE = 0.4
RIVER_CHANCE = 0.35
PIT_CHANCE = 0.35
PIT_COUNT = (1, 3)
FALL_DAMAGE = (3, 6)       # a fall can't kill you; it leaves you on 1 health at worst

# Torches. Each floor gets a few, kept apart and away from the stairs. Standing in full
# torchlight multiplies how far off monsters notice you by 1 + TORCH_NOTICE; it fades with distance.
TORCH_COUNT = (1, 3)
TORCH_RADIUS = 9
TORCH_SPACING = 16
TORCH_NOTICE = 0.75

# Locked rooms. Each floor in the range has LOCKED_ROOM_CHANCE of one, and its key lies
# KEY_DISTANCE floors above or below. There's one room per color in tiles.LOCK_COLORS at most.
LOCKED_ROOM_FLOORS = (4, 14)
LOCKED_ROOM_CHANCE = 0.15
KEY_DISTANCE = 2

# Stealth. The bar fills while you stand still and drains as you move; attacking
# empties it. A full bar shrinks monster detection range to STEALTH_RANGE_MIN of normal.
# Equipped gear makes noise (see items.py), which lowers how far the bar can fill.
STEALTH_MAX = 100
STEALTH_FILL_SECONDS = 3.0 # empty to full
STEALTH_MOVE_DRAIN = 20    # lost per step
STEALTH_RANGE_MIN = 0.3

# Stamina. Sprinting and attacking spend it, and it refills after STAMINA_REST_SECONDS
# without spending any. Below ATTACK_STAMINA your attacks take TIRED_ATTACK times as long.
STAMINA_MAX = 100
STAMINA_FILL_SECONDS = 6.0 # empty to full
STAMINA_REST_SECONDS = 0.75
SPRINT_STAMINA = 5         # spent per step
SPRINT_MOVE_COST = 0.6     # a sprinting step takes this share of a normal one
ATTACK_STAMINA = 8         # spent per attack
TIRED_ATTACK = 2

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

PROTOCOL_VERSION = 14
DEFAULT_PORT = 5555
