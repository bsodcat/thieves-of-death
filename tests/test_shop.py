"""Merchants, buying, and the potion of levitation."""
import unittest

from game import protocol
from game.constants import (MAP_H, MAP_W, MAP_X, MAP_Y, MERCHANT_EVERY, MERCHANT_STOCK, PACK_SIZE,
                            STEALTH_MOVE_DRAIN, TICKS_PER_SECOND, TICKS_PER_TURN)
from game.entities import make_merchant, make_monster
from game.items import ITEMS, make_item
from game.render import FLOAT_DIM, FLOAT_BRIGHT, FLOAT_SHADOW, ClientView
from game.world import World, cheb


def setup_world(names=("Alice",)):
    w = World(1)
    lvl = w.level(1)
    for m in list(lvl.monsters):
        lvl.remove(m)
    lvl.monsters.clear()
    lvl.items.clear()
    return (w, lvl, *[w.join(n) for n in names])


def with_merchant(names=("Alice",), kinds=("dagger", "sword", "levitation")):
    """A merchant beside the first player. Returns the world, level, merchant, step to them, players."""
    w, lvl, *ps = setup_world(names)
    a = ps[0]
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        n = (a.x + dx, a.y + dy)
        if lvl.walkable[n] and n not in lvl.occupant:
            m = make_merchant(9000, "merchant")
            m.stock = {i: w._item(k) for i, k in enumerate(kinds)}
            lvl.place(m, *n)
            lvl.merchant = m
            return w, lvl, m, {"a": "move", "dx": dx, "dy": dy}, ps
    raise AssertionError("boxed in")


def view_of(w, p):
    v = ClientView()
    v.apply({"t": "welcome", "id": p.id, "name": p.name})
    for msg in (w.level_msg(p.depth), w.pack_msg(p), w.state_for(p)):
        v.apply(protocol.decode(protocol.encode(msg)))
    return v


def deliver(w, v, pid):
    for to, msg in w.drain_outbox():
        if to in (None, pid):
            v.apply(protocol.decode(protocol.encode(msg)))


def screen(v):
    frame = v.draw()
    return "\n".join("".join(chr(c) for c in frame["ch"][:, y]) for y in range(frame.shape[1]))


def said(w):
    return " ".join(m["text"] for _, m in w.drain_outbox() if m["t"] == "msg")


class SpawnTests(unittest.TestCase):
    def test_only_every_fifth_floor(self):
        for seed in range(30):
            w = World(seed)
            for depth in (1, 2, 3, 4, 6, 7, 9, 11):
                self.assertIsNone(w.level(depth).merchant, (seed, depth))

    def test_its_a_chance_not_a_certainty(self):
        found = sum(World(seed).level(MERCHANT_EVERY).merchant is not None for seed in range(100))
        self.assertTrue(40 <= found <= 80, found)

    def test_every_multiple_of_five_can_have_one(self):
        for depth in (5, 10, 15, 20, 25, 30):
            self.assertTrue(any(World(s).level(depth).merchant for s in range(12)), depth)

    def test_same_seed_same_shop(self):
        def shop(seed):
            m = next(w.level(5).merchant for w in [World(seed)])
            return m and ((m.x, m.y), [i.kind for i in m.stock.values()])
        for seed in range(10):
            self.assertEqual(shop(seed), shop(seed))

    def merchants(self, depth=5, seeds=200):
        return [m for m in (World(s).level(depth).merchant for s in range(seeds)) if m]

    def test_stands_somewhere_reachable_and_clear(self):
        for seed in range(40):
            w = World(seed)
            lvl = w.level(5)
            m = lvl.merchant
            if m:
                self.assertTrue(lvl.walkable[m.x, m.y])
                self.assertNotIn((m.x, m.y), lvl.items)
                self.assertIs(lvl.occupant[(m.x, m.y)], m)
                self.assertFalse(lvl.is_door[m.x, m.y])
                self.assertNotIn(m, lvl.monsters)

    def test_stock_is_equipment_plus_sometimes_levitation(self):
        for m in self.merchants(seeds=60):
            kinds = [i.kind for i in m.stock.values()]
            gear = [k for k in kinds if ITEMS[k]["category"] in ("weapon", "armor")]
            self.assertTrue(MERCHANT_STOCK[0] <= len(gear) <= MERCHANT_STOCK[1], kinds)
            self.assertEqual(len(gear), len(set(gear)))
            self.assertLessEqual(len(kinds), 10)
            self.assertLessEqual(set(kinds) - set(gear), {"levitation"})

    def test_levitation_is_an_occasional_stock_item(self):
        ms = self.merchants()
        share = sum(any(i.kind == "levitation" for i in m.stock.values()) for m in ms) / len(ms)
        self.assertTrue(0.15 < share < 0.45, share)

    def test_stock_suits_the_floor(self):
        for m in self.merchants(depth=25, seeds=40):
            self.assertNotIn("dagger", [i.kind for i in m.stock.values()])

    def test_hint_on_arrival(self):
        seed = next(s for s in range(30) if World(s).level(5).merchant)
        w = World(seed)
        a = w.join("Alice")
        lvl4 = w.level(4)
        w.levels[1].remove(a)
        lvl4.place(a, *lvl4.down_front)
        w.drain_outbox()
        w.submit(a, {"a": "descend"})
        self.assertEqual(a.depth, 5)
        self.assertIn("calling out", said(w))


