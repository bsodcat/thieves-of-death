# Changelog

Versions are MAJOR.MINOR.PATCH. See "Versions" in the README for what each number means.

## 2.13.1 - November 9, 2026

2.12 and 2.13 players can play together.

### Changed

- The game is now called Thieves of Death: The Fellowship. The exe is `thieves-of-death.exe`, and
  settings and logs move from `%APPDATA%\Togetherogue` to `%APPDATA%\Thieves of Death` on first run.

## 2.13.0 - November 8, 2026

2.12 and 2.13 players can play together.

### Added

- Test console: `enable rover [count]` adds rovers, smarter bot teammates that share the 5-bot
  cap. They roam near you, pick up and wear better gear, go after the monsters they see, drink
  healing potions and antidotes, and run back to you when a fight goes badly. `disable rover`
  removes just the rovers; `disable bot` still removes every bot.

## 2.12.0 - November 6, 2026

2.11 and older players can't join a 2.12 game, and 2.12 players can't join theirs.

### Added

- A join password. Host Game and the Server Tool have a Password field, and Join Game asks for
  it. Blank lets anyone in. The Server Tool shows it, and `server.py`, `client.py` and `bot.py`
  take `--password`. A wrong guess waits a second before the server answers.
- At most 6 players connected at once. A seventh is told the game is full. `server.py` takes
  `--max-players`.
- Limits on misbehaving players and bots. The server ignores messages from anyone sending more
  than about 30 a second, and disconnects anyone who keeps that up. More than 5 chat lines in a
  row get a "chatting too fast" warning. One address can only join about once every 10 seconds,
  except your own computer. A message over 16 KB ends the connection.
- Test console: `enable bot [count]` adds up to 5 bot teammates, and `disable bot` removes them.
  Bots follow the player who added them, fight with auto attack, revive players who are down, and
  appear beside you if they fall behind. They run inside the server and take no player seats.

- Antidote (`!`, 40 gold): every merchant sells it. It cures slime poison and the slowness that
  comes with it, and spider venom.
- Menus: click a choice's `<` to step it back or `>` to step it on. Clicking the value itself still
  steps it on.
- The test console finishes what you type. Tab completes command names and then what each command
  takes: items, monsters, players or on/off. Press Tab again for the next choice, or click one in
  the list shown above the typing line.
- Click a command, item or monster name in the console to fill it in: after `list`, clicking an
  item makes `give <item> ` and a monster makes `spawn <monster> `. Click `help` in the title to
  list the commands, or `[x]` to close. What can be clicked lights up under the pointer.
- Auto attack, in Options. While you stand still you hit monsters fighting you from the 8 tiles
  around you, and with nothing beside you, a readied bow, boomerang, wand or staff fires at them.
  With it on, using one of those from the pack readies it instead of firing it. It never attacks
  sleeping or wandering monsters, or a monkey you haven't attacked.
- The fisherman's hook (`⌡`), dropped by every monkey. Give hooks back to the fisherman and he
  thanks you with a potion of strength for each, which adds 2 to your melee damage for the rest of
  the run. Potions of strength aren't found anywhere else.

### Changed

- Floor layouts change with depth. Floors 9 to 14 are mostly caves, round rooms come back from
  floor 15, and from floor 41 rooms tend to come in mirrored pairs. Floors 50 to 59 try out new
  layouts: a maze, rings, a grid of rooms, a pillared hall and one huge cavern. Floors 1 to 8 are
  unchanged.
- A kobold leader's spear thrust shows: a red `-`, `|`, `/` or `\`, depending on the angle, across
  the tile between you and lunging into yours. After 5 thrusts it's winded and backs off for 3
  seconds before coming back.
- Grass (`"`) no longer blocks sight; only tall grass (`τ`, once called foliage) does.
- One monkey a run, on the floor above or below the fisherman's, instead of monkeys on any floor
  from 2 to 10. A run without a fisherman has none.
- When the whole party falls, the new dungeon waits 10 seconds instead of 4, with a countdown on
  the status line. Press Enter to start it sooner; with more than one player, it starts once
  everyone still connected has pressed Enter.
- Kobolds (green `k`) keep their distance and throw 3 or 4 rocks, up to 6 tiles, before they close
  in to fight. One you get next to steps back to throw again; cornered, it fights.
