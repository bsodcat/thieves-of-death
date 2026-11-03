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
MONSTER_SWING = 2          # monsters' melee attacks take this many times as long on top of that
TICK_RATE = 30             # server updates per second
PING_SECONDS = 1.0         # how often each player's ping is measured
PING_TIMEOUT = 5.0         # give up on an unanswered ping after this long

# Seconds between the whole party dying and a fresh dungeon.
RESET_DELAY = 4.0

# Items.
PACK_SIZE = 10             # slots, one per number key; potions of a kind share a slot
GOLD_DROP = 25             # gold dropped at a time

# The console's teleport lands you at least this many steps' walk from where you were.
# A potion of teleportation goes further: to a random floor of the whole dungeon.
TELEPORT_STEPS = 15

# Merchants. Each MERCHANT_EVERY floors, one may be waiting. The levitation potion
# shows up in LEVITATION_STOCK_CHANCE of their shops.
MERCHANT_EVERY = 5
MERCHANT_CHANCE = 0.6
MERCHANT_STOCK = (3, 5)
LEVITATION_STOCK_CHANCE = 0.3

# The end of the dungeon. ATRIUM_FLOOR is an empty hall leading down to the tower, whose
# floors from TOWER_FIRST to LAST_FLOOR are built to a plan rather than grown. See mapgen.
ATRIUM_FLOOR = 89
TOWER_FIRST = 90

# The tower has its own monsters, not the ordinary lists: (kind, weight).
TOWER_MONSTERS = (("skeleton_warrior", 6), ("zombie", 3), ("cultist", 2), ("wolf", 1))

# Ogres stop at their last floor in the list, and are this many times as common here.
OGRE_PEAK = (45, 55)
OGRE_PEAK_WEIGHT = 3
OGRE_LATE_SHARE = 0.4      # below the peak, nearly alone on the lists, only this many of them come

# Skeleton archers try to stay this many tiles from their target: closer and they back away,
# further and they come closer. They shoot every ARCHER_RELOAD seconds.
ARCHER_RANGE = (6, 11)
ARCHER_RELOAD = 2.5

# Slimes crawl about in numbers on these floors. Their hits, and walking through the trail they
# leave for SLIME_TRAIL seconds, slow you down and poison you.
SLIME_FLOORS = (25, 85)
SLIME_COUNT = (4, 5)
SLIME_TRAIL = 15.0
SLOW_SECONDS = 3.0
SLOW_FACTOR = 2            # a slowed step takes this many times as long
TOXIN_SECONDS = 6.0
TOXIN_DAMAGE = 1           # each second it lasts

# The lair's side rooms: one holds a hoard, one holds potions, and the others stand empty.
HOARD_PILES = 14
HOARD_GOLD = (300, 700)
POTION_ROOM = 8

# The goal. The dungeon ends at LAST_FLOOR, where the Amulet lies in the necromancer's room.
# Whoever carries it up the stairs on floor 1 wins the run for the whole party.
LAST_FLOOR = 99
VICTORY_SECONDS = 12.0     # how long the win stays on screen before a new dungeon

# The necromancer. Awake and in sight of a player, it raises zombies every SUMMON_SECONDS.
# Anyone who leaves its floor while it's awake is chased: wherever they are above it, more
# zombies come every TIDE_SECONDS, up to TIDE_MAX at a time, until the necromancer dies.
SUMMON_SECONDS = 8.0
SUMMON_SIZE = (2, 5)
TIDE_SECONDS = 4.0
TIDE_SIZE = 2
TIDE_MAX = 30

# Wolves hunt in packs. From WOLF_FIRST down, a floor has WOLF_CHANCE of one.
WOLF_FIRST = 3
WOLF_CHANCE = 0.2
WOLF_SIZE = (3, 6)

# Mushrooms never move. Get within GAS_TRIGGER tiles and one fills the open space around it,
# up to GAS_REACH tiles away in any direction. The edges clear first, and the last of it goes
# after GAS_SECONDS.
MUSHROOM_SHARE = 0.6       # of the mushrooms a floor would get, how many it really does
MUSHROOM_MOST = 8          # on any one floor
GAS_TRIGGER = 2
GAS_REACH = 4
GAS_SECONDS = 12.0
GAS_COOLDOWN = 20.0
GAS_DAMAGE = 2             # each second spent in it

# Ponds of healing. Stepping in heals you fully and wards you, which reflects magic, then the
# pond is spent. Armor with `reflect` wards whoever wears it.
POND_CHANCE = 0.12
REFLECT_SECONDS = 180.0

# The skeletal dragon sleeps on DRAGON_FLOOR. It breathes fire along a line at whoever it's
# hunting, every BREATH_SECONDS.
DRAGON_FLOOR = 80
BREATH_RANGE = 8
BREATH_SECONDS = 6.0
BREATH_DAMAGE = (8, 14)

