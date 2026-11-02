# Togetherogue

A starter for an online co-op roguelike in the spirit of Brogue, written in Python with
libtcod (python-tcod). One server holds the dungeon; each player runs a client.

The goal: go down to floor 99, take the Amulet from the necromancer's room, and carry it back up
and out through the stairs on floor 1.

What's in it so far:

- Brogue-style level generation: rooms, cross rooms, circular rooms and caves grown onto
  each other through doorways, with extra loops knocked through and stairs set into walls.
- Brogue's layout and rules: 79x29 map, sidebar, 3 message lines, doors that block sight
  unless someone is standing in them, no cutting diagonally around wall corners,
  sneak attacks on unaware monsters, and walking into stairs to use them.
- Per-player field of view and memory of explored tiles (per depth).
- Monsters that sleep, wander and hunt, with melee combat and HP regeneration.
- Real-time online co-op: nobody ever waits for anybody (see "How time works").
- Items: potions, weapons, armor and gold, a 10-slot pack, and dropping things for
  teammates. A run clock in the sidebar.
- Chat, joining mid-game, rejoining under the same name, and a fresh dungeon when the
  whole party dies.

## Playing

Double-click `Togetherogue.exe`. It needs no Python or terminal, and friends only need
that one file. The main menu has:

- **Host Game**: starts a server inside the game and puts you in it. Leaving ends the game for
  everyone. The first time, Windows may ask to allow it through the firewall.
- **Join Game**: type the host's address and port.
- **Server Tool**: runs a server without playing, and shows the address to share, who's
  connected, their floor and ping, and a log.
- **Character**: your name, shape and color.
- **Options**: the font, whether to show the holiday themes, and what ranged weapons aim at.

Use the arrow keys and Enter, or the mouse. Your choices are saved in
`%APPDATA%\Togetherogue\settings.json`. In the game, press `Q` twice to leave.

The version and release date are at the bottom of the title screen, and come from
`game/version.py`. A server refuses players whose copy doesn't match it, and tells them why.

### Building the exe

Python 3.10 or newer, then double-click `build.bat`. The result is `dist\Togetherogue.exe`.

### Running from a terminal

```
pip install -r requirements.txt
```

`python togetherogue.py` opens the same menu. To skip it, start the server on one machine:

```
python server.py
```

Then each player runs a client:

```
python client.py --name Alice                     # same machine as the server
python client.py --name Bob --host 192.168.1.20   # another machine on your network
```

To play over the internet, the host forwards TCP port 5555 on their router, or everyone
joins a virtual LAN like Tailscale or ZeroTier and uses the host's address on it.

No friends online? `python bot.py` adds a simple bot that follows you around.

Useful options: `server.py --port 6000 --seed 42`,
`client.py --font myfont.ttf --tile 12x24` (a .ttf, a Windows .fon bitmap font, or a 16x16
CP437 tilesheet .png).

On Windows the client uses the classic Terminal font (`8514oem.fon`, 10x20), read from
`C:\Windows\Fonts`. For other sizes try `--font C:/Windows/Fonts/vgaoem.fon` (8x12) or
`--font C:/Windows/Fonts/dosapp.fon --tile 12x16`. Other systems use a TrueType font.

### Controls

| Key | Action |
| --- | --- |
| `W A S D`, arrows, numpad, or `h j k l y u b n` | Move or attack (8 directions). Hold to keep going; two keys together move diagonally |
| Walk into `>` / `<`, or press `>` / `<` next to them | Take the stairs |
| `1`-`9`, `0` | Use the item in that pack slot: drink a potion, or equip or remove gear |
| `q` | Quick heal: drink the smallest healing potion that fills you up, or your biggest if none will |
| `i` | Show or hide the pack. While it's open, click an item to use it, or press `o` to sort |
| `t` | Show or hide your tally |
| `x`, then a number or a click | Drop one item from that slot |
| `x`, then `$` | Drop 25 gold |
| `g` | Pick up what you're standing on |
| `?` or F1 | Show or hide the controls |
| Mouse | Point at the map to identify what's there |
| Hold Shift | Sprint, using stamina |
| Hold right click | Walk toward the pointer, around walls. On a monster, chase and attack it. On stairs, take them |
| Esc | Close a panel or cancel a drop |
| Enter | Chat (Enter sends, Esc cancels) |
| `v` | Show or hide the action log |
| `Q` or close the window | Quit |

