"""The .fon reader, checked against the Terminal font that ships with Windows."""
import os
import unittest

from game import fon

TERMINAL = "C:/Windows/Fonts/8514oem.fon"


@unittest.skipUnless(os.path.exists(TERMINAL), "needs the Windows Terminal font")
class FonTests(unittest.TestCase):
    def test_terminal_font(self):
        width, height, tiles = fon.load(TERMINAL)
        self.assertEqual((width, height), (10, 20))
        self.assertEqual(tiles[ord("@")].shape, (20, 10))
        self.assertFalse(tiles[ord(" ")].any())
        self.assertTrue(tiles[ord("@")].any())
        self.assertTrue(((tiles[ord("#")] == 0) | (tiles[ord("#")] == 255)).all())

    def test_picks_requested_size(self):
        self.assertEqual(fon.load("C:/Windows/Fonts/dosapp.fon", (12, 16))[:2], (12, 16))

    def test_rejects_other_files(self):
        with self.assertRaises(ValueError):
            fon.load(__file__)


if __name__ == "__main__":
    unittest.main()
