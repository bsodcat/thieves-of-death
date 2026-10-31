# Togetherogue

A starter for an online co-op roguelike in the spirit of Brogue, written in Python with
libtcod (python-tcod). One server holds the dungeon; each player runs a client.

What's in it so far:

- Brogue-style level generation: rooms, cross rooms, circular rooms and caves grown onto
  each other through doorways, with extra loops knocked through and stairs set into walls.
- Brogue's layout and rules: 79x29 map, sidebar, 3 message lines, doors that block sight
  unless someone is standing in them, no cutting diagonally around wall corners,
  sneak attacks (triple damage) on unaware monsters, and walking into stairs to use them.
- Per-player field of view and memory of explored tiles (per depth).
- Monsters that sleep, wander and hunt, with melee combat and HP regeneration.
- Real-time online co-op: nobody ever waits for anybody (see "How time works").
- Items: potions, weapons, armor and gold, a 10-slot pack, and dropping things for
  teammates. A run clock in the sidebar.
- Chat, joining mid-game, rejoining under the same name, and a fresh dungeon when the
  whole party dies.

## Playing

Double-click 'Togetherogue.exe'. It needs no Python or terminal, and friends only need
that one file. The main menu has:

- **Host Game**: starts a server inside the game and puts you in it. Leaving ends the game for
  everyone. The first time, Windows may ask to allow it through the firewall.
- **Join Game**: type the host's address and port.
- **Server Tool**: runs a server without playing, and shows the address to share, who's
  connected, their floor and ping, and a log.
- **Character**: your name, shape and color.
- **Options**: the font, and whether to show the holiday themes.

Use the arrow keys and Enter, or the mouse. Your choices are saved in
'%APPDATA%\Togetherogue\settings.json'. In the game, press 'Q' twice to leave.

The version and release date are at the bottom of the title screen, and come from
'game/version.py'. A server refuses players whose copy doesn't match it, and tells them why.

### Building the exe

Python 3.10 or newer, then double-click 'build.bat'. The result is 'dist\Togetherogue.exe'.

### Running from a terminal

'''
pip install -r requirements.txt
'''

'python togetherogue.py' opens the same menu. To skip it, start the server on one machine:

'''
python server.py
'''

Then each player runs a client:

'''
python client.py --name Alice                     # same machine as the server
python client.py --name Bob --host 192.168.1.20   # another machine on your network
'''

To play over the internet, the host forwards TCP port 5555 on their router, or everyone
joins a virtual LAN like Tailscale or ZeroTier and uses the host's address on it.

No friends online? 'python bot.py' adds a simple bot that follows you around.

Useful options: 'server.py --port 6000 --seed 42',
'client.py --font myfont.ttf --tile 12x24' (a .ttf, a Windows .fon bitmap font, or a 16x16
CP437 tilesheet .png).

On Windows the client uses the classic Terminal font ('8514oem.fon', 10x20), read from
'C:\Windows\Fonts'. For other sizes try '--font C:/Windows/Fonts/vgaoem.fon' (8x12) or
'--font C:/Windows/Fonts/dosapp.fon --tile 12x16'. Other systems use a TrueType font.

### Controls

| Key | Action |
| --- | --- |
| Arrows, numpad, or 'h j k l y u b n' | Move or attack (8 directions). Hold to keep going; two arrows move diagonally |
| Walk into '>' / '<', or press '>' / '<' next to them | Take the stairs |
| '1'-'9', '0' | Use the item in that pack slot: drink a potion, or equip or remove gear |
| 'i' | Show or hide the pack |
| 't' | Show or hide your tally |
| 'd', then a number | Drop one item from that slot |
| 'd', then '$' | Drop 25 gold |
| 'g' | Pick up what you're standing on |
| '?' or F1 | Show or hide the controls |
| Mouse | Point at the map to identify what's there |
| Hold Shift | Sprint, using stamina |
| Hold right click | Walk toward the pointer, around walls. On a monster, chase and attack it. On stairs, take them |
| Esc | Close a panel or cancel a drop |
| Enter | Chat (Enter sends, Esc cancels) |
| 'Q' or close the window | Quit |

## How time works

The game runs in real time, on one clock shared by everyone:

