"""Holiday looks: on only at the right dates, and strictly cosmetic."""
import dataclasses
import textwrap
import unittest
from datetime import date
from unittest import mock

from game import protocol, seasons
from game.constants import LOOK_Y, SCORE_SCALE, SCREEN_H, SIDEBAR_W, TICKS_PER_TURN
from game.entities import MONSTERS, make_monster
from game.items import ITEMS, make_gold, make_item
from game.render import ClientView
from game.world import World
from server import ServerRunner

ALL = tuple(seasons.SEASONS)


def in_season(name):
    return lambda: name


def view_of(w, p):
    v = ClientView()
    v.apply({"t": "welcome", "id": p.id, "name": p.name})
    for msg in (w.level_msg(p.depth), w.pack_msg(p), w.state_for(p)):
        v.apply(protocol.decode(protocol.encode(msg)))
    return v


def texts(lines):
    return " ".join(t for t, _ in lines)


class DateTests(unittest.TestCase):
    def test_halloween_window(self):
        self.assertEqual(seasons.active_season(date(2026, 10, 31)), "halloween")
        self.assertEqual(seasons.active_season(date(2026, 10, 24)), "halloween")
        self.assertIsNone(seasons.active_season(date(2026, 10, 23)))
        self.assertIsNone(seasons.active_season(date(2026, 11, 1)))

    def test_christmas_window(self):
        self.assertEqual(seasons.active_season(date(2026, 12, 25)), "christmas")
        self.assertEqual(seasons.active_season(date(2026, 12, 18)), "christmas")
        self.assertIsNone(seasons.active_season(date(2026, 12, 17)))
        self.assertIsNone(seasons.active_season(date(2026, 12, 27)))

    def test_every_year(self):
        for year in (2025, 2028, 2031):
            self.assertEqual(seasons.active_season(date(year, 10, 31)), "halloween")

    def test_ordinary_days(self):
        for day in (date(2026, 1, 1), date(2026, 7, 4), date(2026, 3, 15)):
            self.assertIsNone(seasons.active_season(day))

    def test_a_year_of_days_is_never_two_seasons_or_broken(self):
        for ordinal in range(date(2028, 1, 1).toordinal(), date(2029, 1, 1).toordinal()):
            self.assertIn(seasons.active_season(date.fromordinal(ordinal)), (None, *ALL))

    def test_current_reads_the_system_clock(self):
        with mock.patch("game.seasons.date") as fake:
            fake.today.return_value = date(2030, 12, 25)
            self.assertEqual(seasons.current(), "christmas")
            fake.today.return_value = date(2030, 6, 1)
            self.assertIsNone(seasons.current())