- Wolves can lose their nerve. A wolf has a 20% chance of running when it falls below 20% of its
  health, and another 20% chance when more than a third of its pack is below half health. One that
  runs keeps running, and fights only when cornered.
- Monkeys are thieves. One leaves you be unless you attack it, then fights back. It steals one item
  or 15 to 25 gold, never what you're wearing, a key or the Amulet, and runs until it's more than 30
  tiles away. Half the time it drinks a stolen potion, which works on it as it would on you:
  healing, haste, strength, levitation, water or lava walking, or teleporting to a random floor.
  Attacked and below 40% health, it has a 66% chance of running, and drops what it stole. Killed,
  it drops what it stole, 10 to 30 gold and a fisherman's hook.

- Options: "Ranged weapons aim at" is now "Ranged aim at", so it no longer runs into its value.

### Removed

- The Go downstairs and Go upstairs keys (`>` and `<`). Walk into the stairs to take them, as
  before. `>` and `<` are free to give to other actions.

## 2.11.0 - November 2, 2026

2.10 players can still join a 2.11 game.

### Added

- Difficulty, chosen by the host, in place of Monster speed and Game mode:
  - **Easy**: slow monsters with less health and armor, health returns over time, and a teammate
    revives you in 3 seconds.
  - **Medium**: normal monsters, no health over time, and reviving takes 8 seconds.
  - **Hard**: fast monsters with more health and armor, no health over time, and no reviving.
  The server's `--mode` option is now `--difficulty`.
- The giant spider queen (`A`) nests in big caves on floors 8 to 40, with 2 or 3 spiders (`a`) and
  webs that slow you. Run more than 5 tiles from her and she spits web that slows you even more.
  Spiders leap at you, bite, and back off. Their venom lasts up to 40 seconds and stops healing,
  but never takes you below 1 health. The console's `spawn nest` adds one.
- Arrows, rocks, kobold scouts' fireballs and spat web fly across the map a tile at a time, like
  the boomerang, instead of flashing. Magic still flashes.
- Merchants and the fisherman no longer block the way, even in a doorway. Walk into one to shop or
  talk, then walk into them again straight away to step past.

### Changed

- The cult leader fights with its wand of fire. It backs off out of reach, throws three fire bolts
  one after another, the last setting the ground around you alight, then rests 2 seconds. It has 75
  health instead of 50, more armor and hits harder up close.
- The cultist mage has 65 health instead of 45 and more armor, and casts lightning every 2.5
  seconds instead of 3.
- A locked room's walls are drawn in its key's color, so it stands out from across the floor.
- The fisherman always waits at the water's edge, on a floor from 2 to 6 that has water.
- The console's `list` sorts items by kind and puts everything in columns. `list items` or
  `list monsters` shows just one.

### Fixed

- A monster killed by a boomerang or an arrow stays in view until the shot reaches it.
- The way into a hidden room was a single `#` a shade off from the rest of the wall, so it looked
  as if its fairy was shut in for good. It's now a gold `▒` stretch 1 to 3 tiles wide, and a bomb
  beside any of it breaks all of it open. 2.10.0 and 2.10.1 players still see it as a `#`.

## 2.10.1 - November 2, 2026

### Changed

- The title screen shows the date the project began, October 30, 2026, instead of the release
  date.

## 2.10.0 - November 2, 2026

Players need this version to play together: 2.9 and 2.10 can't join each other's games.

### Added

- Merchants buy what you carry for half its price. Press Tab at a shop to switch to selling. What
  you sell is gone for good.
- Bombs. Merchants always have them, and now and then one lies on the floor. One goes off 2 seconds
  after you set it down, hurting everyone beside it and setting grass alight.
- Hidden rooms behind cracked walls, which look like the walls around them, a shade off in color.
  A floor with no locked room and no cult altar has a 33% chance of one. Bomb the wall open to
  find a fairy, which raises every living player's maximum health by a fifth.
- A fisherman on one floor from 2 to 6, often by the water. He tells you which floor a key lies on,
  or gives you a tip.
- Barrels of food, in rooms with a door and nothing but a torch. Walk into one: "Food is good!", and
  you heal quickly for 8 seconds.
- The cultist mage, a floor above or below each cult. It floats out of reach of melee, glowing
  violet, and casts lightning, which a ward stops. It drops a staff of lightning that never runs
  out and can't be enhanced.