# Plants block sight until someone walks through them, which tramples them for good.
PLANT_CHANCE = 0.6
PLANT_PATCHES = (1, 3)

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

# Cloaks. Each player brings one into the dungeon, somewhere in the CLOAK_FLOORS floors
# from where they joined.
CLOAK_FLOORS = 4

# Lava. From LAVA_FIRST down, most floors have pools of it. Falling into one costs LAVA_DAMAGE
# on top of the fall, which can kill, and leaves you on the nearest ground.
LAVA_FIRST = 51
LAVA_CHANCE = 0.85
LAVA_POOLS = (4, 8)
LAVA_DAMAGE = 25

# Cultists. From CULT_FIRST down, a floor has CULT_CHANCE of one group, leader included.
CULT_FIRST = 10
CULT_CHANCE = 0.2
CULT_SIZE = (6, 12)

# Arrows lie about in piles of this many. See items.py for the bow and boomerang.
ARROW_PILE = (20, 30)

# The wand of fire the leader drops. It aims at the nearest monster in sight, and each one
# burns for WAND_BURN_TURNS of its own turns.
WAND_CHARGES = 10
WAND_RANGE = 10
WAND_DAMAGE = (8, 14)
WAND_BURN = (2, 4)
WAND_BURN_TURNS = 3

# What an altar can give a weapon. See items.enhance_weapon.
ENHANCE_DAMAGE = (2, 4)
ENHANCE_ACCURACY = 15
ENHANCE_NOISE = 10
WEAPON_FREEZE_CHANCE = 0.2
WEAPON_FREEZE_SECONDS = 3.0
WEAPON_DRAIN = 4           # a draining weapon heals you for 1 in this many points of damage

# Using an altar has a price. Once you're GHOST_FLOORS floors from it, a ghost appears on
# whatever floor you're on, GHOST_DISTANCE tiles from you, and comes straight through the walls.
GHOST_FLOORS = 2
GHOST_DISTANCE = (10, 15)

# Weapons an altar has enhanced do this many times the damage to the undead.
UNDEAD_BONUS = 1.5

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
STEALTH_MOVE_DRAIN = 10    # lost per step
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

# Sneak attacks always hit, for SNEAK_DAMAGE times normal. One on a sleeping monster with
# at least CRIT_STEALTH stealth is a critical hit, for CRIT_DAMAGE times normal.
SNEAK_DAMAGE = 3
CRIT_DAMAGE = 10
CRIT_STEALTH = 40

# Difficulty, picked by the host. For each:
#   monster_time  how slow monsters are next to players (see MONSTER_TIME)
#   toughness     monsters' health multiplier, and what's added to their defense
#   regen         whether players heal over time on their own
#   revive        seconds a teammate stands by a fallen player to bring them back, or None:
#                 the fallen stay down until the next run
DIFFICULTIES = {
    "Easy":   dict(monster_time=2.0, toughness=(0.8, -5), regen=True, revive=3.0),
    "Medium": dict(monster_time=MONSTER_TIME, toughness=(1.0, 0), regen=False, revive=8.0),
    "Hard":   dict(monster_time=1.0, toughness=(1.3, 5), regen=False, revive=None),
}
DEFAULT_DIFFICULTY = "Medium"
REVIVE_SECONDS = DIFFICULTIES[DEFAULT_DIFFICULTY]["revive"]
REVIVE_HEALTH = 0.5        # share of full health a revived player comes back with
BONES_GLYPH = "%"

# Score = gold carried * kills * SCORE_SCALE / moves, doubled if the party won.
# So gold and kills raise it, and every move lowers it.
SCORE_SCALE = 100

# Boomerangs fly out and come back at this many seconds a tile, and can't be thrown again until they're back.
BOOMERANG_TILE_SECONDS = 0.06
BOOMERANG_WAIT = 1.0       # the least time before it can be thrown again, however close the target

# Selling to a merchant gets you this share of an item's price. What you sell is gone for good.
SELL_SHARE = 0.5

# The fisherman waits on one floor in this range, by water if there is any. He knows where keys are.
FISHER_FLOORS = (2, 6)

# Food barrels stand in quiet rooms: a door, a torch and nothing else. Walking into one gives you
# FOOD_HEAL health a second for FOOD_SECONDS.
FOOD_SECONDS = 8.0
FOOD_HEAL = 2
FOOD_ROOM_MOST = 80       # tiles; bigger than this isn't a room

# Fire from a wand of fire burns the ground around its target for FIRE_SECONDS, and grass until it's
# all burned away. Anything standing in it catches fire, and players in it take FIRE_DAMAGE a second.
FIRE_SECONDS = (2.0, 3.5)
GRASS_FIRE_SECONDS = (1.5, 3.0)
FIRE_SPREAD_SECONDS = 0.3  # how often fire jumps to the grass next to it
FIRE_SPREAD_CHANCE = 0.55
FIRE_DAMAGE = 2
FLEE_HEALTH = 0.5          # monsters on fire run below this share of their health