class CosmeticOnlyTests(unittest.TestCase):
    def fields(self, obj, ignore):
        return {f.name: getattr(obj, f.name) for f in dataclasses.fields(obj) if f.name not in ignore}

    def test_monsters_keep_every_stat(self):
        for season in ALL:
            for kind in MONSTERS:
                plain = make_monster(kind, 1)
                dressed = seasons.dress_monster(make_monster(kind, 1), season)
                self.assertNotEqual(dressed.name, plain.name, (season, kind))
                ignore = ("name", "color")
                self.assertEqual(self.fields(dressed, ignore), self.fields(plain, ignore), (season, kind))
                self.assertEqual(dressed.glyph, plain.glyph)

    def test_items_keep_every_stat(self):
        for season in ALL:
            for kind in ITEMS:
                plain = make_item(kind)
                dressed = seasons.dress_item(make_item(kind), season)
                self.assertNotEqual(dressed.name, plain.name, (season, kind))
                ignore = ("name", "color")
                self.assertEqual(self.fields(dressed, ignore), self.fields(plain, ignore), (season, kind))
                self.assertEqual(dressed.info, plain.info)
                self.assertEqual(dressed.glyph, plain.glyph)

    def test_the_same_dungeon_in_every_season(self):
        worlds = [World(5, season_fn=in_season(s)) for s in (None, *ALL)]
        layouts = []
        for w in worlds:
            lvl = w.level(2)
            layouts.append((lvl.tiles.tobytes(),
                            [(m.kind, m.x, m.y, m.hp, m.state) for m in lvl.monsters],
                            sorted((pos, i.kind, i.count) for pos, i in lvl.items.items())))
        self.assertEqual(layouts[0], layouts[1])
        self.assertEqual(layouts[0], layouts[2])

    def test_gold_amounts_and_score_are_unchanged(self):
        for season in ALL:
            gold = seasons.dress_item(make_gold(30), season)
            self.assertEqual(gold.count, 30)
            self.assertIn("30 ", gold.label)
            w = World(1, season_fn=in_season(season))
            w.level(1).items.clear()
            a = w.join("A")
            a.gold, a.kills, a.turns = 10, 2, 4
            self.assertEqual(w.score_of(a), 10 * 2 * SCORE_SCALE // 4)


class CoverageTests(unittest.TestCase):
    def test_every_monster_and_item_is_covered(self):
        for name, s in seasons.SEASONS.items():
            self.assertEqual(set(s["monsters"]), set(MONSTERS), name)
            self.assertEqual(set(s["items"]), set(ITEMS) | {"cloak", "fire_wand"}, name)

    def test_names_fit_the_ui(self):
        for s in seasons.SEASONS.values():
            for look in s["monsters"].values():
                self.assertLessEqual(len(look[0]), 16, look[0])
            for look in s["items"].values():
                self.assertLessEqual(len(look[0]), 22, look[0])

    def test_descriptions_fit_the_look_panel(self):
        limit = SCREEN_H - LOOK_Y - 1
        for s in seasons.SEASONS.values():
            for kind, look in s["monsters"].items():
                t = MONSTERS[kind]
                line = f"{look[2]} Hits for {t['damage'][0]}-{t['damage'][1]}. Fast. Slow hits."
                self.assertLessEqual(3 + len(textwrap.wrap(line, SIDEBAR_W - 2)), limit, look[0])

    def test_messages_fit_on_one_line(self):
        for s in seasons.SEASONS.values():
            self.assertLessEqual(len(s["joined"]), 79)


class InGameTests(unittest.TestCase):
    def world(self, season="halloween"):
        w = World(1, season_fn=in_season(season))
        lvl = w.level(1)
        for m in list(lvl.monsters):
            lvl.remove(m)
        lvl.monsters.clear()
        lvl.items.clear()
        return w, lvl, w.join("Alice")

    def test_off_season_is_untouched(self):
        w = World(1)
        lvl = w.level(1)
        self.assertIsNone(w.season)
        names = {t["name"] for t in MONSTERS.values()}
        self.assertTrue(all(m.name in names for m in lvl.monsters))
        self.assertTrue(all(i.name == "gold" if i.category == "gold" else i.name == ITEMS[i.kind]["name"]
                            for i in lvl.items.values()))
        a = w.join("A")
        self.assertFalse(any("Happy" in m["text"] or "Merry" in m["text"] for _, m in w.drain_outbox()))
        self.assertIsNone(w.state_for(a)["season"])

    def test_levels_are_dressed(self):
        w = World(3, season_fn=in_season("christmas"))
        lvl = w.level(1)
        looks = seasons.SEASONS["christmas"]
        self.assertTrue(lvl.monsters)
        self.assertTrue(all(m.name == looks["monsters"][m.kind][0] for m in lvl.monsters))
        for item in lvl.items.values():
            self.assertIn(item.name, ("chocolate coins", *[v[0] for v in looks["items"].values()]))

    def test_new_levels_get_dressed_too(self):
        w = World(3, season_fn=in_season("halloween"))
        names = {v[0] for v in seasons.SEASONS["halloween"]["monsters"].values()}
        self.assertTrue(all(m.name in names for m in w.level(4).monsters))

    def test_new_players_are_greeted(self):
        w, lvl, a = self.world()
        self.assertTrue(any("Happy Halloween" in m["text"] for _, m in w.drain_outbox()))

    def test_pickup_message_uses_the_flavored_name(self):
        w, lvl, a = self.world("christmas")
        lvl.items[(a.x, a.y)] = w._item("sword")
        w.drain_outbox()
        w.submit(a, {"a": "pickup"})
        self.assertTrue(any("peppermint sword" in m["text"] for _, m in w.drain_outbox()))

    def test_stacks_stay_flavored_when_split(self):
        w, lvl, a = self.world()
        item = w._item("healing")
        item.count = 3
        a.pack.append(item)
        w.submit(a, {"a": "drop", "slot": 0})
        self.assertEqual(lvl.items[(a.x, a.y)].name, "pumpkin juice")
        self.assertEqual(a.pack[0].label, "pumpkin juice x2")

    def test_flavored_potions_still_stack_with_each_other(self):
        w, lvl, a = self.world()
        a.pack.append(w._item("healing"))
        lvl.items[(a.x, a.y)] = w._item("healing")
        w.submit(a, {"a": "pickup"})
        self.assertEqual(a.pack[0].count, 2)

    def test_gold_is_flavored_in_every_message(self):
        w, lvl, a = self.world()
        a.gold = 30
        w.drain_outbox()
        w.submit(a, {"a": "dropgold"})
        self.assertTrue(any("25 candy corn" in m["text"] for _, m in w.drain_outbox()))
        self.assertEqual(lvl.items[(a.x, a.y)].label, "25 candy corn")

    def test_scattered_gold_is_flavored(self):
        w, lvl, a = self.world("christmas")
        a.gold = 30
        w._kill(a, make_monster("rat", 800))
        self.assertEqual(next(iter(lvl.items.values())).label, "30 chocolate coins")

    def test_combat_tally_and_death_use_the_flavored_name(self):
        w, lvl, a = self.world()
        m = seasons.dress_monster(make_monster("rat", 900), w.season)
        m.hp, m.state = 1, "wandering"
        dx, dy = next((d for d in ((1, 0), (-1, 0), (0, 1), (0, -1))
                       if lvl.walkable[a.x + d[0], a.y + d[1]] and (a.x + d[0], a.y + d[1]) not in lvl.occupant))
        lvl.place(m, a.x + dx, a.y + dy)
        lvl.monsters.append(m)
        w.drain_outbox()
        w.submit(a, {"a": "move", "dx": dx, "dy": dy})
        said = " ".join(msg["text"] for _, msg in w.drain_outbox() if msg["t"] == "msg")
        self.assertIn("skeletal rat", said)
        st = w.state_for(a)
        self.assertEqual(st["tally"], {"skeletal rat": 1})
        self.assertEqual(st["hardest"], "skeletal rat")
        w._kill(a, seasons.dress_monster(make_monster("ogre", 901), w.season))
        self.assertEqual(a.death, "Killed by a zombie ogre on depth 1.")

    def test_look_panel_uses_the_flavored_description_and_real_stats(self):
        w, lvl, a = self.world()
        spot = next(c for c in lvl.floor_cells if w.fov(a)[c] and c != (a.x, a.y) and c not in lvl.occupant)
        m = seasons.dress_monster(make_monster("goblin", 900), w.season)
        lvl.place(m, *spot)
        lvl.monsters.append(m)
        text = texts(view_of(w, a).describe(*spot))
        self.assertIn("Ghostly goblin", text)
        self.assertIn("Cold to the touch.", text)
        self.assertIn("Hits for 2-5", text)

    def test_look_at_a_flavored_item(self):
        w, lvl, a = self.world("christmas")
        spot = next(c for c in lvl.floor_cells if w.fov(a)[c] and c != (a.x, a.y))
        lvl.items[spot] = w._item("mace")
        text = texts(view_of(w, a).describe(*spot))
        self.assertIn("Yule log", text)
        self.assertIn("Dmg 12-18, slow, noise 20", text)


class DisplayTests(unittest.TestCase):
    def screen(self, v):
        frame = v.draw()
        return "\n".join("".join(chr(c) for c in frame["ch"][:, y]) for y in range(frame.shape[1]))

    def test_longest_names_fit_the_sidebar_and_asleep_still_shows(self):
        for season in ALL:
            w = World(1, season_fn=in_season(season))
            lvl = w.level(1)
            for m in list(lvl.monsters):
                lvl.remove(m)
            lvl.monsters.clear()
            a = w.join("A")
            cells = [c for c in lvl.floor_cells if w.fov(a)[c] and c not in lvl.occupant]
            kind = max(MONSTERS, key=lambda k: len(seasons.SEASONS[season]["monsters"][k][0]))
            m = seasons.dress_monster(make_monster(kind, 900), season)
            m.state = "sleeping"
            lvl.place(m, *cells[0])
            lvl.monsters.append(m)
            text = self.screen(view_of(w, a))
            self.assertIn(f"{m.glyph} {m.name}", text)
            self.assertIn("asleep", text)

    def test_pack_panel_uses_the_flavored_gold_name(self):
        w = World(1, season_fn=in_season("halloween"))
        a = w.join("A")
        a.gold = 40
        v = view_of(w, a)
        v.show_pack = True
        self.assertIn("40 candy corn", self.screen(v))

    def test_off_season_pack_still_says_gold(self):
        w = World(1)
        a = w.join("A")
        a.gold = 40
        v = view_of(w, a)
        v.show_pack = True
        self.assertIn("40 gold", self.screen(v))


class RunBoundaryTests(unittest.TestCase):
    def test_looks_hold_through_a_run_then_follow_the_date(self):
        today = ["halloween"]
        w = World(1, season_fn=lambda: today[0])
        a = w.join("A")
        monsters = list(w.level(1).monsters)
        names = [m.name for m in monsters]
        today[0] = None                        # midnight passes mid-run
        w.level(2)
        w.advance(TICKS_PER_TURN * 5)
        self.assertEqual(w.season, "halloween")
        self.assertEqual([m.name for m in monsters], names)
        w.reset_run()                          # the next run follows the new date
        self.assertIsNone(w.season)
        plain = {t["name"] for t in MONSTERS.values()}
        self.assertTrue(all(m.name in plain for m in w.level(1).monsters))

    def test_the_app_follows_the_system_date(self):
        with mock.patch("game.seasons.date") as fake:
            fake.today.return_value = date(2030, 12, 25)
            runner = ServerRunner(0, host="127.0.0.1")
            self.assertEqual(runner.world.season, "christmas")
            fake.today.return_value = date(2030, 8, 1)
            runner = ServerRunner(0, host="127.0.0.1")
            self.assertIsNone(runner.world.season)


class TitleTests(unittest.TestCase):
    def test_greetings(self):
        self.assertEqual(seasons.greeting("halloween"), "Happy Halloween!")
        self.assertEqual(seasons.greeting("christmas"), "Merry Christmas!")
        self.assertEqual(seasons.greeting(None), "")


if __name__ == "__main__":
    unittest.main()
