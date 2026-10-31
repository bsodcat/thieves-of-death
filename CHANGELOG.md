# Changelog

Versions are MAJOR.MINOR.PATCH. See "Versions" in the README for what each number means.

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