Change any of these in Options, under Controls: choose one and press its new key. Each key can only
do one thing, and giving `h j k l y u b n` another job takes it off movement. Numbers, Enter, Esc,
`` ` ``, F1 and F2 can't be changed. The arrows and numpad always move you, unless you bind them.

Walk into a teammate to go straight past them, which leaves them where they are. If there's nowhere
to land on the far side you trade places instead, so nobody can block a corridor.

## How time works

The game runs in real time, on one clock shared by everyone:

- Moving or attacking costs a cooldown of 0.16 seconds (`TURN_SECONDS`). Press a key and the
  action happens at once. Press again during the cooldown and it's queued for when the
  cooldown ends, with the newest press replacing any older one.
- Nobody waits for anybody. Your actions depend only on your own cooldown.
- Monsters act on their own clock whether or not anyone is pressing keys, at 1.5 times the
  player's action time (`MONSTER_TIME`), so you can get away from most of them. Jackals
  are still faster than you.
- Monsters only run on levels with a living player. Other levels stay frozen until
  someone arrives.
- Health returns over time, a full bar in about 48 seconds, so there's no rest key.

All of these numbers are in `game/constants.py`.

## Game modes

Choose one under Host Game or Server Tool.

- **Classic**: a fallen player is out until the next run, and their gear lands around them
  for the party to collect.
- **Revive**: a fallen player stays on the map as bones (`%`), keeps their gear, and can watch
  what's nearby. Stand next to the bones for 3 seconds to bring them back at half health. If you
  move out of reach, the progress resets. Monsters ignore bones. If everyone goes down, the run
  restarts.

## Your character

The Character screen on the main menu sets your name, shape and color, with a preview.
Others see the shape and color you pick, in the dungeon and in the Players list.

## The buried tower

Floor 89 has no monsters: a long pillared hall opens into a round atrium with green walls, and the
stairs at the far side lead into the tower. Floors 90 to 99 are the tower itself, buried in the rock.
Its walls glow green, and every floor is a mirror image, with a shaft and central hall and rooms
down each side. The tower has its own monsters: mostly skeleton warriors, with zombies, cultists and wolves, and no
ogres or mushrooms. The last
floor is a great round room with pillars and smaller rooms off it, and nothing lives there but the
necromancer. One side room holds a hoard of gold, and another a store of potions.

## The goal

Floor 99 is the last floor, and has no stairs down. The necromancer sleeps in the middle of the great
round room, with the Amulet (`§`) lying across it, well away from the ways in. Press `g` to pick it up, then carry it to the
upward stairs on floor 1. When anyone in the party walks out with it, the whole party wins. Without
it, that staircase stays sealed. If whoever has it leaves the game, it drops to the floor.

You can do it two ways:

- **Fight**: the necromancer has 200 health, and raises 2 to 5 zombies every 8 seconds while it can
  see you. Kill it and the zombies stop coming for good.
- **Sneak**: the Amulet is 7 to 9 tiles from it, so with some stealth, and ideally a cloak, you can
  take it and leave without waking it. A wand of frost holds it still too, without waking it.

If you leave floor 99 while it's awake, you're chased. Every floor you climb to, 2 more zombies
appear out of sight of you every 4 seconds, for as long as you stay there, up to 30 at a time. It only
ends if the necromancer dies.

## Score and tally

Gold scores and moves divide it. Your score is 10 points for each piece of gold you're carrying,
plus 10000 if the party wins, divided by a share of your moves: score = points x 500 / (moves + 500).
So 500 moves halves it, and 1500 leaves a quarter. It's shown in the sidebar as you play. Moves
counts every action, including attacks and using items. The score uses
the gold you carry when you fall, so gold you drop no longer counts, and in Classic the gold that
scatters from you still does.

Press `t` for your tally: score, kills by monster, and the hardest enemy you've fought, ranked by
health times damage per turn. Any monster that's hit or been hit by you counts, even if nobody won.
The same numbers appear when you fall, and when the whole party falls everyone sees a ranked
scoreboard. Scores aren't kept between runs. Change the numbers with `SCORE_STEPS`,
`SCORE_PER_GOLD` and `WIN_POINTS` in `game/constants.py`.

## Action log

Press `v` in a game to read what's happened this run, including after you die. Up, down and the
mouse wheel scroll it, and `v` or Esc closes it. The game keeps running behind it.

The same lines are saved as you play, one text file for each run, in
`%APPDATA%\Togetherogue\logs`. The panel shows the file's name. Everyone playing gets their
own file, from the moment they joined, and only the newest 200 are kept. A server run on its own
with `server.py` saves one too.

```
0:04:12.3 F03 Bob hit goblin#41 -5 hp 10/15
0:04:12.9 F03 goblin#41 missed Bob (62% to hit)
0:04:13.8 F03 Bob drank potion of healing hp 40/40
0:05:02.1 F03 Bob stairs F03->F04 hp 40/40
```

Each line is the time since the run began, the floor, who, and what happened. `10/15` is health
left of the most, `-5` is damage, and `goblin#41` is one particular goblin. Lines are marked
`DIED`, `DOWN`, `WON` or `RUN OVER` at the end of things, `CONSOLE` for a test command, and `ERROR`
for a bug in the game itself. To chase a bug, the file's first line has the version and seed, and
`--seed` or the Seed option rebuilds the same floors.