class PriceTests(unittest.TestCase):
    def test_all_equipment_has_a_price(self):
        for kind, t in ITEMS.items():
            if t["category"] in ("weapon", "armor") and t["weight"]:  # anything else is never found or sold
                self.assertGreater(t["price"], 0, kind)

    def test_levitation_costs_the_most(self):
        self.assertEqual(max(ITEMS, key=lambda k: ITEMS[k].get("price", 0)), "levitation")

    def test_levitation_is_rare_on_the_floor(self):
        self.assertEqual(ITEMS["levitation"]["weight"], min(t["weight"] for t in ITEMS.values() if t["weight"]))
        counts = {"levitation": 0, "other": 0}
        for seed in range(60):
            for item in World(seed).level(6).items.values():
                if item.category != "gold":
                    counts["levitation" if item.kind == "levitation" else "other"] += 1
        self.assertLess(counts["levitation"], counts["other"] / 8)
        self.assertGreater(counts["levitation"], 0)

    def test_gear_prices_rise_with_quality(self):
        price = {k: t["price"] for k, t in ITEMS.items() if "price" in t}
        self.assertLess(price["dagger"], price["sword"])
        self.assertLess(price["sword"], price["mace"])
        self.assertLess(price["leather"], price["scale"])
        self.assertLess(price["scale"], price["plate"])


