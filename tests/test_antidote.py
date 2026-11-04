"""The antidote: sold by every merchant, it cures slime poison and spider venom."""
import unittest
from unittest import mock

from game.items import ITEMS, make_item
from helpers_210 import empty_world, said


class AntidoteTests(unittest.TestCase):
    def setUp(self):
        self.w, self.lvl, self.p = empty_world()
        self.p.pack = [make_item("antidote")]

    def drink(self):
        self.w.drain_outbox()
        return self.w._use(self.p, 0)

    def test_it_cures_slime_poison_and_its_slowness(self):
        self.w._slimed(self.p)
        self.assertGreater(self.p.toxin_until, self.w.clock)
        self.assertGreater(self.p.slow_until, self.w.clock)
        self.assertGreater(self.drink(), 0)
        self.assertEqual((self.p.toxin_until, self.p.slow_until), (0, 0))
        self.assertIn("The burning fades", said(self.w))
        self.assertEqual(self.p.pack, [])

    def test_it_cures_spider_venom(self):
        self.w._envenom(self.p)
        self.assertGreater(self.p.venom_until, self.w.clock)
        self.drink()
        self.assertEqual(self.p.venom_until, 0)
        self.assertEqual(self.p.pack, [])

    def test_it_keeps_when_youre_not_poisoned(self):
        self.assertEqual(self.drink(), 0)
        self.assertIn("You aren't poisoned.", said(self.w))
        self.assertEqual(len(self.p.pack), 1)

    def test_only_merchants_have_it(self):
        self.assertEqual(ITEMS["antidote"]["weight"], 0)
        self.assertGreater(ITEMS["antidote"]["price"], 0)
        self.assertEqual(make_item("antidote").info, "cures poison and venom")

    def test_every_merchant_sells_one(self):
        with mock.patch("game.world.MERCHANT_CHANCE", 1.0):
            for seed in range(1, 6):
                w, lvl, p = empty_world(seed=seed)
                lvl.merchant = None
                w._add_merchant(lvl)
                if lvl.merchant is None:
                    continue
                kinds = [i.kind for i in lvl.merchant.stock.values()]
                self.assertIn("antidote", kinds)
                self.assertIn("bomb", kinds)


if __name__ == "__main__":
    unittest.main()
