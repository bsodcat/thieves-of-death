"""Selling, the console's gold and summon, the fisherman, food barrels, the boomerang's return,
the score, altars' extra damage and names that scroll."""
import math
import unittest
from unittest import mock

from game import commands
from game.constants import (BOOMERANG_TILE_SECONDS, BOOMERANG_WAIT, ENHANCE_BOOST, FISHER_FLOORS, FOOD_HEAL, FOOD_SECONDS, MAP_X,
                            MAP_Y, SCORE_SCALE, TICKS_PER_SECOND)
from game.items import ITEMS, enhance_weapon, make_amulet, make_item, make_key
from game.render import ClientView
from game.tiles import DEEP, DOOR, POND, SHALLOW, WALL
from game.world import World
from helpers_210 import add, deliver, empty_world, open_spot, put, said, seconds, view_of
from test_shop import screen, with_merchant


class SellTests(unittest.TestCase):
    def setUp(self):
        self.w, self.lvl, self.m, self.step, (self.a,) = with_merchant()

    def sell(self, slot):
        self.a.next_time = self.w.clock
        self.w.submit(self.a, {"a": "sell", "slot": slot})

    def test_half_price_and_gone_for_good(self):
        sword = make_item("sword")
        self.w._stash(self.a, sword)
        stock = dict(self.m.stock)
        self.sell(0)
        self.assertEqual(self.a.gold, sword.price // 2)
        self.assertEqual(self.a.pack, [])
        self.assertEqual(self.m.stock, stock)  # nobody can buy it back
        self.assertIn("gone for good", said(self.w))

    def test_one_potion_at_a_time_but_a_whole_quiver(self):
        potion = make_item("healing")
        potion.count = 3
        arrows = make_item("arrows")
        arrows.count = 20
        self.w._stash(self.a, potion)
        self.w._stash(self.a, arrows)
        self.sell(0)
        self.assertEqual(potion.count, 2)
        self.sell(1)
        self.assertNotIn(arrows, self.a.pack)
        self.assertEqual(self.a.gold, potion.price // 2 + 20 * max(1, arrows.price // 2))

    def test_keys_and_the_amulet_arent_for_sale(self):
        self.w._stash(self.a, make_key("red", 5))
        self.w._stash(self.a, make_amulet())
        self.sell(0)
        self.sell(1)
        self.assertEqual(len(self.a.pack), 2)
        self.assertEqual(self.a.gold, 0)

    def test_selling_what_you_wear_takes_it_off(self):
        sword = make_item("sword")
        self.w._stash(self.a, sword)
        self.w.submit(self.a, {"a": "use", "slot": 0})
        self.assertIs(self.a.weapon, sword)
        self.sell(0)
        self.assertIsNone(self.a.weapon)

    def test_only_at_the_shop(self):
        self.lvl.merchant = None
        self.w._stash(self.a, make_item("sword"))
        self.sell(0)
        self.assertEqual(len(self.a.pack), 1)

    def test_every_item_has_a_price(self):
        for kind, entry in ITEMS.items():
            self.assertGreater(entry.get("price", 0), 0, kind)

    def test_the_screen(self):
        self.w._stash(self.a, make_item("sword"))
        self.w._stash(self.a, make_key("red", 5))
        self.w.submit(self.a, self.step)
        v = view_of(self.w, self.a)
        deliver(self.w, v, self.a.id)
        self.assertIn("Tab to sell", screen(v))
        v.toggle_selling()
        text = screen(v)
        self.assertIn("sell for half", text)
        self.assertIn(str(make_item("sword").price // 2), text)
        self.assertIn("won't buy", text)


class ConsoleTests(unittest.TestCase):
    def test_give_gold(self):
        w, lvl, p = empty_world()
        p.can_command = True
        commands.run(w, p, "give gold 500")
        self.assertEqual(p.gold, 500)
        commands.run(w, p, "give gold")
        self.assertEqual(p.gold, 600)

    def test_summon_brings_a_guest_to_the_host(self):
        w, lvl, host, guest = empty_world(names=("Host", "Guest"))
        host.can_command = True
        w.warp(guest, 7)
        commands.run(w, host, "summon guest")
        self.assertEqual(guest.depth, host.depth)
        self.assertLessEqual(max(abs(guest.x - host.x), abs(guest.y - host.y)), 2)
        self.assertNotIn(guest, w.levels[7].occupant.values())

    def test_summon_with_no_name_brings_everyone(self):
        w, lvl, host, b, c = empty_world(names=("Host", "B", "C"))
        host.can_command = True
        w.warp(b, 4)
        w.warp(c, 9)
        commands.run(w, host, "summon")
        self.assertEqual({b.depth, c.depth}, {host.depth})


class FishermanTests(unittest.TestCase):
    def test_one_on_an_early_floor(self):
        for seed in range(8):
            w = World(seed)
            found = [(d, n) for d in range(1, 9) for n in w.level(d).npcs if n.role == "fisherman"]
            self.assertEqual(len(found), 1, seed)
            depth, f = found[0]
            self.assertTrue(FISHER_FLOORS[0] <= depth <= FISHER_FLOORS[1])
            beside = {int(w.level(depth).tiles[f.x + dx, f.y + dy]) for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
            self.assertTrue(beside & {SHALLOW, DEEP, POND}, seed)  # he's always at the water's edge

    def test_no_water_no_fisherman(self):
        w = World(1)
        with mock.patch.object(World, "_shore", return_value=[]):
            self.assertIsNone(w.fisher_floor())
            self.assertFalse([n for d in range(1, 8) for n in w.level(d).npcs if n.role == "fisherman"])

    def test_looking_ahead_doesnt_change_the_floors(self):
        early, late = World(4), World(4)
        early.fisher_floor()
        for depth in range(1, 8):
            self.assertTrue((early.level(depth).tiles == late.level(depth).tiles).all(), depth)

    def talk(self, w):
        p = w.join("Alice")
        lvl = w.level(w.fisher_floor())
        f = next(n for n in lvl.npcs if n.role == "fisherman")
        w.warp(p, lvl.depth)
        spot = next((f.x + dx, f.y + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                    if lvl.walkable[f.x + dx, f.y + dy] and (f.x + dx, f.y + dy) not in lvl.occupant)
        lvl.move(p, *spot)
        w.drain_outbox()
        w.submit(p, {"a": "move", "dx": f.x - p.x, "dy": f.y - p.y})
        return p, w.drain_outbox()

    def test_he_knows_where_a_key_is(self):
        w = next(World(s) for s in range(50) if World(s).locked_rooms)
        p, out = self.talk(w)
        text = " ".join(m.get("text", "") for _, m in out)
        room = sorted(w.locked_rooms.values(), key=lambda r: r.depth)[0]
        self.assertIn(f"The {room.color} key lies on floor {room.key_depth}", text)

    def test_with_no_keys_he_gives_a_tip(self):
        w = next(World(s) for s in range(50) if not World(s).locked_rooms)
        p, out = self.talk(w)
        tips = [m for _, m in out if m["t"] == "tip"]
        self.assertEqual(len(tips), 1)
        v = ClientView()
        v.apply(tips[0])
        self.assertTrue(v.messages[-1][0].startswith('The fisherman says: "'))


class FoodTests(unittest.TestCase):
    def test_walk_over_it_and_it_heals_for_a_while(self):
        w, lvl, p = empty_world()
        x, y = open_spot(lvl)
        put(lvl, p, x, y)
        from game.items import make_barrel
        lvl.items[(x + 1, y)] = make_barrel()
        p.hp = 5
        w.submit(p, {"a": "move", "dx": 1, "dy": 0})
        self.assertNotIn((x + 1, y), lvl.items)
        self.assertEqual(p.pack, [])
        self.assertIn("Food is good!", said(w))
        p.regen_acc = -10 ** 9  # leave ordinary healing out of it
        w.advance(seconds(FOOD_SECONDS) + 50)
        self.assertEqual(p.hp, 5 + FOOD_HEAL * int(FOOD_SECONDS))
        w.advance(seconds(3))
        self.assertEqual(p.hp, 5 + FOOD_HEAL * int(FOOD_SECONDS))

    def test_barrels_stand_in_quiet_rooms_with_a_door_and_a_torch(self):
        found = 0
        for seed in range(6):
            w = World(seed)
            for depth in range(1, 15):
                lvl = w.level(depth)
                barrels = [spot for spot, item in lvl.items.items() if item.category == "food"]
                self.assertLessEqual(len(barrels), 1)
                for spot in barrels:
                    found += 1
                    room, doors = room_of(lvl, spot)
                    self.assertTrue(doors, (seed, depth))
                    self.assertEqual(sum(front in room for _, front in lvl.torches), 1)
                    others = [c for c in room if c != spot and (c in lvl.items or c in lvl.occupant)]
                    self.assertEqual(others, [], (seed, depth))
        self.assertGreater(found, 0)


def room_of(lvl, start):
    """The tiles you can walk to from `start` without going through a door, and how many doors it has."""
    room, todo, doors = {start}, [start], 0
    while todo:
        x, y = todo.pop()
        for dx, dy in ((0, 1), (1, 0), (0, -1), (-1, 0)):
            n = (x + dx, y + dy)
            if n in room or not lvl.walkable[n]:
                continue
            if lvl.tiles[n] == DOOR:
                doors += 1
                continue
            room.add(n)
            todo.append(n)
    return room, doors


class BoomerangTests(unittest.TestCase):
    def setUp(self):
        self.w, self.lvl, self.p = empty_world()
        self.x, self.y = open_spot(self.lvl)
        put(self.lvl, self.p, self.x, self.y)
        self.m = add(self.w, self.lvl, "ogre", self.x + 3, self.y, state="wandering")
        self.boomerang = make_item("boomerang")
        self.w._stash(self.p, self.boomerang)

    def throw(self):
        self.p.next_time = self.w.clock
        self.w.submit(self.p, {"a": "use", "slot": 0})

    def test_it_cant_be_thrown_again_until_its_back(self):
        self.throw()
        hp = self.m.hp
        self.throw()
        self.assertEqual(self.m.hp, hp)
        self.assertIn("hasn't come back", said(self.w))
        self.w.advance(seconds(BOOMERANG_WAIT) - 5)
        self.assertNotIn("comes back", said(self.w))  # never sooner than this, even this close
        self.w.advance(10)
        self.assertIn("comes back", said(self.w))
        self.throw()
        self.assertNotIn("hasn't come back", said(self.w))

    def test_you_see_it_fly_back(self):
        v = view_of(self.w, self.p)
        self.throw()
        deliver(self.w, v, self.p.id)
        path = v.throws[-1][0]
        self.assertEqual(path, path[::-1])  # the same way back as out
        self.assertEqual(path[0], (self.x + 1, self.y))
        self.assertEqual(len(path), 5)  # out three tiles, back two to your side

    def test_what_it_kills_stays_in_view_until_it_gets_there(self):
        import client
        v = view_of(self.w, self.p)
        self.m.hp = 1
        glyph, color = self.m.glyph, tuple(self.m.color)
        self.throw()
        deliver(self.w, v, self.p.id)
        self.assertNotIn(self.m, self.lvl.occupant.values())  # the server has it dead already
        cells, thrown, fell = v.throws[-1]
        self.assertEqual(fell, (self.x + 3, self.y, glyph, color))

        def drawn_at(flown):
            con = client.new_console()
            with mock.patch("game.render.time.monotonic", return_value=thrown + flown):
                v._draw_throws(con.rgb)
            return chr(con.rgb["ch"][MAP_X + self.x + 3, MAP_Y + self.y])

        self.assertEqual(drawn_at(0.0), glyph)
        self.assertEqual(drawn_at(BOOMERANG_TILE_SECONDS * 1.5), glyph)
        self.assertNotEqual(drawn_at(BOOMERANG_TILE_SECONDS * 2.5), glyph)  # the boomerang is on it
        self.assertNotEqual(drawn_at(BOOMERANG_TILE_SECONDS * 3.5), glyph)  # and it's gone

    def test_a_wounded_target_needs_no_stand_in(self):
        v = view_of(self.w, self.p)
        self.throw()
        deliver(self.w, v, self.p.id)
        self.assertIsNone(v.throws[-1][2])


class WalkPastTests(unittest.TestCase):
    """Merchants and the fisherman can stand in doorways, so they never block the way."""

    def walk(self, w, p, step):
        p.next_time = w.clock
        w.submit(p, step)

    def test_first_the_shop_then_past_the_merchant(self):
        w, lvl, m, step, (a,) = with_merchant()
        start, at = (a.x, a.y), (m.x, m.y)
        w.drain_outbox()
        self.walk(w, a, step)
        self.assertIn("shop", [msg["t"] for _, msg in w.drain_outbox()])
        self.assertEqual((a.x, a.y), start)  # just the shop the first time
        self.walk(w, a, step)
        self.assertNotEqual((a.x, a.y), start)
        self.assertIn(m, lvl.occupant.values())
        self.assertIn((a.x, a.y), ((at[0] + step["dx"], at[1] + step["dy"]), at))  # beyond them, or in their place

    def test_the_hint_fits_the_message_line(self):
        from game import seasons
        from game.constants import MAP_W
        for season in (None, *seasons.SEASONS):
            w, lvl, m, step, (a,) = with_merchant()
            m.name = seasons.merchant_name(season)
            w.drain_outbox()
            self.walk(w, a, step)
            text = next(msg["text"] for _, msg in w.drain_outbox() if msg["t"] == "msg" and "again" in msg["text"])
            self.assertLessEqual(len(text), MAP_W, season)

    def test_anything_in_between_and_its_the_shop_again(self):
        w, lvl, m, step, (a,) = with_merchant()
        start = (a.x, a.y)
        self.walk(w, a, step)
        w.submit(a, {"a": "sort"})
        self.walk(w, a, step)
        self.assertEqual((a.x, a.y), start)

    def test_in_a_doorway_you_trade_places(self):
        w, lvl, m, step, (a,) = with_merchant()
        ahead = (m.x + step["dx"], m.y + step["dy"])
        lvl._set_tile(*ahead, WALL)  # nowhere to land beyond them
        start, at = (a.x, a.y), (m.x, m.y)
        self.walk(w, a, step)
        self.walk(w, a, step)
        self.assertEqual((a.x, a.y), at)
        self.assertEqual((m.x, m.y), start)

    def test_past_the_fisherman_too(self):
        w = World(3)
        p, _ = FishermanTests.talk(None, w)
        f = next(n for n in w.level(p.depth).npcs if n.role == "fisherman")
        start = (p.x, p.y)
        self.walk(w, p, {"a": "move", "dx": f.x - p.x, "dy": f.y - p.y})
        self.assertNotEqual((p.x, p.y), start)


class VaultWallTests(unittest.TestCase):
    def test_a_locked_rooms_walls_wear_its_color(self):
        import numpy as np
        from game.tiles import LOCK_COLORS, WALL
        w = next(World(s) for s in range(50) if World(s).locked_rooms)
        room = sorted(w.locked_rooms.values(), key=lambda r: r.depth)[0]
        p = w.join("Alice")
        w.warp(p, room.depth)
        lvl = w.level(room.depth)
        sent = w.level_msg(room.depth)["vault"]
        self.assertEqual(tuple(sent["c"]), LOCK_COLORS[room.color])
        for x, y in sent["cells"]:
            self.assertEqual(lvl.tiles[x, y], WALL)
            self.assertTrue(lvl.vault[max(0, x - 1):x + 2, max(0, y - 1):y + 2].any())  # right up against the room
        v = view_of(w, p)
        v.bright = True
        x, y = sent["cells"][0]
        tint = v.draw()["fg"][MAP_X + x, MAP_Y + y]
        key = np.array(LOCK_COLORS[room.color], float)
        same_hue = tint @ key / (np.linalg.norm(tint) * np.linalg.norm(key))
        self.assertGreater(same_hue, 0.98)  # lit more or less, but the key's own color

    def test_other_floors_send_none(self):
        w = World(next(s for s in range(50) if not World(s).locked_rooms))
        self.assertNotIn("vault", w.level_msg(1))


class ScoreTests(unittest.TestCase):
    def test_gold_times_kills_over_moves(self):
        w, lvl, p = empty_world()
        p.gold, p.kills, p.turns = 300, 12, 400
        self.assertEqual(w.score_of(p), 300 * 12 * SCORE_SCALE // 400)
        p.kills = 0
        self.assertEqual(w.score_of(p), 0)
        p.kills, w.victory = 12, "Alice"
        self.assertEqual(w.score_of(p), 2 * (300 * 12 * SCORE_SCALE // 400))

    def test_no_moves_yet_is_not_a_crash(self):
        w, lvl, p = empty_world()
        p.gold, p.kills, p.turns = 10, 1, 0
        self.assertEqual(w.score_of(p), 10 * SCORE_SCALE)


class AltarBoostTests(unittest.TestCase):
    def test_every_blessing_adds_a_share_of_damage(self):
        sword = make_item("sword")
        rng = mock.Mock()
        rng.choice = lambda options: "accuracy"
        enhance_weapon(sword, rng)
        base = ITEMS["sword"]["damage"]
        self.assertEqual(sword.damage, tuple(math.ceil(d * (1 + ENHANCE_BOOST)) for d in base))


class ScrollingNameTests(unittest.TestCase):
    def test_short_names_stay_put(self):
        self.assertEqual(ClientView.fit("rat", 10), "rat")

    def test_long_names_scroll_to_their_end_and_back(self):
        name = "skeletal dragon of the deep"
        shown = set()
        for t in range(0, 200):
            with mock.patch("game.render.time.monotonic", return_value=t * 0.05):
                part = ClientView.fit(name, 10)
            self.assertEqual(len(part), 10)
            shown.add(part)
        self.assertIn(name[:10], shown)
        self.assertIn(name[-10:], shown)


if __name__ == "__main__":
    unittest.main()