class ShopTests(unittest.TestCase):
    def test_walking_into_them_opens_the_shop_for_free(self):
        w, lvl, m, step, (a,) = with_merchant()
        spot = (m.x, m.y)
        w.drain_outbox()
        w.submit(a, step)
        shop = [msg for to, msg in w.outbox if msg["t"] == "shop"]
        self.assertEqual(len(shop), 1)
        self.assertEqual([i["price"] for i in shop[0]["stock"]], [40, 120, 600])
        self.assertEqual((a.turns, a.next_time), (0, 0))
        self.assertEqual((m.x, m.y), spot)     # no swapping places, no attack
        self.assertEqual(m.hp, 1)

    def test_holding_into_them_only_opens_it_once(self):
        w, lvl, m, step, (a,) = with_merchant()
        w.drain_outbox()
        w.submit(a, {**step, "a": "hold", "press": True})
        w.advance(TICKS_PER_TURN * 5)
        self.assertEqual(sum(msg["t"] == "shop" for _, msg in w.outbox), 1)
        self.assertIsNone(a.hold)

    def buy(self, w, a, stock_id):
        w.submit(a, {"a": "buy", "id": stock_id})

    def test_buying(self):
        w, lvl, m, step, (a,) = with_merchant()
        a.gold = 130
        w.drain_outbox()
        self.buy(w, a, 1)
        self.assertEqual([i.kind for i in a.pack], ["sword"])
        self.assertEqual(a.gold, 10)
        self.assertNotIn(1, m.stock)
        self.assertTrue(a.pack_dirty)
        self.assertIn("You buy a sword for 120", said(w))

    def test_too_expensive(self):
        w, lvl, m, step, (a,) = with_merchant()
        a.gold = 39
        w.drain_outbox()
        self.buy(w, a, 0)
        self.assertEqual((a.pack, a.gold, a.next_time), ([], 39, 0))
        self.assertIn(0, m.stock)
        self.assertIn("can't afford", said(w))

    def test_exact_money_works(self):
        w, lvl, m, step, (a,) = with_merchant()
        a.gold = 40
        self.buy(w, a, 0)
        self.assertEqual(a.gold, 0)

    def test_full_pack_keeps_your_money(self):
        w, lvl, m, step, (a,) = with_merchant()
        a.gold = 500
        a.pack = [make_item("dagger") for _ in range(PACK_SIZE)]
        w.drain_outbox()
        self.buy(w, a, 1)
        self.assertEqual(a.gold, 500)
        self.assertIn(1, m.stock)
        self.assertIn("pack is full", said(w))

    def test_potion_stacks_even_with_a_full_pack(self):
        w, lvl, m, step, (a,) = with_merchant()
        a.gold = 600
        a.pack = [make_item("levitation")] + [make_item("dagger") for _ in range(PACK_SIZE - 1)]
        self.buy(w, a, 2)
        self.assertEqual(a.pack[0].count, 2)

    def test_must_be_beside_them(self):
        w, lvl, m, step, (a,) = with_merchant()
        a.gold = 500
        lvl.move(a, *next(c for c in lvl.floor_cells if max(abs(c[0] - m.x), abs(c[1] - m.y)) > 3))
        self.buy(w, a, 0)
        self.assertEqual((a.pack, a.gold), ([], 500))

    def test_no_merchant_no_sale(self):
        w, lvl, a = setup_world()
        a.gold = 500
        self.buy(w, a, 0)
        self.assertEqual(a.gold, 500)

    def test_bad_ids_are_ignored(self):
        w, lvl, m, step, (a,) = with_merchant()
        a.gold = 500
        for bad in (99, -1, "0", None, 1.5, True, [0]):
            self.buy(w, a, bad)
        self.assertEqual((a.pack, a.gold), ([], 500))
        self.assertEqual(len(m.stock), 3)

    def test_two_players_cant_buy_the_same_thing(self):
        w, lvl, m, step, (a, b) = with_merchant(("Alice", "Bob"))
        lvl.move(b, *lvl.free_near(m.x, m.y))
        a.gold = b.gold = 500
        self.buy(w, a, 1)
        w.drain_outbox()
        self.buy(w, b, 1)
        self.assertEqual((len(a.pack), b.pack, b.gold), (1, [], 500))
        self.assertIn("already been sold", said(w))

    def test_everyone_at_the_shop_sees_the_new_stock(self):
        w, lvl, m, step, (a, b) = with_merchant(("Alice", "Bob"))
        lvl.move(b, *lvl.free_near(m.x, m.y))
        a.gold = 500
        w.drain_outbox()
        self.buy(w, a, 1)
        to = {pid for pid, msg in w.drain_outbox() if msg["t"] == "shop"}
        self.assertEqual(to, {a.id, b.id})

    def test_buying_lowers_score(self):
        w, lvl, m, step, (a,) = with_merchant()
        a.gold = 130
        before = w.score_of(a)
        self.buy(w, a, 1)
        self.assertLess(w.score_of(a), before)
        self.assertEqual(a.gold, 10)

    def test_bought_gear_works(self):
        w, lvl, m, step, (a,) = with_merchant()
        a.gold = 130
        self.buy(w, a, 1)
        w.advance(TICKS_PER_TURN * 2)
        w.submit(a, {"a": "use", "slot": 0})
        self.assertEqual(a.damage, ITEMS["sword"]["damage"])

    def test_monsters_leave_them_alone(self):
        w, lvl, m, step, (a,) = with_merchant()
        lvl.move(a, *next(c for c in lvl.floor_cells if max(abs(c[0] - m.x), abs(c[1] - m.y)) > 5))
        goblin = make_monster("goblin", 901)
        goblin.state = "wandering"
        lvl.place(goblin, *lvl.free_near(m.x, m.y))
        lvl.monsters.append(goblin)
        w.advance(TICKS_PER_TURN * 30)
        self.assertEqual(m.hp, 1)
        self.assertIs(lvl.occupant[(m.x, m.y)], m)

    def test_new_run_clears_them(self):
        w, lvl, m, step, (a,) = with_merchant()
        w.reset_run()
        self.assertIsNone(w.level(1).merchant)


