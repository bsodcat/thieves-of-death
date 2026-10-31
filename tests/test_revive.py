"""Revive mode, and the character a player chooses."""
import unittest

from game import protocol
from game.constants import (BONES_GLYPH, MAP_W, MAP_X, MAP_Y, REVIVE_HEALTH, REVIVE_SECONDS, TICKS_PER_SECOND,
                            TICKS_PER_TURN)
from game.entities import PLAYER_COLOR_NAMES, PLAYER_GLYPHS, make_monster
from game.items import make_item
from game.render import ClientView
from game.tiles import GLYPH
from game.world import World

REVIVE_TICKS = int(REVIVE_SECONDS * TICKS_PER_SECOND)


def setup_world(mode="Revive", players=2):
    w = World(1, mode=mode)
    lvl = w.level(1)
    for m in list(lvl.monsters):
        lvl.remove(m)
    lvl.monsters.clear()
    lvl.items.clear()
    return (w, lvl, *[w.join(n) for n in ("Alice", "Bob", "Cara")[:players]])


def down(w, p):
    w._kill(p, make_monster("rat", 800))


def view_of(w, p):
    v = ClientView()
    v.apply({"t": "welcome", "id": p.id, "name": p.name})
    for msg in (w.level_msg(p.depth), w.pack_msg(p), w.state_for(p)):
        v.apply(protocol.decode(protocol.encode(msg)))
    return v


def screen(v):
    frame = v.draw()
    return "\n".join("".join(chr(c) for c in frame["ch"][:, y]) for y in range(frame.shape[1]))


def out_of_reach(lvl, p):
    return next(c for c in lvl.floor_cells if max(abs(c[0] - p.x), abs(c[1] - p.y)) > 3 and c not in lvl.occupant)


class DownedTests(unittest.TestCase):
    def test_going_down_leaves_bones_and_keeps_gear(self):
        w, lvl, a, b = setup_world()
        a.pack, a.gold = [make_item("sword")], 30
        w._perform(a, {"a": "use", "slot": 0})
        spot = (a.x, a.y)
        down(w, a)
        self.assertFalse(a.alive)
        self.assertTrue(a.downed)
        self.assertEqual(lvl.items, {})                # nothing scattered
        self.assertEqual(a.gold, 30)
        self.assertIsNotNone(a.weapon)
        self.assertNotIn(spot, lvl.occupant)           # bones don't block anyone
        bones = next(e for e in w.state_for(b)["ents"] if e["id"] == a.id)
        self.assertEqual((bones["g"], (bones["x"], bones["y"])), (BONES_GLYPH, spot))

    def test_everyone_is_told_what_to_do(self):
        w, lvl, a, b = setup_world()
        w.drain_outbox()
        down(w, a)
        texts = [m["text"] for _, m in w.drain_outbox()]
        self.assertTrue(any("Alice is down on floor 1" in t and "3 seconds" in t and BONES_GLYPH in t for t in texts))

    def test_the_call_for_help_fits_and_skips_the_victim(self):
        w = World(1, mode="Revive")
        a, b = w.join("A" * 16), w.join("Bob")
        w.level(40)
        w.levels[40].place(a, *w.levels[40].up_front)
        w.drain_outbox()
        down(w, a)
        sent = [(pid, m["text"]) for pid, m in w.drain_outbox() if "revive" in m["text"]]
        self.assertEqual([pid for pid, _ in sent], [b.id])
        self.assertLessEqual(len(sent[0][1]), MAP_W)

    def test_explanation_box_never_covers_the_bones(self):
        w, lvl, a, b = setup_world()
        for cell in (min(lvl.floor_cells, key=lambda c: c[1]), max(lvl.floor_cells, key=lambda c: c[1])):
            w, lvl, a, b = setup_world()
            lvl.move(a, *cell)
            down(w, a)
            frame = view_of(w, a).draw()
            self.assertEqual(chr(frame["ch"][MAP_X + a.x, MAP_Y + a.y]), BONES_GLYPH)

    def test_downed_player_gets_the_explanation_and_can_see(self):
        w, lvl, a, b = setup_world()
        down(w, a)
        text = screen(view_of(w, a))
        self.assertIn("You are down!", text)
        self.assertIn("standing next to your", text)
        self.assertIn("3 seconds", text)
        self.assertIn("Killed by a rat", text)
        self.assertTrue(w.state_for(a)["visible"])
        self.assertIn(BONES_GLYPH, text)               # their own bones, still in view under the box

    def test_players_list_says_down(self):
        w, lvl, a, b = setup_world()
        down(w, a)
        self.assertIn("  down", screen(view_of(w, b)))

    def test_downed_players_cant_act(self):
        w, lvl, a, b = setup_world()
        down(w, a)
        spot = (a.x, a.y)
        w.submit(a, {"a": "move", "dx": 1, "dy": 0})
        w.advance(TICKS_PER_TURN)
        self.assertEqual((a.x, a.y), spot)

    def test_monsters_ignore_bones(self):
        w, lvl, a, b = setup_world()
        far = out_of_reach(lvl, a)
        lvl.move(b, *far)
        down(w, a)
        rat = make_monster("rat", 801)
        rat.state = "wandering"
        lvl.place(rat, *lvl.free_near(a.x, a.y))
        lvl.monsters.append(rat)
        w.advance(TICKS_PER_TURN)
        self.assertEqual(rat.state, "wandering")