- Kobold leaders (blue `K`) with spears on floors 5 to 25, and kobold scouts (red `k`) throwing
  fireballs on floors 10 to 15.
- War bands of skeleton warriors on every third floor from 50 to 68, never more than 9 on a floor.
- New armor: chain mail, the mithril shirt and dragon scale armor. New weapons: the flame blade and
  frost brand, which carry magic of their own, and the war axe and greatsword.
- Monsters leave a mark where they die: blood, slime goo, bones, rot or spores.
- The wand of fire sets the ground alight around its target, and fire spreads through grass until
  it's all burned to ash. Monsters on fire and below half health run.
- The console's `give gold <amount>`, and `summon [player]`, which brings a player, or everyone,
  to stand beside you.
- Names too long for the sidebar, the pack or the shop scroll along so you can read all of them.

### Changed

- Score is now gold carried times kills, times 100, divided by moves. A win doubles it.
- Each time an altar enhances a weapon, its damage also goes up by 15%.
- A boomerang flies back to you, and can't be thrown again until it's back in your hand, which
  takes at least a second.
- A kobold on its own runs, sometimes throws a rock when it's hurt, and sometimes kills a rat.

### Fixed

- Lava no longer forms in or beside water.

## 2.9.1 - November 1, 2026

### Fixed

- `killall` no longer fails partway when the player using it is down.
- The pack and the shop show whole names, so stacks of greater healing show their count.
- Long lines in the action log wrap instead of being cut off, and the file's name always shows.
- The help panel, its tips, the Look panel, the hint line and "Press g to pick it up" all show your
  own keys. The help panel only lists hjklyubn keys that still walk.
- The hint line fits the screen again, so it no longer ends in a lone Q.

## 2.9.0 - November 1, 2026

### Added

- WASD moves you. Arrows, the numpad and hjklyubn still work, and drop moves from d to x.
- A quick heal key, q, which drinks the smallest healing potion that fills you up.
- Options now has a Controls screen for changing keys.
- The pack can be sorted with o, and its items can be clicked to use or drop them.

### Changed

- Players walk straight past each other now, and only swap places if there's nowhere to land.
- Auto-walking goes through allies instead of treating them as walls.

## 2.8.0 - November 1, 2026

### Added

- An action log. Press v to read it in the game, even after you die, or open the text file saved
  for each run. It notes fights, damage, items, floors, deaths, test commands and game errors.
- The mouse wheel scrolls the action log and the test console.

## 2.7.8 - November 1, 2026

### Changed

- Potions of lava walking last 1 minute instead of 15 seconds.
- Lava walking now gives you an orange glow reaching 5 tiles, which holds for 5 seconds, then
  fades slowly until the potion runs out.

## 2.7.7 - November 1, 2026

### Changed

- Potions of water walking last 1 minute instead of 15 seconds.
- Their glow now holds for 5 seconds, then fades slowly until the potion runs out.

## 2.7.6 - November 1, 2026

### Changed

- The water walking glow now fades evenly and really reaches 5 tiles, where it used to stop short.
- Magic armor's glow pulses about half as fast, once every 9 seconds.

## 2.7.5 - November 1, 2026

### Changed

- Monsters about to hit now blink about twice in a swing, and more softly, instead of strobing.

## 2.7.4 - November 1, 2026

### Changed

- 40% fewer mushrooms, with at most 8 on a floor, and none from floor 51 down.

## 2.7.3 - November 1, 2026

### Changed

- Skeleton archers now move a third slower, and hold 6 to 11 tiles away instead of 5 to 9.

## 2.7.2 - November 1, 2026

### Changed

- A pond's ward now shows as a blue glow around you instead of sparks, and lasts 3 minutes.

## 2.7.1 - October 31, 2026

### Changed

- A thrown boomerang now spins across the map through `/ - \ |` instead of showing as a flash.

## 2.7.0 - October 31, 2026

### Added

- Ghosts that pass through walls. One comes for you 2 floors after you use an altar.
- Weapons enhanced at an altar do 1.5 times the damage to the undead.

## 2.6.0 - October 31, 2026

### Added

- Skeleton archers on floors 70 to 90, who keep 5 to 9 tiles away and shoot.
- Skeleton warriors, the main enemy of floors 80 to 98.
- Slimes on floors 25 to 85, whose touch and trail poison you and slow you down.

### Changed