To log something new, call `World.note` where it happens.

## Look

The bottom left of the sidebar is the Look panel. Point the mouse at the map and that tile is
highlighted and described: monsters with their health, what they're doing and how hard they
hit, players, bones, items and terrain. It only tells you what your character knows, so
unexplored tiles stay unknown and remembered items are marked as remembered. Add
descriptions in `MONSTERS` in `game/entities.py` and `DESCRIPTIONS` in `game/tiles.py`.

## Holidays

From October 24 to 31 and December 18 to 26, monsters and items can get Halloween or Christmas
names, descriptions and colors, and the title screen says so. **Holiday themes** in Options is
On by default; turn it Off to hide them. In a game, the host's setting applies to everyone. It's
purely cosmetic: every stat stays the same. The date comes from the clock of the computer running
the server, so everyone in a game sees the same thing, and it's checked at the start of each run so nothing changes partway
through. Change the dates and names in `game/seasons.py`. To preview one, use
`python server.py --season christmas`.

## Players list

The sidebar lists everyone connected, including you, with the floor they're on and their
ping. Ping is the round trip to the server in milliseconds, measured once a second and
smoothed. It shows `--` until the first measurement. The green bar behind each name is
that player's health.

## Stamina

The yellow bar under stealth. Hold Shift to sprint: each step takes 60% of the time and costs 5
stamina, and uses up stealth twice as fast. Each attack costs 8. Below that your attacks take twice
as long, and with under 5 you can't sprint. It starts refilling 0.75 seconds after you last spent
any, and fills from empty in 6 seconds. The numbers are in `game/constants.py`.

## Torches

Each floor has 1 to 3 torches on its walls, far apart and away from the stairs. Their light flickers
and stops at walls and doors. Standing in it makes you easier to notice: up to 75% further away right
beside a torch, fading to nothing 9 tiles out. The sidebar's Detection line turns orange and says
Torchlit while you're in it.

## Test console