class ReviveTests(unittest.TestCase):
    def test_three_seconds_next_to_them_revives(self):
        w, lvl, a, b = setup_world()
        down(w, a)
        w.advance(REVIVE_TICKS - 1)
        self.assertFalse(a.alive)
        w.advance(1)
        self.assertTrue(a.alive)
        self.assertFalse(a.downed)
        self.assertEqual(a.hp, int(a.max_hp * REVIVE_HEALTH))
        self.assertEqual(lvl.occupant[(a.x, a.y)], a)
        self.assertEqual(lvl.downed, [])
        self.assertEqual(w.state_for(a)["status"][0], "go")

    def test_revived_player_can_act_and_keeps_gear(self):
        w, lvl, a, b = setup_world()
        a.pack = [make_item("sword")]
        down(w, a)
        w.advance(REVIVE_TICKS)
        self.assertEqual(len(a.pack), 1)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (a.x + dx, a.y + dy)
            if lvl.walkable[n] and n not in lvl.occupant:
                w.submit(a, {"a": "move", "dx": dx, "dy": dy})
                break
        self.assertEqual(a.turns, 1)

    def test_revive_lands_clear_of_a_rescuer_on_the_bones(self):
        w, lvl, a, b = setup_world()
        spot = (a.x, a.y)
        down(w, a)
        lvl.move(b, *spot)                             # standing right on them counts too
        w.advance(REVIVE_TICKS)
        self.assertTrue(a.alive)
        self.assertNotEqual((a.x, a.y), (b.x, b.y))
        self.assertEqual(lvl.occupant[(b.x, b.y)], b)

    def test_walking_away_resets_progress(self):
        w, lvl, a, b = setup_world()
        down(w, a)
        w.advance(REVIVE_TICKS - 10)
        back = (b.x, b.y)
        lvl.move(b, *out_of_reach(lvl, a))
        w.advance(1)
        self.assertEqual(a.revive_ticks, 0)
        lvl.move(b, *back)
        w.advance(REVIVE_TICKS - 10)
        self.assertFalse(a.alive)                      # had to start again

    def test_no_one_nearby_means_no_progress(self):
        w, lvl, a, b = setup_world()
        lvl.move(b, *out_of_reach(lvl, a))
        down(w, a)
        w.advance(REVIVE_TICKS * 3)
        self.assertFalse(a.alive)

    def test_status_shows_progress_on_both_sides(self):
        w, lvl, a, b = setup_world()
        down(w, a)
        w.advance((REVIVE_TICKS + 1) // 2)
        self.assertEqual(w.state_for(b)["status"], ["revive", "Reviving Alice... 50%"])
        self.assertEqual(w.state_for(a)["status"], ["revive", "You are being revived... 50%"])
        self.assertIn("Reviving Alice... 50%", screen(view_of(w, b)))

    def test_downed_players_cant_revive_each_other(self):
        w, lvl, a, b, c = setup_world(players=3)
        lvl.move(c, *out_of_reach(lvl, a))
        down(w, a)
        down(w, b)
        w.advance(REVIVE_TICKS * 2)
        self.assertFalse(a.alive or b.alive)

    def test_rescuer_on_another_floor_doesnt_count(self):
        w, lvl, a, b = setup_world()
        lvl.move(a, *lvl.down_front)
        down(w, a)
        lvl.remove(b)
        lower = w.level(2)
        lower.place(b, a.x, a.y) if lower.walkable[a.x, a.y] else lower.place(b, *lower.up_front)
        w.advance(REVIVE_TICKS * 2)
        self.assertFalse(a.alive)

    def test_whole_party_down_restarts_the_run(self):
        w, lvl, a, b = setup_world()
        down(w, a)
        self.assertIsNone(w.reset_at)
        down(w, b)
        self.assertIsNotNone(w.reset_at)
        w.check_reset(w.reset_at + 0.1)
        self.assertTrue(a.alive and b.alive)
        self.assertFalse(a.downed or b.downed)
        self.assertEqual(w.run, 2)
        self.assertEqual(w.level(1).downed, [])

    def test_solo_player_gets_no_teammate_message(self):
        w, lvl, a = setup_world(players=1)
        w.drain_outbox()
        down(w, a)
        texts = [m["text"] for _, m in w.drain_outbox()]
        self.assertFalse(any("Stand next to" in t for t in texts))
        self.assertIsNotNone(w.reset_at)

    def test_leaving_while_down_and_coming_back(self):
        w, lvl, a, b = setup_world()
        lvl.move(b, *out_of_reach(lvl, a))
        down(w, a)
        spot = (a.x, a.y)
        w.leave(a)
        self.assertEqual(lvl.downed, [])
        back = w.join("Alice")
        self.assertIs(back, a)
        self.assertEqual(lvl.downed, [a])
        self.assertEqual((a.x, a.y), spot)
        self.assertIsNone(w.reset_at)

    def test_coming_back_down_with_nobody_up_restarts(self):
        w, lvl, a, b = setup_world()
        down(w, a)
        w.leave(a)
        w.leave(b)
        w.join("Alice")
        self.assertIsNotNone(w.reset_at)


class ClassicTests(unittest.TestCase):
    def test_classic_is_unchanged(self):
        w, lvl, a, b = setup_world(mode="Classic")
        a.pack = [make_item("sword")]
        w.drain_outbox()
        down(w, a)
        self.assertFalse(a.downed)
        self.assertEqual([i.kind for i in lvl.items.values()], ["sword"])
        w.advance(REVIVE_TICKS * 2)
        self.assertFalse(a.alive)
        self.assertEqual(w.state_for(a)["status"][0], "dead")
        self.assertFalse(any(e["id"] == a.id for e in w.state_for(b)["ents"]))
        self.assertTrue(any("Alice dies!" in m["text"] for _, m in w.drain_outbox()))
        text = screen(view_of(w, a))
        self.assertIn("You have died.", text)
        self.assertIn("  dead", screen(view_of(w, b)))


class CharacterTests(unittest.TestCase):
    def test_chosen_look_is_used(self):
        w = World(1)
        p = w.join("Alice", "\u2665", "Teal")
        self.assertEqual((p.glyph, p.color), ("\u2665", PLAYER_COLOR_NAMES["Teal"]))
        ent = next(e for e in w.state_for(p)["ents"] if e["id"] == p.id)
        self.assertEqual(ent["g"], "\u2665")
        self.assertEqual(w.state_for(p)["party"][0]["g"], "\u2665")

    def test_no_choice_gives_the_defaults(self):
        w = World(1)
        a, b = w.join("Alice"), w.join("Bob")
        self.assertEqual((a.glyph, b.glyph), ("@", "@"))
        self.assertNotEqual(a.color, b.color)

    def test_unknown_or_hostile_values_are_refused(self):
        w = World(1)
        for glyph, color in (("#", "Mauve"), ("r", 5), ("", None), ([1], ["Gold"]), ("too long", {"a": 1}), (None, [])):
            p = w.join(f"P{w.run}{str(glyph)[:3]}", glyph, color)
            self.assertEqual(p.glyph, "@")
            self.assertIn(p.color, PLAYER_COLOR_NAMES.values())

    def test_rejoining_can_change_look(self):
        w = World(1)
        p = w.join("Alice", "&", "Red")
        w.leave(p)
        again = w.join("Alice", "\u03a9", "Sky")
        self.assertIs(again, p)
        self.assertEqual((p.glyph, p.color), ("\u03a9", PLAYER_COLOR_NAMES["Sky"]))

    def test_shapes_cant_be_mistaken_for_the_dungeon(self):
        taken = set("rkjmgO!)[*%#+<>.") | {chr(c) for c in GLYPH.tolist()}
        self.assertFalse(taken & set(PLAYER_GLYPHS))

    def test_every_shape_exists_in_the_terminal_font(self):
        import tcod.tileset
        from game import fon
        _, _, tiles = fon.load("C:/Windows/Fonts/8514oem.fon")
        codes = {tcod.tileset.CHARMAP_CP437[i]: i for i in tiles}
        for glyph in PLAYER_GLYPHS:
            self.assertTrue(tiles[codes[ord(glyph)]].any(), glyph)

    def test_players_list_shows_each_shape(self):
        w = World(1)
        a, b = w.join("Alice", "\u2665", "Red"), w.join("Bob", "\u263b", "Sky")
        text = screen(view_of(w, a))
        self.assertIn("\u2665 Alice", text)
        self.assertIn("\u263b Bob", text)


if __name__ == "__main__":
    unittest.main()
