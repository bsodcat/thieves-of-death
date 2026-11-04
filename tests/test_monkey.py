"""The monkey: a thief that leaves you be unless you attack it."""
import unittest
from unittest import mock

from game.constants import MONKEY_FLEE, TICKS_PER_TURN
from game.items import make_item
from game.world import cheb
from helpers_210 import add, empty_world, logged, open_spot, put, said


class MonkeyTests(unittest.TestCase):
    def setUp(self):
        self.w, self.lvl, self.p = empty_world()
        self.x, self.y = open_spot(self.lvl, 5)
        put(self.lvl, self.p, self.x, self.y)
        self.p.pack, self.p.gold = [], 0
        self.p.weapon = self.p.armor = self.p.cloak = None

    def monkey(self, dx=1):
        return add(self.w, self.lvl, "monkey", self.x + dx, self.y, target=self.p)

    def turn(self, m, roll=None):
        if roll is None:
            return self.w._monster_turn(m, self.lvl)
        with mock.patch.object(self.w.rng, "random", return_value=roll):
            return self.w._monster_turn(m, self.lvl)

    def give(self, kind, count=1):
        item = make_item(kind)
        item.count = count
        self.p.pack.append(item)
        return item

    def test_it_comes_to_you_without_hurting_you(self):
        m = self.monkey(3)
        self.turn(m)
        self.assertEqual(cheb(m, self.p), 2)
        self.p.gold = 100
        hp = self.p.hp
        for _ in range(5):
            self.turn(m)
        self.assertEqual(self.p.hp, hp)
        self.assertNotRegex(logged(self.w), r"monkey#\d+ (hit|missed)")

    def test_it_steals_gold(self):
        self.p.gold = 100
        m = self.monkey()
        self.turn(m)
        self.assertTrue(15 <= m.stolen_gold <= 25)
        self.assertEqual(self.p.gold, 100 - m.stolen_gold)
        self.assertIn("of your gold", said(self.w))

    def test_it_takes_what_little_gold_there_is(self):
        self.p.gold = 4
        m = self.monkey()
        self.turn(m)
        self.assertEqual((m.stolen_gold, self.p.gold), (4, 0))

    def test_it_steals_one_item_from_a_stack(self):
        arrows = self.give("arrows", 10)
        m = self.monkey()
        self.turn(m)
        self.assertEqual(arrows.count, 9)
        self.assertEqual(m.stolen.kind, "arrows")
        self.assertIn("snatches your arrow", said(self.w))

    def test_never_what_youre_wearing_a_key_or_the_amulet(self):
        sword = self.give("sword")
        self.p.weapon = sword
        self.p.pack.append(make_item("dagger"))
        m = self.monkey()
        self.turn(m)
        self.assertIs(self.p.weapon, sword)
        self.assertIn(sword, self.p.pack)
        self.assertEqual(m.stolen.kind, "dagger")

    def test_nothing_to_take(self):
        m = self.monkey()
        self.turn(m)
        self.assertTrue(m.robbed)
        self.assertIsNone(m.stolen)
        self.assertIn("finds nothing", said(self.w))

    def test_it_robs_once_then_runs(self):
        self.p.gold = 100
        m = self.monkey()
        self.turn(m)
        gold = self.p.gold
        self.turn(m)
        self.assertEqual(cheb(m, self.p), 2)       # running
        for _ in range(10):
            self.turn(m)
        self.assertEqual(self.p.gold, gold)        # just the once
        self.assertGreater(cheb(m, self.p), 5)

    def test_more_than_thirty_tiles_away_it_stops_running(self):
        m = self.monkey()
        m.robbed = True
        spot = next((x, y) for x in range(self.lvl.tiles.shape[0]) for y in range(self.lvl.tiles.shape[1])
                    if self.lvl.walkable[x, y] and (x, y) not in self.lvl.occupant
                    and max(abs(x - self.x), abs(y - self.y)) > MONKEY_FLEE)
        put(self.lvl, m, *spot)
        self.assertEqual(self.w._monkey(m, self.lvl, self.p), TICKS_PER_TURN)   # sits, even with you in sight
        self.assertEqual((m.x, m.y), spot)

    def test_attacked_it_fights_back(self):
        m = self.monkey()
        self.p.gold = 100
        self.w._attack(self.p, m)
        self.assertTrue(m.provoked)
        self.turn(m)
        self.assertEqual(m.stolen_gold, 0)         # fought instead of stealing
        self.assertRegex(logged(self.w), r"monkey#\d+ (hit|missed) Alice")

    def test_any_hurt_angers_it(self):
        m = self.monkey()
        m.hp -= 1
        self.turn(m)
        self.assertTrue(m.provoked)

    def test_badly_hurt_it_may_flee(self):
        m = self.monkey()
        m.provoked, m.hp = True, 4    # under 40% of 12
        self.turn(m, roll=0.5)        # under 0.66
        self.assertTrue(m.fleeing)
        self.assertEqual(cheb(m, self.p), 2)
        self.assertIn("lost its nerve", logged(self.w))

    def test_or_keep_fighting_and_it_rolls_only_once(self):
        m = self.monkey()
        m.provoked, m.hp = True, 4
        self.turn(m, roll=0.9)
        self.assertFalse(m.fleeing)
        self.assertEqual(cheb(m, self.p), 1)
        self.turn(m, roll=0.1)
        self.assertFalse(m.fleeing)

    def test_at_forty_percent_it_doesnt_roll(self):
        m = self.monkey()
        m.provoked, m.hp = True, 5    # 42%
        self.turn(m, roll=0.1)
        self.assertFalse(m.fleeing)

    def test_killed_it_drops_what_it_stole(self):
        self.p.gold = 100
        potion = self.give("teleportation")
        m = self.monkey()
        with mock.patch.object(self.w.rng, "choice", side_effect=lambda seq: seq[0]):
            self.turn(m, roll=0.9)   # takes the potion, and won't drink it
        self.assertIs(m.stolen, potion)
        self.assertFalse(m.drink_next)
        self.w._kill(m, self.p)
        dropped = sorted(i.kind for i in self.lvl.items.values())
        self.assertEqual(dropped, ["gold", "hook", "teleportation"])
        self.assertIn("drops a fisherman's hook", said(self.w))

    def test_killed_it_drops_its_own_gold_and_what_it_stole_together(self):
        self.p.gold = 100
        m = self.monkey()
        self.turn(m)                   # nothing but gold to take
        stolen = m.stolen_gold
        self.w._kill(m, self.p)
        gold = [i.count for i in self.lvl.items.values() if i.kind == "gold"]
        self.assertEqual(len(gold), 1)
        self.assertTrue(stolen + 10 <= gold[0] <= stolen + 30)

    def test_even_an_honest_monkey_has_a_hook_and_some_gold(self):
        m = self.monkey(3)
        self.w._kill(m, self.p)
        self.assertEqual(sorted(i.kind for i in self.lvl.items.values()), ["gold", "hook"])

    def test_when_it_flees_it_drops_what_it_stole(self):
        self.p.gold = 100
        self.give("dagger")
        m = self.monkey()
        with mock.patch.object(self.w.rng, "choice", side_effect=lambda seq: seq[0]):
            self.turn(m)               # takes the dagger
        self.assertEqual(m.stolen.kind, "dagger")
        m.provoked, m.hp = True, 3
        where = (m.x, m.y)
        self.turn(m, roll=0.1)         # loses its nerve
        self.assertTrue(m.fleeing)
        self.assertIsNone(m.stolen)
        self.assertEqual([i.kind for i in self.lvl.items.values()], ["dagger"])
        self.assertLessEqual(cheb(m, self.p), 2)
        self.assertNotEqual((m.x, m.y), where)
        self.assertIn("drops dagger", said(self.w))