class ShopViewTests(unittest.TestCase):
    def opened(self, gold=130):
        w, lvl, m, step, (a,) = with_merchant()
        a.gold = gold
        w.drain_outbox()
        w.submit(a, step)
        v = view_of(w, a)
        deliver(w, v, a.id)
        return w, lvl, m, a, v

    def test_panel_lists_stock_and_prices(self):
        w, lvl, m, a, v = self.opened()
        text = screen(v)
        for part in ("Merchant: 1-0 buy, Esc closes", "dagger", "sword", "potion of levitation", "40", "120", "600",
                     "float for 9s", "130 gold", "Spending lowers your score"):
            self.assertIn(part, text)

    def test_buying_updates_the_panel(self):
        w, lvl, m, a, v = self.opened()
        w.submit(a, {"a": "buy", "id": v.shop[1]["id"]})
        deliver(w, v, a.id)
        self.assertEqual(len(v.shop), 2)
        self.assertNotIn("sword", " ".join(i["name"] for i in v.shop))

    def test_sold_out(self):
        w, lvl, m, a, v = self.opened(gold=2000)
        for item in list(v.shop):
            w.advance(TICKS_PER_TURN * 2)
            w.submit(a, {"a": "buy", "id": item["id"]})
        deliver(w, v, a.id)
        self.assertEqual(v.shop, [])
        self.assertIn("Sold out.", screen(v))

    def test_walking_away_closes_it(self):
        w, lvl, m, a, v = self.opened()
        lvl.move(a, *next(c for c in lvl.floor_cells if cheb(type("P", (), {"x": c[0], "y": c[1]}), m) > 2))
        v.apply(protocol.decode(protocol.encode(w.state_for(a))))
        self.assertIsNone(v.shop)

    def test_staying_keeps_it_open(self):
        w, lvl, m, a, v = self.opened()
        v.apply(protocol.decode(protocol.encode(w.state_for(a))))
        self.assertIsNotNone(v.shop)

    def test_panel_never_covers_the_player(self):
        w, lvl, m, a, v = self.opened()
        for x in range(0, MAP_W, 3):
            for y in range(MAP_H):
                v.ents = [{**e, "x": x, "y": y} if e["id"] == a.id else e for e in v.ents]
                self.assertEqual(chr(v.draw()["ch"][MAP_X + x, MAP_Y + y]), "@", (x, y))

    def test_every_item_on_sale_fits_in_every_season(self):
        for season in (None, "halloween", "christmas"):
            w = World(1, season_fn=lambda s=season: s)
            for kind, t in ITEMS.items():
                if "price" in t:
                    item = w._item(kind)
                    v = ClientView()
                    v.shop = [{"id": 0, "name": item.label, "g": item.glyph, "c": list(item.color),
                               "info": item.info, "price": item.price}]
                    text = screen(v)
                    self.assertIn(item.label, text)
                    self.assertIn(f"{item.info}  ", text)

    def test_full_stock_fits(self):
        w, lvl, m, a, v = self.opened()
        v.shop = [dict(v.shop[0]) for _ in range(6)]
        self.assertIn("Spending lowers", screen(v))

    def test_seen_on_the_map_and_identified(self):
        w, lvl, m, a, v = self.opened()
        self.assertEqual(chr(v.draw()["ch"][MAP_X + m.x, MAP_Y + m.y]), "$")
        text = " ".join(t for t, _ in v.describe(m.x, m.y))
        self.assertIn("Merchant", text)
        self.assertIn("for sale", text)
        self.assertNotIn("Health", text)

    def test_auto_walk_treats_them_as_a_destination(self):
        w, lvl, m, a, v = self.opened()
        self.assertEqual(v.walk_step(m.x, m.y), (m.x - a.x, m.y - a.y))

    def test_sidebar_says_shop(self):
        w, lvl, m, a, v = self.opened()
        self.assertIn("shop", screen(v))


