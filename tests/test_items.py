"""Items: picking up, using, equipping, dropping and the UI clock."""
import unittest

from game import protocol
from game.constants import GOLD_DROP, PACK_SIZE, TICKS_PER_SECOND, TICKS_PER_TURN
from game.entities import PLAYER_STATS, make_monster
from game.items import ITEMS, make_gold, make_item
from game.render import ClientView, format_clock
from game.world import World


def setup_world(players=1):
    """A level with no monsters or items, with players standing next to each other."""
    w = World(1)
    lvl = w.level(1)
    for m in list(lvl.monsters):
        lvl.remove(m)
    lvl.monsters.clear()
    lvl.items.clear()
    return (w, lvl, *[w.join(f"P{i}") for i in range(players)])


def step_cell(lvl, p):
    """A free floor tile next to this player, and the move that reaches it."""
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        n = (p.x + dx, p.y + dy)
        if lvl.walkable[n] and n not in lvl.occupant:
            return n, {"a": "move", "dx": dx, "dy": dy}
    raise AssertionError("boxed in")


class ItemTests(unittest.TestCase):
    def ready(self, w):
        w.advance(2 * TICKS_PER_TURN)

    def test_levels_get_items_and_gold(self):
        for seed in range(10):
            w = World(seed)
            found = list(w.level(1).items.values())
            self.assertGreaterEqual(sum(i.category == "gold" for i in found), 2)
            self.assertGreaterEqual(sum(i.category != "gold" for i in found), 3)
            self.assertTrue(all(w.level(1).walkable[pos] for pos in w.level(1).items))

    def test_walking_onto_a_potion_picks_it_up(self):
        w, lvl, a = setup_world()
        cell, step = step_cell(lvl, a)
        lvl.items[cell] = make_item("healing")
        w.submit(a, step)
        self.assertEqual([i.kind for i in a.pack], ["healing"])
        self.assertNotIn(cell, lvl.items)
        self.assertTrue(a.pack_dirty)

    def test_walking_onto_gold_picks_it_up(self):
        w, lvl, a = setup_world()
        cell, step = step_cell(lvl, a)
        lvl.items[cell] = make_gold(30)
        w.submit(a, step)
        self.assertEqual((a.gold, a.pack), (30, []))
        self.assertNotIn(cell, lvl.items)

    def test_gold_is_collected_even_with_a_full_pack(self):
        w, lvl, a = setup_world()
        a.pack = [make_item("dagger") for _ in range(PACK_SIZE)]
        cell, step = step_cell(lvl, a)
        lvl.items[cell] = make_gold(30)
        w.submit(a, step)
        self.assertEqual(a.gold, 30)

    def test_dropped_gold_can_be_walked_back_over(self):
        w, lvl, a = setup_world()
        a.gold = 30
        w.submit(a, {"a": "dropgold"})
        self.assertEqual(a.gold, 5)             # stays underfoot until you step away and back
        self.ready(w)
        (x, y), step = (a.x, a.y), step_cell(lvl, a)[1]
        w.submit(a, step)
        self.ready(w)
        w.submit(a, {"a": "move", "dx": -step["dx"], "dy": -step["dy"]})
        self.assertEqual((a.x, a.y), (x, y))
        self.assertEqual(a.gold, 30)

    def test_weapons_and_armor_wait_for_the_pickup_key(self):
        for item in (make_item("sword"), make_item("leather")):
            w, lvl, a = setup_world()
            cell, step = step_cell(lvl, a)
            lvl.items[cell] = item
            w.drain_outbox()
            w.submit(a, step)
            self.assertEqual((a.x, a.y), cell)
            self.assertEqual((a.pack, a.gold), ([], 0))
            self.assertIn(cell, lvl.items)
            self.assertIn("Press g", w.drain_outbox()[0][1]["text"])
            self.ready(w)
            w.submit(a, {"a": "pickup"})
            self.assertNotIn(cell, lvl.items)
            self.assertEqual(len(a.pack), 1)

    def test_gold_goes_to_the_purse_not_the_pack(self):
        w, lvl, a = setup_world()
        lvl.items[(a.x, a.y)] = make_gold(30)
        w.submit(a, {"a": "pickup"})
        self.assertEqual((a.gold, a.pack), (30, []))

    def test_drop_then_teammate_picks_it_up(self):
        w, lvl, a, b = setup_world(2)
        a.pack.append(make_item("sword"))
        w.submit(a, {"a": "use", "slot": 0})
        self.ready(w)
        w.submit(a, {"a": "drop", "slot": 0})
        self.assertEqual(a.pack, [])
        self.assertIsNone(a.weapon)                 # dropping unequips it
        self.assertEqual(a.damage, PLAYER_STATS["damage"])
        spot = (a.x, a.y)
        self.assertEqual(lvl.items[spot].kind, "sword")  # still there: you don't re-grab your own drop
        self.ready(w)
        away, step = step_cell(lvl, a)
        w.submit(a, step)
        self.ready(w)
        lvl.move(b, *spot)  # a teammate steps onto it
        w.submit(b, {"a": "pickup"})
        self.assertEqual([i.kind for i in b.pack], ["sword"])

    def test_pickup_key_grabs_an_item_underfoot(self):
        w, lvl, a = setup_world()
        lvl.items[(a.x, a.y)] = make_item("dagger")
        w.submit(a, {"a": "pickup"})
        self.assertEqual([i.kind for i in a.pack], ["dagger"])

    def test_full_pack_leaves_the_item(self):
        w, lvl, a = setup_world()
        a.pack = [make_item("dagger") for _ in range(PACK_SIZE)]
        lvl.items[(a.x, a.y)] = make_item("sword")
        w.drain_outbox()
        w.submit(a, {"a": "pickup"})
        self.assertEqual(len(a.pack), PACK_SIZE)
        self.assertIn((a.x, a.y), lvl.items)
        self.assertEqual(a.next_time, 0)
        self.assertIn("pack is full", w.drain_outbox()[0][1]["text"])

    def test_potions_stack_in_one_slot_even_when_full(self):
        w, lvl, a = setup_world()
        a.pack = [make_item("healing")] + [make_item("dagger") for _ in range(PACK_SIZE - 1)]
        lvl.items[(a.x, a.y)] = make_item("healing")
        w.submit(a, {"a": "pickup"})
        self.assertEqual((len(a.pack), a.pack[0].count), (PACK_SIZE, 2))
        self.assertEqual(a.pack[0].label, "potion of healing x2")

    def test_healing_potion(self):
        w, lvl, a = setup_world()
        a.pack.append(make_item("healing"))
        w.submit(a, {"a": "use", "slot": 0})   # full health: not wasted
        self.assertEqual(len(a.pack), 1)
        self.assertEqual(a.next_time, 0)
        a.hp = 5
        w.submit(a, {"a": "use", "slot": 0})
        self.assertEqual((a.hp, a.pack), (25, []))

    def test_haste_halves_cooldowns_then_wears_off(self):
        w, lvl, a = setup_world()
        a.pack.append(make_item("haste"))
        w.submit(a, {"a": "use", "slot": 0})
        self.ready(w)
        _, step = step_cell(lvl, a)
        w.submit(a, step)
        self.assertEqual(a.next_time, w.clock + TICKS_PER_TURN // 2)
        self.assertTrue(w.state_for(a)["haste"])
        w.advance(int(ITEMS["haste"]["haste"] * TICKS_PER_SECOND))
        self.assertFalse(w.state_for(a)["haste"])

    def test_weapon_and_armor_change_stats(self):
        w, lvl, a = setup_world()
        a.pack = [make_item("mace"), make_item("plate")]
        w.submit(a, {"a": "use", "slot": 0})
        self.ready(w)
        w.submit(a, {"a": "use", "slot": 1})
        self.assertEqual((a.damage, a.attack_cost), (ITEMS["mace"]["damage"], 2 * TICKS_PER_TURN))
        self.assertEqual(a.defense, PLAYER_STATS["defense"] + ITEMS["plate"]["armor"])
        self.assertGreater(a.move_cost, TICKS_PER_TURN)
        self.ready(w)
        w.submit(a, {"a": "use", "slot": 1})   # pressing again takes it off
        self.assertEqual((a.defense, a.move_cost), (PLAYER_STATS["defense"], TICKS_PER_TURN))

    def test_held_movement_doesnt_cancel_a_queued_potion(self):
        w, lvl, a = setup_world()
        a.hp = 5
        a.pack.append(make_item("healing"))
        _, step = step_cell(lvl, a)
        w.submit(a, step)                       # on cooldown now
        w.submit(a, {"a": "use", "slot": 0})
        _, step = step_cell(lvl, a)
        w.submit(a, step)                       # the held key resends
        self.assertEqual(a.pending, {"a": "use", "slot": 0})
        self.ready(w)
        self.assertEqual(a.hp, 25)

    def test_dropping_gold(self):
        w, lvl, a = setup_world()
        a.gold = GOLD_DROP + 5
        w.submit(a, {"a": "dropgold"})
        self.assertEqual(a.gold, 5)
        self.assertEqual(lvl.items[(a.x, a.y)].count, GOLD_DROP)
        self.ready(w)
        w.submit(a, {"a": "dropgold"})
        self.assertEqual(a.gold, 0)
        self.ready(w)
        w.submit(a, {"a": "dropgold"})          # empty purse: no cost
        self.assertEqual(len(lvl.items), 2)

    def test_bad_slots_are_ignored(self):
        w, lvl, a = setup_world()
        for slot in (-1, PACK_SIZE, "1", None, True, 1.5):
            w.submit(a, {"a": "use", "slot": slot})
            w.submit(a, {"a": "drop", "slot": slot})
        w.submit(a, {"a": "use", "slot": 3})    # valid slot, nothing in it
        self.assertEqual(a.next_time, 0)

    def test_fallen_players_drop_everything(self):
        w, lvl, a, b = setup_world(2)
        lvl.items.clear()
        a.pack, a.gold = [make_item("sword"), make_item("leather")], 40
        w._perform(a, {"a": "use", "slot": 0})
        w.revive_seconds = None  # the fallen stay down, as on Hard
        spot = (a.x, a.y)
        w._kill(a, make_monster("rat", 800))
        self.assertEqual((a.pack, a.gold, a.weapon), ([], 0, None))
        self.assertEqual(sorted(i.kind for i in lvl.items.values()), ["gold", "leather", "sword"])
        self.assertIn(spot, lvl.items)

    def test_new_run_clears_everything(self):
        w, lvl, a = setup_world()
        a.pack, a.gold = [make_item("sword")], 40
        w.advance(1000)
        w.reset_run()
        self.assertEqual((a.pack, a.gold), ([], 0))
        self.assertEqual(w.state_for(a)["time"], 0)


class ClientTests(unittest.TestCase):
    def test_clock_format(self):
        self.assertEqual(format_clock(0), "00:00")
        self.assertEqual(format_clock(222.9), "03:42")
        self.assertEqual(format_clock(3725), "1:02:05")

    def test_state_reports_run_time(self):
        w, lvl, a = setup_world()
        w.advance(int(TICKS_PER_SECOND * 10))
        self.assertAlmostEqual(w.state_for(a)["time"], 10, places=1)

    def view_for(self, w, a):
        view = ClientView()
        view.apply({"t": "welcome", "id": a.id, "name": a.name})
        for msg in (w.level_msg(a.depth), w.pack_msg(a), w.state_for(a)):
            view.apply(protocol.decode(protocol.encode(msg)))
        return view

    def test_pack_panel_and_clock_draw(self):
        w, lvl, a = setup_world()
        a.pack, a.gold = [make_item("sword"), make_item("healing")], 12
        w._perform(a, {"a": "use", "slot": 0})
        view = self.view_for(w, a)
        view.show_pack = True
        frame = view.draw()
        text = "\n".join("".join(chr(c) for c in frame["ch"][:, y]) for y in range(frame.shape[1]))
        for expected in ("Time 00:00", "Gold 12", "Dmg 5-9", "sword", "dmg 5-9, noise 15 (on)", "potion of healing", "12 gold"):
            self.assertIn(expected, text)

    def test_items_are_drawn_and_remembered(self):
        w, lvl, a = setup_world()
        cell, _ = step_cell(lvl, a)
        lvl.items[cell] = make_item("sword")
        view = self.view_for(w, a)
        self.assertIn(cell, view.item_memory[1])
        view.visible[cell] = False               # out of sight: still remembered
        view.apply(protocol.decode(protocol.encode({**w.state_for(a), "items": [],
                                                    "visible": protocol.pack_bool(view.visible)})))
        self.assertIn(cell, view.item_memory[1])
        del lvl.items[cell]                      # seen again and gone: forgotten
        view.apply(protocol.decode(protocol.encode(w.state_for(a))))
        self.assertNotIn(cell, view.item_memory[1])


if __name__ == "__main__":
    unittest.main()