class MonkeyPotionTests(unittest.TestCase):
    def setUp(self):
        self.w, self.lvl, self.p = empty_world()
        self.x, self.y = open_spot(self.lvl, 5)
        put(self.lvl, self.p, self.x, self.y)
        self.p.pack, self.p.gold = [], 0
        self.p.weapon = self.p.armor = self.p.cloak = None

    def rob(self, kind, roll=0.1):
        """A monkey steals a potion of this kind, then has its next turn."""
        self.p.pack.append(make_item(kind))
        m = add(self.w, self.lvl, "monkey", self.x + 1, self.y, target=self.p)
        with mock.patch.object(self.w.rng, "random", return_value=roll):
            self.w._monster_turn(m, self.lvl)
        return m

    def test_half_the_time_it_drinks_it(self):
        self.assertTrue(self.rob("haste", roll=0.4).drink_next)
        self.w, self.lvl, self.p = empty_world()
        self.x, self.y = open_spot(self.lvl, 5)
        put(self.lvl, self.p, self.x, self.y)
        self.p.pack, self.p.gold = [], 0
        self.p.weapon = self.p.armor = self.p.cloak = None
        self.assertFalse(self.rob("haste", roll=0.6).drink_next)

    def test_healing(self):
        m = self.rob("healing")
        m.hp = 3
        self.w._monster_turn(m, self.lvl)
        self.assertEqual(m.hp, m.max_hp)
        self.assertIsNone(m.stolen)
        self.assertIn("drinks the potion of healing", said(self.w))

    def test_haste_halves_its_turns(self):
        m = self.rob("haste")
        self.w._monster_turn(m, self.lvl)
        self.assertGreater(m.haste_until, self.w.clock)
        slow = add(self.w, self.lvl, "monkey", self.x - 2, self.y, state="wandering")
        with mock.patch.object(self.w, "_monster_turn", return_value=100):
            self.w._monster_act(m)
            self.w._monster_act(slow)
        self.assertEqual(m.next_time - self.w.clock, (slow.next_time - self.w.clock) // 2)

    def test_levitation_puts_it_out_of_reach(self):
        m = self.rob("levitation")
        self.w._monster_turn(m, self.lvl)
        self.assertTrue(self.w._levitating(m))
        hp = m.hp
        put(self.lvl, m, self.x + 1, self.y)
        self.w._attack(self.p, m)
        self.assertEqual(m.hp, hp)
        self.assertIn("can't reach the monkey", said(self.w))

    def test_teleportation_takes_it_to_another_floor(self):
        m = self.rob("teleportation")
        self.w._monster_turn(m, self.lvl)
        self.assertNotEqual(m.depth, self.p.depth)
        self.assertNotIn(m, self.lvl.monsters)
        other = self.w.levels[m.depth]
        self.assertIn(m, other.monsters)
        self.assertIs(other.occupant[(m.x, m.y)], m)
        self.assertEqual(m.state, "wandering")
        self.assertIn("vanishes", said(self.w))

    def water_between(self):
        """A moat of deep water two tiles wide between the player and the monkey, east of them."""
        from game.tiles import DEEP
        for x in (self.x + 2, self.x + 3):
            for y in range(self.y - 5, self.y + 6):
                self.lvl._set_tile(x, y, DEEP)
        self.lvl._paths.clear()

    def test_water_walking_crosses_water(self):
        m = self.rob("waterwalking")
        self.w._monster_turn(m, self.lvl)
        self.assertGreater(m.waterwalk_until, self.w.clock)
        self.assertIn("can walk on water", said(self.w))
        self.water_between()
        for _ in range(3):
            self.w._monster_turn(m, self.lvl)   # running from you, straight over the water
        self.assertGreater(m.x, self.x + 3)

    def test_without_it_the_water_stops_it(self):
        from game.tiles import DEEP
        m = add(self.w, self.lvl, "monkey", self.x + 1, self.y, target=self.p)
        m.robbed = True
        self.water_between()
        for _ in range(3):
            self.w._monster_turn(m, self.lvl)
        self.assertNotEqual(self.lvl.tiles[m.x, m.y], DEEP)
        self.assertLessEqual(m.x, self.x + 1)

    def test_lava_walking(self):
        from game.tiles import DEEP, LAVA
        m = self.rob("lavawalking")
        self.w._monster_turn(m, self.lvl)
        self.assertGreater(m.lavawalk_until, self.w.clock)
        self.lvl._set_tile(self.x + 3, self.y, LAVA)
        self.lvl._set_tile(self.x + 3, self.y + 1, DEEP)
        self.assertTrue(self.w._ground(m, self.lvl)[self.lvl.tiles == LAVA].all())
        self.assertFalse(self.w._ground(m, self.lvl)[self.lvl.tiles == DEEP].any())

    def test_when_it_wears_off_over_water_it_gets_back_to_land(self):
        from game.tiles import DEEP
        m = self.rob("waterwalking")
        self.w._monster_turn(m, self.lvl)
        self.water_between()
        put(self.lvl, m, self.x + 2, self.y)
        m.waterwalk_until = self.w.clock - 1
        self.w._monster_act(m)
        self.assertNotEqual(self.lvl.tiles[m.x, m.y], DEEP)
        self.assertIn("solid ground", said(self.w))

    def test_a_levitating_monkey_shows_as_floating(self):
        m = self.rob("levitation")
        self.w._monster_turn(m, self.lvl)
        ents = {e["id"]: e for e in self.w.state_for(self.p)["ents"]}
        if m.id in ents:
            self.assertTrue(ents[m.id]["lev"])
        self.assertTrue(self.w._ground(m, self.lvl)[self.lvl.hover].all())

    def test_strength_makes_it_hit_harder(self):
        m = self.rob("strength")
        low, high = m.damage
        self.w._monster_turn(m, self.lvl)
        self.assertEqual(m.damage, (low + 2, high + 2))
        self.assertIn("looks stronger", said(self.w))


class HookTests(unittest.TestCase):
    """The fisherman's hooks, which monkeys drop, traded back to him for potions of strength."""

    def setUp(self):
        self.w, self.lvl, self.p = empty_world()
        self.x, self.y = open_spot(self.lvl, 5)
        put(self.lvl, self.p, self.x, self.y)
        self.p.pack = []
        self.fisher = self.w._add_npc(self.lvl, "fisherman", (self.x + 1, self.y))

    def hooks(self, count):
        hook = make_item("hook")
        hook.count = count
        self.p.pack.append(hook)

    def test_he_thanks_you_and_gives_strength(self):
        self.hooks(1)
        self.w._meet(self.p, self.fisher, self.lvl)
        self.assertEqual([i.kind for i in self.p.pack], ["strength"])
        text = said(self.w)
        self.assertIn("My hook!", text)
        self.assertIn("Thank you", text)
        self.assertEqual(self.fisher.talks, 0)   # no key news this time

    def test_one_potion_a_hook(self):
        self.hooks(3)
        self.w._meet(self.p, self.fisher, self.lvl)
        self.assertEqual([(i.kind, i.count) for i in self.p.pack], [("strength", 3)])
        self.assertIn("All 3 of them", said(self.w))

    def test_with_no_hook_he_talks_as_usual(self):
        self.w._meet(self.p, self.fisher, self.lvl)
        self.assertEqual(self.fisher.talks, 1)
        self.assertEqual(self.p.pack, [])

    def test_a_full_pack_still_has_room_where_the_hooks_were(self):
        from game.constants import PACK_SIZE
        self.p.pack = [make_item("dagger") for _ in range(PACK_SIZE - 1)]
        self.hooks(2)
        self.w._meet(self.p, self.fisher, self.lvl)
        self.assertEqual([(i.kind, i.count) for i in self.p.pack if i.kind == "strength"], [("strength", 2)])
        self.assertEqual(len(self.p.pack), PACK_SIZE)
        self.assertEqual(self.lvl.items, {})

    def test_hooks_stack_and_are_picked_up_by_walking_over(self):
        from game.items import AUTO_PICKUP
        self.assertTrue(make_item("hook").stacks)
        self.assertIn("hook", AUTO_PICKUP)
        self.assertFalse(make_item("hook").sellable)

    def test_using_one_just_reminds_you_whose_it_is(self):
        self.hooks(1)
        self.assertEqual(self.w._use(self.p, 0), 0)
        self.assertEqual(self.p.pack[0].kind, "hook")
        self.assertIn("fisherman", said(self.w))

    def test_strength_adds_damage_for_the_run(self):
        from game.entities import apply_gear, reset_player
        self.p.pack.append(make_item("strength"))
        low, high = self.p.damage
        self.w._use(self.p, 0)
        self.assertEqual(self.p.damage, (low + 2, high + 2))
        self.p.weapon = make_item("sword")
        apply_gear(self.p)
        self.assertEqual(self.p.damage, (5 + 2, 9 + 2))   # on top of a weapon too
        self.assertIn("You feel stronger", said(self.w))
        reset_player(self.p)
        self.p.weapon = None
        apply_gear(self.p)
        self.assertEqual(self.p.damage, (low, high))      # a new run starts over

    def test_strength_is_never_found_lying_about(self):
        from game.world import World
        for seed in range(4):
            w = World(seed)
            for depth in range(1, 12):
                kinds = {i.kind for i in w.level(depth).items.values()}
                self.assertFalse(kinds & {"strength", "hook"}, (seed, depth))

    def test_a_monkey_drinking_strength_hits_harder(self):
        self.p.pack.append(make_item("strength"))
        m = add(self.w, self.lvl, "monkey", self.x - 1, self.y, target=self.p)
        low, high = m.damage
        with mock.patch.object(self.w.rng, "random", return_value=0.1):
            self.w._monster_turn(m, self.lvl)
        self.assertTrue(m.drink_next)
        self.w._monster_turn(m, self.lvl)
        self.assertEqual(m.damage, (low + 2, high + 2))


if __name__ == "__main__":
    unittest.main()