- Moving or attacking costs a cooldown of 0.16 seconds ('TURN_SECONDS'). Press a key and the
  action happens at once. Press again during the cooldown and it's queued for when the
  cooldown ends, with the newest press replacing any older one.
- Nobody waits for anybody. Your actions depend only on your own cooldown.
- Monsters act on their own clock whether or not anyone is pressing keys, at 1.5 times the
  player's action time ('MONSTER_TIME'), so you can get away from most of them. Jackals
  are still faster than you.
- Monsters only run on levels with a living player. Other levels stay frozen until
  someone arrives.
- Health returns over time, a full bar in about 48 seconds, so there's no rest key.

All of these numbers are in 'game/constants.py'.

## Game modes

Choose one under Host Game or Server Tool.

- **Classic**: a fallen player is out until the next run, and their gear lands around them
  for the party to collect.
- **Revive**: a fallen player stays on the map as bones ('%'), keeps their gear, and can watch
  what's nearby. Stand next to the bones for 3 seconds to bring them back at half health. If you
  move out of reach, the progress resets. Monsters ignore bones. If everyone goes down, the run
  restarts.

## Your character

The Character screen on the main menu sets your name, shape and color, with a preview.
Others see the shape and color you pick, in the dungeon and in the Players list.

## Score and tally

Your score is your Moves plus 10 points for each piece of gold you're carrying, shown in the
sidebar as you play. Moves counts every action, including attacks and using items. The score uses
the gold you carry when you fall, so gold you drop no longer counts, and in Classic the gold that
scatters from you still does.

Press 't' for your tally: score, kills by monster, and the hardest enemy you've fought, ranked by
health times damage per turn. Any monster that's hit or been hit by you counts, even if nobody won.
The same numbers appear when you fall, and when the whole party falls everyone sees a ranked
scoreboard. Scores aren't kept between runs. Change the weights with 'SCORE_PER_MOVE' and
'SCORE_PER_GOLD' in 'game/constants.py'.

## Look

The bottom left of the sidebar is the Look panel. Point the mouse at the map and that tile is
highlighted and described: monsters with their health, what they're doing and how hard they
hit, players, bones, items and terrain. It only tells you what your character knows, so
unexplored tiles stay unknown and remembered items are marked as remembered. Add
descriptions in 'MONSTERS' in 'game/entities.py' and 'DESCRIPTIONS' in 'game/tiles.py'.

## Holidays

From October 24 to 31 and December 18 to 26, monsters and items can get Halloween or Christmas
names, descriptions and colors, and the title screen says so. **Holiday themes** in Options is
On by default; turn it Off to hide them. In a game, the host's setting applies to everyone. It's
purely cosmetic: every stat stays the same. The date comes from the clock of the computer running the server, so everyone in a
game sees the same thing, and it's checked at the start of each run so nothing changes partway
through. Change the dates and names in 'game/seasons.py'. To preview one, use
'python server.py --season christmas'.

## Players list

The sidebar lists everyone connected, including you, with the floor they're on and their
ping. Ping is the round trip to the server in milliseconds, measured once a second and
smoothed. It shows '--' until the first measurement. The green bar behind each name is
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

## Terrain

Some floors have lakes or a river running through them, across rock as well as rooms. You can wade
through shallow water (`~`), but deep water can't be crossed on foot, and monsters stay out of it
too. Where water cuts a floor in two it leaves a shallow ford, so the stairs up and down and every
part of the floor can always be reached on foot.

Walking into a pit drops you to the floor below, close to the same spot, for 3 to 6 damage. A fall
can't kill you. Auto-walk goes around pits, but holding a direction doesn't.

A potion of levitation carries you over water and pits, though not through walls. If it runs out
over water you scramble to the nearest shore, and if it runs out over a pit you fall. The chances
are in `game/constants.py`.

## Locked rooms

Each of floors 4 to 14 has a 15% chance of a locked room, in red, blue, green or yellow. Its key is
the same color and lies exactly 2 floors above or below, so you may have to come back for it. Press
`g` to pick up a key, then walk into the door. Anyone in the party can use it, and it's used up.
Inside are two pieces of gear from deeper down, a potion and a big pile of gold.

## Merchants

