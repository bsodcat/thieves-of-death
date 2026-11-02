# Changelog

Versions are MAJOR.MINOR.PATCH. See "Versions" in the README for what each number means.

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
