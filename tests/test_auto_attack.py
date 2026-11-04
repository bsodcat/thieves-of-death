"""Auto attack: hitting back at monsters beside you, and firing a readied bow, boomerang, wand or staff."""
import unittest

from game import settings
from game.constants import TICKS_PER_TURN
from game.items import make_item, make_staff, make_wand
from helpers_210 import add, empty_world, logged, open_spot, put, said


class AutoAttackTests(unittest.TestCase):
    def setUp(self):
        self.w, self.lvl, self.p = empty_world()
        self.x, self.y = open_spot(self.lvl, 6)
        put(self.lvl, self.p, self.x, self.y)
        self.p.auto_attack = True
        self.p.god = True   # nothing here should be about dying

    def tick(self, turns=1):
        for _ in range(turns):
            self.w.advance(TICKS_PER_TURN)

    def monster(self, kind="rat", dx=1, dy=0, **kw):
        return add(self.w, self.lvl, kind, self.x + dx, self.y + dy, target=self.p, **kw)

    def ready(self, item):
        self.p.pack.append(item)
        self.w._use(self.p, self.p.pack.index(item))
        self.p.next_time = self.w.clock
        return item

    def test_it_hits_back_at_whats_beside_you(self):
        rat = self.monster(dx=1)
        self.tick(3)
        self.assertRegex(logged(self.w), r"Alice\S* (hit|missed|killed)")
        self.assertTrue(rat.hp < rat.max_hp or rat not in self.lvl.monsters or "missed" in logged(self.w))

    def test_off_it_does_nothing(self):
        self.p.auto_attack = False
        rat = self.monster(dx=1)
        self.tick(3)
        self.assertEqual(rat.hp, rat.max_hp)
        self.assertEqual((self.p.x, self.p.y), (self.x, self.y))

    def test_diagonals_count(self):
        rat = self.monster(dx=1, dy=1)
        self.assertEqual(self.w._auto_choice(self.p), ("melee", rat))

    def test_it_leaves_sleepers_and_wanderers_alone(self):
        self.monster(dx=1, state="sleeping")
        self.monster(dx=-1, state="wandering")
        self.assertIsNone(self.w._auto_choice(self.p))

    def test_and_a_monkey_that_hasnt_been_provoked(self):
        monkey = self.monster("monkey", dx=1)
        self.assertIsNone(self.w._auto_choice(self.p))
        monkey.provoked = True
        self.assertEqual(self.w._auto_choice(self.p), ("melee", monkey))

    def test_two_tiles_away_is_too_far_for_melee(self):
        self.monster(dx=2)
        self.assertIsNone(self.w._auto_choice(self.p))

    def test_it_waits_while_youre_walking(self):
        self.monster(dx=1)
        self.p.hold = (0, -1)
        self.w._tick_auto_attacks()
        self.assertIsNone(self.p.pending)

    def test_a_key_press_replaces_it(self):
        self.monster(dx=1)
        self.p.next_time = self.w.clock + 10   # still busy, so the queued attack hasn't run
        self.p.pending = {"a": "auto"}
        self.w.submit(self.p, {"a": "move", "dx": 0, "dy": -1})
        self.assertNotEqual(self.p.pending, {"a": "auto"})

    def test_using_a_bow_readies_it_instead_of_firing(self):
        bow = self.ready(make_item("bow"))
        self.assertIs(self.p.ranged, bow)
        self.assertIn("You ready the bow", said(self.w))
        self.w._use(self.p, self.p.pack.index(bow))
        self.assertIsNone(self.p.ranged)

    def test_without_auto_attack_using_a_bow_still_fires(self):
        self.p.auto_attack = False
        self.p.pack.append(make_item("bow"))
        self.w._use(self.p, 0)
        self.assertIsNone(self.p.ranged)
        self.assertIn("You have no arrows", said(self.w))   # it tried to fire

    def test_a_readied_bow_fires_at_what_is_fighting_you(self):
        self.ready(make_item("bow"))
        arrows = make_item("arrows")
        arrows.count = 5
        self.p.pack.append(arrows)
        rat = self.monster(dx=4)
        self.monster(dx=-4, state="sleeping")
        self.tick(2)
        self.assertLess(arrows.count, 5)
        self.assertRegex(logged(self.w), r"shot rat#\d+")

    def test_no_arrows_no_shot_and_no_nagging(self):
        self.ready(make_item("bow"))
        self.monster(dx=4)
        said(self.w)
        self.assertIsNone(self.w._auto_choice(self.p))
        self.tick(2)
        self.assertNotIn("no arrows", said(self.w))

    def test_a_boomerang_waits_to_come_back(self):
        boomerang = self.ready(make_item("boomerang"))
        self.monster("ogre", dx=4)
        self.assertEqual(self.w._auto_choice(self.p)[0], "ranged")
        boomerang.back_at = self.w.clock + 100
        self.assertIsNone(self.w._auto_choice(self.p))

    def test_beside_you_it_uses_melee_not_the_bow(self):
        self.ready(make_item("bow"))
        self.p.pack.append(make_item("arrows"))
        rat = self.monster(dx=1)
        self.assertEqual(self.w._auto_choice(self.p), ("melee", rat))

    def test_out_of_reach_nothing(self):
        boomerang = self.ready(make_item("boomerang"))
        boomerang.reach = 3
        self.monster(dx=4)
        self.assertIsNone(self.w._auto_choice(self.p))
        boomerang.reach = 4
        self.assertEqual(self.w._auto_choice(self.p)[0], "ranged")

    def test_a_wand_of_fire(self):
        wand = self.ready(make_wand())
        self.monster("ogre", dx=3)
        charges = wand.charges
        self.tick(2)
        self.assertLess(wand.charges, charges)
        self.assertRegex(logged(self.w), r"zapped ogre#\d+ with wand of fire")

    def test_a_staff_of_lightning(self):
        staff = self.ready(make_staff())
        self.assertIs(self.p.ranged, staff)
        self.monster("ogre", dx=3)
        self.tick(2)
        self.assertRegex(logged(self.w), r"zapped ogre#\d+ with staff of lightning")

    def test_frost_doesnt_freeze_a_frozen_monster_again(self):
        wand = self.ready(make_item("frost_wand"))
        rat = self.monster(dx=3)
        rat.frozen_until = self.w.clock + 1000
        self.assertIsNone(self.w._auto_choice(self.p))

    def test_a_used_up_wand_is_no_longer_readied(self):
        wand = self.ready(make_wand())
        wand.charges = 1
        self.monster("ogre", dx=3)
        self.tick(2)
        self.assertNotIn(wand, self.p.pack)
        self.assertIsNone(self.p.ranged)

    def test_dropping_it_puts_it_away(self):
        bow = self.ready(make_item("bow"))
        self.w._drop(self.p, self.lvl, self.p.pack.index(bow))
        self.assertIsNone(self.p.ranged)

    def test_a_monkey_wont_steal_a_readied_weapon(self):
        bow = self.ready(make_item("bow"))
        monkey = self.monster("monkey", dx=1)
        self.p.auto_attack = False   # let it get its hands in
        self.w._monster_turn(monkey, self.lvl)
        self.assertIn(bow, self.p.pack)


class AutoAttackSettingTests(unittest.TestCase):
    def test_off_by_default(self):
        self.assertEqual(settings.DEFAULTS["auto_attack"], "Off")

    def test_the_options_screen_and_the_hello_carry_it(self):
        from togetherogue import App
        app = App.__new__(App)
        app.config = dict(settings.DEFAULTS, auto_attack="On")
        self.assertEqual(app.look()["auto"], "On")


if __name__ == "__main__":
    unittest.main()