Every 5th floor has a 60% chance of a merchant ('$'), and you'll hear them when you arrive. Walk
into them to see their stock, and press a number to buy. They sell 3 to 5 weapons and armor suited
to the floor, and there's one of each, shared by the whole party. walking away closes the shop.
Spending gold lowers your score, since the score counts what you're carrying. He can't be walked through.

The potion of levitation is rare on the floor, and 30% of merchants have one for 600 gold. For 9
seconds you float: ground monsters can't reach you and moving doesn't use up your stealth, though
you can still attack. Prices are in 'game/items.py', the odds in 'game/constants.py'.

## Stealth

The blue bar under your health is your stealth. It fills from empty to full in 3 seconds
while you stand still. Each step costs 20%, and attacking empties it. Walking slowly with
pauses between steps can keep it up; holding a direction empties it in about a second.

A full bar shrinks the range at which monsters notice you to 30% of normal: awake monsters
from 14 tiles to about 4, and sleeping ones from 7 to about 2. Monsters already hunting you
aren't fooled while they can see you. The numbers are in 'game/constants.py'.

Equipped gear makes noise, this lowers how high the bar can go. Each point of noise takes
1% off the top, so a mace (20) and plate armor (40) stop you at 40%, and even standing still
monsters then notice you from about 10 tiles. Only equiptped gear counts, so carrying heavy gear
in your pack is free. The red part of the bar is what's out of reach in your current gear,
and the sidebar shows how far away you can be noticed right now.

## Items

Walking over a potion or gold picks it up. Weapons and armor stay on the floor until you
stand on them and press 'g'. Anyone can collect what another player drops. Something you've
just dropped stays there until you step off and back on, or press 'g'. When a player dies,
everything they carried lands around them for the party to collect.

The pack has 10 slots, one per number key, so you can drink or change gear in the middle
of a fight. Potions of the same kind share a slot, and gold doesn't take up a slot. The game
doesn't pause while the pack is open; the panel opens on the far side of the map from you.

| Item | Glyph | Effect | Noise |
| --- | --- | --- | --- |
| Potion of healing | '!' | Heals 20 | |
| Potion of greater healing | '!' | Heals 40 | |
| Potion of haste | '!' | Double speed for 10 seconds | |
| Potion of levitation | '!' | Float for 9 seconds, out of reach of ground monsters | |
| Dagger | ')' | 3-5 damage | 5 |
| Sword | ')' | 5-9 damage | 15 |
| Mace | ')' | 12-18 damage, attacks take twice as long | 20 |
| Leather armor | '[' | +15 armor | 10 |
| Scale armor | '[' | +35 armor | 25 |
| Plate armor | '[' | +60 armor, moves take 25% longer | 40 |
| Gold | '*' | Goes to your purse, not a pack slot | |

Add or change items in 'game/items.py'. Stronger items appear deeper down.

## Versions

Versions are MAJOR.MINOR.PATCH, and each one is listed in 'CHANGELOG.md'.

| Raise | When | Example |
|  ---  | --- | --- |
| PATCH | A fix that adds nothing new | 1.0.0 to 1.0.1 |
| MINOR | A new feature that keeps the game working as before | 1.0.0 to 1.1.0 |
| MAJOR | A big change to how the game plays, or old saves or settings stop working | 1.0.0 to 2.0.0 |

Reset the numbers to the right when one goes up. Separately, raise 'PROTOCOL_VERSION' in
'game/constants.py' whenever older copies can no longer play with newer ones; that's what the
server checks when someone joins.

To release: update 'game/version.py' and 'CHANGELOG.md', run the tests, commit, tag it
('git tag -a v1.1.0 -m "Togetherogue 1.1.0"'), then run 'build.bat'. To get an old version back,
use 'git checkout v0.1.0'.

## Project layout

'''
server.py          asyncio TCP server and game clock: one JSON message per line
togetherogue.py    the app: main menu, setup screens and Server Tool
client.py          tcod window, input, and a network thread
bot.py             headless test player bot
game/world.py      game state, real-time clock, combat, monster AI   <- most of the game
game/mapgen.py     level generator
game/entities.py   players and the monster list (add more monsters here)
game/items.py      the item list (add itens here)
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
'''

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