Press `` ` `` or F2 in a game to open the console, type a command and press Enter. Up and down
recall what you've typed, the mouse wheel scrolls back through what it's printed, and Esc closes
it. The game keeps running behind it.

| Command | Does |
| --- | --- |
| `help`, `list` | List the commands, or the item and monster names |
| `info` | Seed, floor, locked rooms and where cloaks are waiting |
| `give <item> [count]` | Put an item in your pack, such as `give wand` or `give tele 3` |
| `gold <amount>` | Add gold, which raises your score |
| `heal` | Fill your health and stamina |
| `god` | Take no damage, until you turn it off |
| `collision [on\|off]` | With it off, walk through walls, enemies, allies, water, pits, lava and locked doors |
| `floor <number> [player]` | Move yourself, or another player, to any floor, such as `floor 51` for lava |
| `goto <floor>` | The same as `floor`, for yourself only |
| `spawn <monster> [count]` | Add monsters beside you. `spawn cult` adds a whole cult |
| `killall` | Kill every monster on this floor |
| `reveal` | Toggle: every floor is mapped as you reach it, and all monsters and items are marked, including any that appear later |
| `ultrabright` | Toggle: every floor is drawn fully lit, without showing what's out of sight |
| `stealth <0-100>` | Set your stealth |
| `teleport` | Jump to another part of this floor |
| `clear` | Empty the console |

Names can be cut short as long as they still match only one thing. Only someone playing on the
computer running the server can use commands, and everyone else in the game is told when one
runs. Add your own in `game/commands.py`.

## Terrain

Some floors have lakes or a river running through them, across rock as well as rooms. You can wade
through shallow water (`~`), but deep water can't be crossed on foot, and monsters stay out of it
too. Water can cut off whole rooms, and only a potion of water walking or levitation gets you to
them, though anything can be lying there. The stairs up and down are always linked on foot, by a
shallow ford if need be, and so are locked doors, keys, cloaks and merchants.

Nothing puts you on an island unless you choose to go. Falls, teleports and revivals all end on the
main part of the floor. If a potion runs out while you're on one, you can swim back: walk into the
water, at half speed. You can only swim away from an island, not out to one.

Walking into a pit drops you to the floor below, close to the same spot, for 3 to 6 damage. A fall
can't kill you. Auto-walk goes around pits, but holding a direction doesn't.

A potion of levitation carries you over water and pits, though not through walls. If it runs out
over water you scramble to the nearest shore, and if it runs out over a pit you fall. The chances
are in `game/constants.py`.

From floor 51 down, most floors have pools of lava. Nothing can walk through it without a potion of
lava walking or levitation, and walking into it is refused, but a pit gives no warning: you come
down as close as possible to where you fell, and that can be lava. It costs 25 health on top of the
fall and can kill you. If you live, you end up on the nearest ground.

## Monsters

- **Skeletal dragon** (`D`): sleeps on floor 80, as far from the stairs as it can. Every 6 seconds it
  breathes fire in a line at whoever it's hunting, from up to 8 tiles, for 8 to 14 damage.

- **Wolves** (`w`): from floor 3 down, a floor has a 20% chance of a pack of 3 to 6. They're twice as
  fast as you, and when one notices you they all do.
- **Mushrooms** (`f`): floors 3 to 50, and never more than 8 on a floor. They never move and don't attack. Get within 2 tiles and one fills the space
  around it with toxic gas, up to 4 tiles away in any direction, however stealthy you are. Walls and
  doors stop it. It thins from the edges inward and is gone
  in 12 seconds. Gas does 2 damage a second, and the mushroom can do it again after 20 seconds. Kill
  it from a distance, or go around.
- **Ogres** (`O`): from floor 7 to floor 65, and most common on floors 45 to 55.
- **Skeleton archers** (`s`): floors 70 to 90. They move slowly, and try to stay 6 to 11 tiles from you, backing away if
  you close in and following if you run, and shoot every 2.5 seconds for 3 to 7 damage.
- **Skeleton warriors** (`S`): the main enemy from floor 80 down through the tower to floor 98.
- **Slimes** (`b`): 4 or 5 on every floor from 25 to 85. They're slow and only hit for 1 or 2, but their
  touch poisons you for 1 damage a second for 6 seconds, with no healing meanwhile, and halves your
  speed for 3 seconds, and so
  does walking on the green trail they leave, which lasts 15 seconds. Levitating avoids the trail.
- **Ghosts** (`G`): only appear after you've used an altar. See Altars.
- **Zombies** (`z`): slow, and only raised by the necromancer.

## Ponds of healing

About 1 floor in 8 has a small bright teal pond. Step in to heal fully and be warded for 3 minutes:
a blue glow surrounds you, and magic aimed at you goes straight back at whoever cast it. The pond is then spent.
Magic armor has the same ward for as long as you wear it, with a smaller, slower glow. So far the dragon's fire is the only magic
aimed at players.

A monster about to hit you in melee warns you first: it blinks, faster and faster as the blow gets
close. When a player strikes a monster, a red glow flares around it and fades. Most monsters give you about half a second, and slow hitters like ogres nearly a
second, so you can step away. Monsters attack half as often as they did before 2.4.1: change
`MONSTER_SWING` in `game/constants.py` to adjust it.

## Plants

Some floors have patches of tall grass (`"`) and thicker foliage (`τ`). You can walk through them, but
you can't see through them. Whatever walks through tramples them for good, for everyone.

## Altars

Every group of cultists stands around an altar (`∩`) with a glowing purple aura. Walk into it holding
a weapon and it asks whether you'd like to enhance your weapon. Say yes and that weapon improves for
good, in one random way: more damage, better aim, faster attacks, less noise, or a spell that burns,
sometimes freezes, or heals you as you hit. Each altar works once, then goes cold. The improvement
stays with the weapon, whoever carries it, until the run ends, and a weapon can take several.