class LevitationTests(unittest.TestCase):
    def floating(self, names=("Alice",)):
        w, lvl, *ps = setup_world(names)
        a = ps[0]
        a.pack.append(make_item("levitation"))
        w.submit(a, {"a": "use", "slot": 0})
        return w, lvl, a, ps

    def attacker(self, w, lvl, p):
        m = make_monster("ogre", 900)
        m.accuracy = 100000
        lvl.place(m, *lvl.free_near(p.x, p.y))
        lvl.monsters.append(m)
        return m

    def step(self, lvl, p):
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (p.x + dx, p.y + dy)
            if lvl.walkable[n] and n not in lvl.occupant:
                return {"a": "move", "dx": dx, "dy": dy}
        raise AssertionError("boxed in")

    def test_drinking_it(self):
        w, lvl, a, _ = self.floating()
        self.assertEqual(a.pack, [])
        self.assertTrue(w.state_for(a)["levitate"])
        self.assertIn("rise off the ground", said(w))

    def test_monsters_cant_reach_you(self):
        w, lvl, a, _ = self.floating()
        m = self.attacker(w, lvl, a)
        w.drain_outbox()
        for _ in range(10):
            w._attack(m, a)
        self.assertEqual(a.hp, a.max_hp)
        self.assertIn("can't reach you", said(w))

    def test_it_ends_and_you_can_be_hit_again(self):
        w, lvl, a, _ = self.floating()
        m = self.attacker(w, lvl, a)
        w.drain_outbox()
        lvl.monsters.remove(m)
        w.advance(int(ITEMS["levitation"]["levitate"] * TICKS_PER_SECOND) + 1)
        self.assertFalse(w.state_for(a)["levitate"])
        self.assertIn("drift back down", said(w))
        w._attack(m, a)
        self.assertLess(a.hp, a.max_hp)

    def test_the_landing_message_only_comes_once(self):
        w, lvl, a, _ = self.floating()
        w.drain_outbox()
        w.advance(int(ITEMS["levitation"]["levitate"] * TICKS_PER_SECOND) + 1)
        w.advance(TICKS_PER_TURN * 5)
        self.assertEqual(said(w).count("drift back down"), 1)

    def test_you_can_still_fight(self):
        w, lvl, a, _ = self.floating()
        w.advance(TICKS_PER_TURN)
        rat = make_monster("rat", 901)
        rat.state = "wandering"
        step = self.step(lvl, a)
        lvl.place(rat, a.x + step["dx"], a.y + step["dy"])
        lvl.monsters.append(rat)
        w.submit(a, step)
        self.assertLess(rat.hp, rat.max_hp)

    def test_moving_keeps_stealth_while_floating(self):
        w, lvl, a, _ = self.floating()
        w.advance(TICKS_PER_TURN)
        a.stealth = 80
        w.submit(a, self.step(lvl, a))
        self.assertEqual(a.stealth, 80)

    def test_moving_drains_stealth_again_afterwards(self):
        w, lvl, a, _ = self.floating()
        w.advance(int(ITEMS["levitation"]["levitate"] * TICKS_PER_SECOND) + 1)
        a.stealth = 80
        w.submit(a, self.step(lvl, a))
        self.assertEqual(a.stealth, 80 - STEALTH_MOVE_DRAIN)

    def test_attacking_still_empties_stealth(self):
        w, lvl, a, _ = self.floating()
        w.advance(TICKS_PER_TURN)
        a.stealth = 80
        rat = make_monster("rat", 901)
        rat.hp = 99
        step = self.step(lvl, a)
        lvl.place(rat, a.x + step["dx"], a.y + step["dy"])
        lvl.monsters.append(rat)
        w.submit(a, step)
        self.assertEqual(a.stealth, 0)

    def test_not_wasted_or_blocked_at_full_health(self):
        w, lvl, a, _ = self.floating()
        self.assertEqual(a.hp, a.max_hp)
        self.assertTrue(w._levitating(a))

    def test_only_the_drinker_floats(self):
        w, lvl, a, (a2, b) = self.floating(("Alice", "Bob"))
        m = self.attacker(w, lvl, b)
        w._attack(m, b)
        self.assertLess(b.hp, b.max_hp)

    def test_falling_ends_it(self):
        w, lvl, a, _ = self.floating()
        w._kill(a, make_monster("rat", 800))
        self.assertEqual(a.levitate_until, 0)

    def test_new_run_ends_it(self):
        w, lvl, a, _ = self.floating()
        w.reset_run()
        self.assertFalse(w._levitating(a))

    def test_the_effect_shows_to_everyone(self):
        w, lvl, a, (a2, b) = self.floating(("Alice", "Bob"))
        for viewer in (a, b):
            v = view_of(w, viewer)
            ent = next(e for e in v.ents if e["id"] == a.id)
            self.assertTrue(ent["lev"])
            frame = v.draw()
            bg = tuple(int(c) for c in frame["bg"][MAP_X + a.x, MAP_Y + a.y])
            for value, low, high in zip(bg, FLOAT_DIM, FLOAT_BRIGHT):
                self.assertTrue(low <= value <= high, bg)
            self.assertEqual(tuple(frame["bg"][MAP_X + a.x, MAP_Y + a.y + 1]), FLOAT_SHADOW)

    def test_no_effect_otherwise(self):
        w, lvl, a = setup_world()
        ent = next(e for e in w.state_for(a)["ents"] if e["id"] == a.id)
        self.assertFalse(ent["lev"])

    def test_effect_at_the_bottom_edge_of_the_map(self):
        w, lvl, a, _ = self.floating()
        v = view_of(w, a)
        v.ents = [{**e, "y": MAP_H - 1} for e in v.ents]
        self.assertEqual(v.draw().shape[0], 100)

    def test_sidebar_and_look_mention_it(self):
        w, lvl, a, _ = self.floating()
        v = view_of(w, a)
        self.assertIn("Float", screen(v))
        self.assertIn("Levitating", " ".join(t for t, _ in v.describe(a.x, a.y)))


if __name__ == "__main__":
    unittest.main()