- Ogres now stop at floor 65, and are most common on floors 45 to 55.

## 2.5.0 - October 31, 2026

### Added

- Bows, arrows in piles of 20 to 30, and the boomerang, with a range of 9.
- A hoard of gold and a store of potions in the side rooms of floor 99.
- Ranged weapons and wands now aim at the strongest monster, with an option for the weakest.

### Changed

- Floors 90 to 99 have zombies, cultists and wolves, instead of ogres and mushrooms.
- The Amulet now lies well away from the doors of the necromancer's room.

## 2.4.2 - October 31, 2026

### Changed

- Water walking now gives you a blue glow reaching 5 tiles.
- Magic armor now shows a slowly pulsing 3x3 glow.
- Monsters about to hit you now only blink. Instead, the red glow appears on a monster when a
  player strikes it.

## 2.4.1 - October 31, 2026

### Changed

- Monsters' melee attacks now come half as often, which also gives twice as long to see them coming.

## 2.4.0 - October 31, 2026

### Added

- Monsters about to land a melee hit turn red and blink, faster and brighter as it gets close.

## 2.3.0 - October 31, 2026

### Added

- An `ultrabright` console command, which lights up every floor until you turn it off.

### Changed

- The `reveal` console command is now a toggle. While it's on, every floor is mapped and all its
  monsters and items are marked as they appear, with or without `ultrabright`.

Players need 2.3.0 or newer to join each other's games.

## 2.2.1 - October 31, 2026

### Changed

- Toxic gas now spreads no more than 4 tiles from the mushroom in any direction.

## 2.2.0 - October 31, 2026

### Added

- A buried tower on floors 90 to 99: symmetrical, with several rooms and glowing green walls.
- Floor 89, an empty hall and atrium leading down to it.
- Floor 99 is now a great round room with pillars and smaller rooms off it.
- Ponds of healing, which heal you and ward you against magic once.
- A skeletal dragon on floor 80 that breathes fire.

### Changed

- Water and lava are animated.
- Toxic gas fills the room and thins out from the edges before it's gone.
- Magic armor now turns up on floors 60 to 70, and reflects magic.

Players need 2.2.0 or newer to join each other's games. The same seed now builds a different
dungeon.

## 2.1.0 - October 31, 2026

### Added

- Cultists now surround a glowing purple altar. Walk into it to enhance your weapon, for good, in
  one random way. Each altar works once.

### Changed

- A potion of teleportation now takes you to a random floor, from 1 to 99, instead of elsewhere on
  this one. The console's `teleport` still stays on the floor.

Players need 2.1.0 or newer to join each other's games.

## 2.0.0 - October 31, 2026

The dungeon now has an ending.

### Added

- Floor 99 is the last floor. The necromancer sleeps there beside the Amulet, which you must carry
  up the stairs on floor 1 to win. Beat it, or sneak past it.
- The necromancer raises 2 to 5 zombies at a time. Leave its floor with it awake and zombies keep
  coming on every floor you climb to.
- Packs of wolves, mushrooms that release toxic gas, and the wand of frost.
- Tall grass and foliage, which block sight until something tramples them.

### Changed

- Moves now divide your score instead of adding to it.

Players need 2.0.0 to join each other's games. The same seed now builds a different dungeon.

## 1.10.0 - October 31, 2026

### Changed

- Lakes and rivers now cut off parts of a floor, which only water walking or levitation can reach.
  The stairs, locked doors, keys, cloaks and merchants always stay reachable on foot.
- From an island you can swim back, at half speed.

The same seed now builds a different dungeon.

## 1.9.0 - October 31, 2026

### Added

- A `collision` console command. With it off, you walk through walls, enemies and hazards.

## 1.8.0 - October 31, 2026

### Added

- A `floor` console command, which moves you or another player to any floor.

## 1.7.0 - October 31, 2026

### Added