Any enhanced weapon also does 1.5 times the damage to the undead: zombies, skeletons, the skeletal
dragon, ghosts and the necromancer. But altars have a price. Once you're 2 floors from one you've
used, a ghost appears on your floor, 10 to 15 tiles away and out of sight. It's the only thing
that goes through walls, and it always knows where you are. You get one ghost for each altar.

## Cultists

From floor 10 down, a floor has a 20% chance of a group of 6 to 12 cultists, one of them their
leader (`C`). When one notices you they all do. Kill the leader and it drops a wand of fire, which
anyone can pick up with `g`. Use it like any pack item: it burns the nearest monster in sight within
10 tiles for 8 to 14 damage and sets it alight for 3 of its turns. The wand breaks after 10 uses,
and if there's nothing to aim at, a use isn't spent.

## Locked rooms

Each of floors 4 to 14 has a 15% chance of a locked room, in red, blue, green or yellow. Its key is
the same color and lies exactly 2 floors above or below, so you may have to come back for it. Walk over a
key to pick it up, then walk into the door. Anyone in the party can use it, and it's used up.
Inside are two pieces of gear from deeper down, a potion and a big pile of gold.

## Merchants

Every 5th floor has a 60% chance of a merchant (`$`), and you'll hear them when you arrive. Walk
into them to see their stock, and press a number to buy. They sell 3 to 5 weapons and armor suited
to the floor, and there's one of each, shared by the whole party. Walking away closes the shop.
Spending gold lowers your score, since it counts what you're carrying. You can't walk through a merchant.

The potion of levitation is rare on the floor, and 30% of merchants have one for 600 gold. For 9
seconds you float: ground monsters can't reach you and moving doesn't use up your stealth, though
you can still attack. Prices are in `game/items.py`, the odds in `game/constants.py`.

## Stealth

The blue bar under your health is your stealth. It fills from empty to full in 3 seconds
while you stand still. Each step costs 10%, and attacking empties it. Walking slowly with
pauses between steps can keep it up; holding a direction empties it in about 3.5 seconds.

A full bar shrinks the range at which monsters notice you to 30% of normal: awake monsters
from 14 tiles to about 4, and sleeping ones from 7 to about 2. Monsters already hunting you
aren't fooled while they can see you. The numbers are in `game/constants.py`.

Equipped gear makes noise, which lowers how high the bar can go. Each point of noise takes
1% off the top, so a mace (20) and plate armor (40) stop you at 40%, and even standing still
monsters then notice you from about 10 tiles. Only equipped gear counts, so carrying heavy gear
in your pack is free. The red part of the bar is what's out of reach in your current gear,
and the sidebar shows how far away you can be noticed right now.

A cloak helps too: see Items.

Attacking a monster that hasn't noticed you always hits, for triple damage. Attack a sleeping
monster with at least 30% stealth and it's a critical hit, for five times normal damage. Stealth
empties as you attack, so wait a moment beside a sleeper first.

## Items

Walking over a potion, a key or gold picks it up. Weapons and armor stay on the floor until you
stand on them and press `g`. Anyone can collect what another player drops. Something you've
just dropped stays there until you step off and back on, or press `g`. When a player dies,
everything they carried lands around them for the party to collect.

The pack has 10 slots, one per number key, so you can drink or change gear in the middle
of a fight. Potions of the same kind share a slot, and gold doesn't take up a slot. The game
doesn't pause while the pack is open; the panel opens on the far side of the map from you.