# Bombs. Merchants sell them, and they turn up now and then. One goes off BOMB_SECONDS after it's
# lit, hurting everything within BOMB_RADIUS and breaking cracked walls.
BOMB_SECONDS = 2.0
BOMB_RADIUS = 1
BOMB_DAMAGE = (15, 25)

# Hidden rooms lie behind a cracked wall on HIDDEN_ROOM_CHANCE of the floors with no locked door
# and no cult altar. A fairy in one raises everyone's health by FAIRY_BOOST of its maximum.
HIDDEN_ROOM_CHANCE = 0.33
FAIRY_BOOST = 0.2

# Every time an altar improves a weapon, its damage also goes up by this share.
ENHANCE_BOOST = 0.15

# Skeleton warriors gather in a group on every SKELETON_EVERY floors in this range, never more than
# SKELETON_MOST on one floor.
SKELETON_FLOORS = (50, 70)
SKELETON_EVERY = 3
SKELETON_GROUP = (3, 5)
SKELETON_MOST = 9

# The cultist mage lives a floor from a cult's altar. It floats for MAGE_FLOAT seconds of every
# MAGE_CYCLE, out of reach of melee, and casts lightning every MAGE_BOLT seconds.
MAGE_FLOAT = 6.0
MAGE_CYCLE = 10.0
MAGE_BOLT = 2.5
MAGE_RANGE = 8
LIGHTNING_DAMAGE = (6, 12)

# The cult leader fights with its wand of fire: it backs off to LEADER_RANGE, throws LEADER_VOLLEY
# bolts one after another, the last setting the ground alight around you, then rests LEADER_REST
# seconds before the next volley.
LEADER_RANGE = (3, 6)
LEADER_VOLLEY = 3
LEADER_REST = 2.0
LEADER_FIRE_DAMAGE = (4, 8)

# A giant spider queen nests in the big cave on SPIDER_CHANCE of floors SPIDER_FLOORS that have
# one, with SPIDER_BROOD smaller spiders, and webs over WEB_SHARE of the cave. Walking into a web
# slows you for SLOW_SECONDS. Run more than WEB_SPIT_RANGE tiles from her and she spits web at you
# every WEB_SPIT_SECONDS, out to WEB_SPIT_REACH, which slows you to WEB_FACTOR for WEB_SECONDS.
SPIDER_FLOORS = (8, 40)
SPIDER_CHANCE = 0.35
SPIDER_BROOD = (2, 3)
WEB_SHARE = 0.12
WEB_SPIT_RANGE = 5
WEB_SPIT_REACH = 10
WEB_SPIT_SECONDS = 4.0
WEB_FACTOR = 3             # a webbed step takes this many times as long
WEB_SECONDS = 3.0
# Smaller spiders leap from up to LEAP_RANGE tiles away to bite, every LEAP_SECONDS, then back
# off LEAP_RETREAT steps. A spider's bite adds VENOM_PER_BITE seconds of venom, up to VENOM_MOST,
# taking VENOM_DAMAGE every VENOM_EVERY seconds. Venom never takes you below 1 health.
LEAP_RANGE = 3
LEAP_SECONDS = 3.0
LEAP_RETREAT = 2
VENOM_PER_BITE = 10.0
VENOM_MOST = 40.0
VENOM_DAMAGE = 1
VENOM_EVERY = 2.0
STAFF_RANGE = 9

# Kobolds. A kobold next to a rat may turn on it. Leaders keep a tile away and reach in with a
# spear, on floors KOBOLD_LEADER_FLOORS. Scouts throw fire every SCOUT_RELOAD seconds.
KOBOLD_RAT_CHANCE = 0.03
KOBOLD_ALONE = 4           # with no other monster this close, a kobold runs
KOBOLD_ROCK_CHANCE = 0.05  # each turn below half health, for a thrown rock
KOBOLD_ROCK_RANGE = 6
ROCK_DAMAGE = (1, 3)
KOBOLD_LEADER_FLOORS = (5, 25)
KOBOLD_LEADER_CHANCE = 0.35  # of one leader on a floor; it has this chance again of a second
KOBOLD_SCOUT_FLOORS = (10, 15)
KOBOLD_SCOUT_CHANCE = 0.6
KOBOLD_SCOUT_MOST = 3
SCOUT_RELOAD = 5.0
SCOUT_RANGE = (4, 8)
FIREBALL_DAMAGE = (4, 8)

# Combat and monsters.
DEEPEST_TABLE = 26         # the monster and item lists end here; deeper floors reuse this one
REGEN_TURNS = 300          # turns for a player to regenerate from 0 to full
DEFENSE_FACTOR = 0.987     # hit% = accuracy * DEFENSE_FACTOR ** defense
NOTICE_RANGE_SLEEPING = 7
NOTICE_RANGE_AWAKE = 14

PROTOCOL_VERSION = 21
DEFAULT_PORT = 5555