- A test console, opened with `` ` `` or F2. Only someone playing on the host's computer can use
  it, and everyone else is told when a command runs.
- Potion of teleportation, found on any floor, which jumps you to a random spot well away from
  where you are.

Players need 1.7.0 or newer to join each other's games. The same seed now places items
differently.

## 1.6.0 - October 31, 2026

### Added

- Lava from floor 51 down. A pit can drop you into it with no warning, for 25 damage on top of the
  fall.
- Potions of water walking and lava walking, on floors 18 to 42.
- Groups of 6 to 12 cultists from floor 10 down. Their leader drops a wand of fire, which breaks
  after 10 uses.

### Changed

- A cloak now cuts detection range by 50%.
- Items and monsters with a last floor past the end of the lists now stop there properly.

Players need 1.6.0 or newer to join each other's games. The same seed now builds a different
dungeon.

## 1.5.0 - October 31, 2026

### Added

- Cloaks: one per player in each run, on a random floor. Wearing one cuts your detection range by
  25% and takes 20 off the noise of your gear.
- Critical hits: attacking a sleeping monster with at least 30% stealth does five times normal
  damage.

### Changed

- Monsters share their route maps, so big fights cost the server far less.
- Auto-walk only works out a new route when something has changed.

### Fixed

- Leaving while holding Shift no longer keeps you sprinting when you rejoin.
- Typos in the README and comments, and the README's code formatting.

## 1.4.0 - October 31, 2026

### Added

- Torches on the walls, with flickering light that stops at walls. Monsters notice you from up to
  75% further away in their light.
- A stamina bar. Hold Shift to sprint. Sprinting and attacking spend it, and with too little left
  your attacks take twice as long.
- A different tip each time you open the help.

Players need 1.4.0 or newer to join each other's games. The same seed now builds a slightly
different dungeon.

## 1.3.0 - October 31, 2026

### Added

- Lakes and rivers that run through rooms and rock. Deep water stops you on foot, and a shallow
  ford is left wherever water would cut a floor in two, so the stairs can always be reached.
- Pits that drop you a floor for 3 to 6 damage. A fall can't kill you.
- Locked rooms on floors 4 to 14, with a matching key exactly 2 floors above or below.
- A potion of levitation now carries you over water and pits.

Players need 1.3.0 or newer to join each other's games. The same seed now builds a different
dungeon.

## 1.2.2 - October 31, 2026

### Fixed

- The holiday option worked backwards, with the themes showing when it said Off. It's now called
  **Holiday themes**: On shows them, Off hides them, and it starts On.

## 1.2.1 - October 31, 2026

### Changed

- Added **Hide holiday themes** to Options. It's On by default, which turns the themes off.
  The host's setting applies to everyone in a game.

## 1.2.0 - October 31, 2026

### Added

- Merchants: every 5th floor has a 60% chance of one selling weapons and armor. Spending gold
  lowers your score.
- Potion of levitation: rare, and 600 gold when a merchant has one. For 9 seconds ground monsters
  can't reach you and moving doesn't use up stealth, with a floating effect on your character.

Players need 1.2.0 or newer to join each other's games. The same seed now builds a slightly
different dungeon, because of the new potion.

## 1.1.0 - October 31, 2026

### Added

- Hold right click to walk toward the pointer, around walls and along the way you've explored.
  Point at a monster to chase and attack it, or at stairs to take them. Letting go stops you
  at once, and a movement key takes over.

Only the client changed, so 1.1.0 and 1.0.0 can play together.

## 1.0.0 - October 31, 2026

The first full release. There are no gameplay changes from 0.2.0, and the two can play together.

- Versioning rules are written down in the README.
- Every release is tagged in Git, and this changelog records what changed.

## 0.2.0 - October 31, 2026

### Added

- Holiday themes: monsters and items get Halloween names from October 24 to 31 and Christmas
  names from December 18 to 26, by the system clock. They only change how things look.
- Holiday greetings on the title screen and when joining.
- `--season` option on `server.py`, to preview a theme.

Players need 0.2.0 or newer to join each other's games; 0.1.x copies are refused.

## 0.1.1 - October 31, 2026

### Fixed

- Long monster names were cut off in the sidebar when "(asleep)" was added to them. "asleep" now
  appears on the monster's health bar.

## 0.1.0 - October 31, 2026

The first numbered version.

- Real-time online co-op with Host Game, Join Game and a Server Tool, in one exe.
- Brogue-style level generation, field of view and monsters.
- Classic and Revive game modes.
- Character creation: name, shape and color.
- Potions, weapons, armor, gold, a 10-slot pack, and dropping items for teammates.
- Stealth, limited by the noise of equipped gear.
- Score, kill tally and hardest enemy fought.
- Run clock, players list with floor and ping, Look panel, and help panel.
- Version check when joining a server.