| Item | Glyph | Effect | Noise |
| --- | --- | --- | --- |
| Potion of healing | `!` | Heals 20 | |
| Potion of greater healing | `!` | Heals 40 | |
| Potion of haste | `!` | Double speed for 10 seconds | |
| Potion of levitation | `!` | Float for 9 seconds, out of reach of ground monsters | |
| Potion of teleportation | `!` | Jump to a random spot on a random floor, anywhere from 1 to 99. A real gamble | |
| Potion of water walking | `!` | Walk on deep water for 1 minute, in a blue glow reaching 5 tiles that fades away as it runs out. Floors 18 to 42 | |
| Potion of lava walking | `!` | Walk on lava for 1 minute, in an orange glow reaching 5 tiles that fades away as it runs out. Floors 18 to 42 | |
| Dagger | `)` | 3-5 damage | 5 |
| Sword | `)` | 5-9 damage | 15 |
| Mace | `)` | 12-18 damage, attacks take twice as long | 20 |
| Leather armor | `[` | +15 armor | 10 |
| Scale armor | `[` | +35 armor | 25 |
| Plate armor | `[` | +60 armor, moves take 25% longer | 40 |
| Magic armor | `[` | +40 armor, and wards you against magic while worn. Floors 60 to 70 only | 10 |
| Cloak | `¶` | Monsters notice you from half as far. Worn alongside weapon and armor | -45 |
| Bow | `}` | Fires an arrow at a monster up to 12 tiles away, for 4 to 8 damage | |
| Arrows | `\|` | Found in piles of 20 to 30, and picked up by walking over them | |
| Boomerang | `}` | Thrown spinning at a monster up to 9 tiles away, for 3 to 6 damage. It comes back, so it's never used up | |
| Wand of frost | `/` | Freezes the nearest monster in sight for 30 seconds, without waking it. Rare. Breaks after 10 uses | |
| Wand of fire | `/` | Burns the nearest monster in sight within 10 tiles. Breaks after 10 uses | |
| Gold | `*` | Goes to your purse, not a pack slot | |

Add or change items in `game/items.py`. Stronger items appear deeper down.

There's exactly one cloak per player in each run, and merchants don't sell them. Each lies on a
random floor among the 4 starting from the one its player joined on, so a late arrival adds one
near the party. Anyone can pick one up, and it takes one slot like any other gear.

Use a bow or boomerang from the pack, like a wand. Ranged weapons and wands aim for you: at monsters
already fighting first, then the strongest of them, or the weakest if you change **Ranged weapons aim
at** in Options. A change takes effect the next time you join a game.

## Versions

Versions are MAJOR.MINOR.PATCH, and each one is listed in `CHANGELOG.md`.

| Raise | When | Example |
| --- | --- | --- |
| PATCH | A fix that adds nothing new | 1.0.0 to 1.0.1 |
| MINOR | A new feature that keeps the game working as before | 1.0.0 to 1.1.0 |
| MAJOR | A big change to how the game plays, or old saves or settings stop working | 1.0.0 to 2.0.0 |

Reset the numbers to the right when one goes up. Separately, raise `PROTOCOL_VERSION` in
`game/constants.py` whenever older copies can no longer play with newer ones; that's what the
server checks when someone joins.

To release: update `game/version.py` and `CHANGELOG.md`, run the tests, commit, tag it
(`git tag -a v1.1.0 -m "Togetherogue 1.1.0"`), then run `build.bat`. To get an old version back,
use `git checkout v0.1.0`.

## Project layout

```
server.py          asyncio TCP server and game clock: one JSON message per line
togetherogue.py    the app: main menu, setup screens and Server Tool
client.py          tcod window, input, and a network thread
bot.py             headless test player bot
game/world.py      game state, real-time clock, combat, monster AI   <- most of the game
game/mapgen.py     level generator
game/commands.py   the test console's commands
game/controls.py   the keys a player can change
game/ledger.py     saves the action log to a text file
game/entities.py   players and the monster list (add more monsters here)
game/items.py      the item list (add items here)
game/seasons.py    holiday names, descriptions, colors and dates
game/render.py     everything the client draws, without tcod
game/algo.py       field of view and pathfinding (tcod, or pure-Python fallback)
game/fon.py        reader for Windows .fon bitmap fonts
game/pathing.py    route finding for auto-walking
game/menu.py       menu forms, without tcod
game/settings.py   saved settings
game/protocol.py   message format
game/tiles.py      tile types, glyphs and colors
tests/             python -m pytest
```

The server is authoritative: clients only send key presses, and each client only receives
what its player can see.

## Good next steps

1. More items: scrolls, rings and staffs. Brogue's strength system and enchant scrolls fit
   in from there, and gold needs something to spend it on.
2. Brogue's lighting and colors: light sources, darkness, and stealth.
3. Monster abilities (ranged attacks, spellcasters, splitting jellies, thieves).
4. Mouse support with click-to-travel and auto-explore. These should stop as soon as
   anything new comes into view.
5. Saving the world when the server shuts down.

## A note on Brogue's code

Brogue CE's source code is licensed under the AGPL. This project is written from scratch
and only borrows ideas. If you copy code or data tables from Brogue CE, your project will
need to be AGPL too.
