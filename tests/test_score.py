"""Score, the kill tally and the hardest enemy fought."""
import unittest

from game import protocol
from game.constants import MAP_H, MAP_W, MAP_X, MAP_Y, SCORE_SCALE, SIDEBAR_W, TICKS_PER_SECOND, TICKS_PER_TURN
from game.entities import MONSTERS, danger, make_monster
from game.items import make_gold
from game.render import ClientView
from game.world import World


def setup_world(mode="Classic", names=("Alice",)):
    w = World(1)
    if mode == "Classic":
        w.revive_seconds = None  # the fallen stay down
    lvl = w.level(1)
    for m in list(lvl.monsters):
        lvl.remove(m)
    lvl.monsters.clear()
    lvl.items.clear()
    return (w, lvl, *[w.join(n) for n in names])


def view_of(w, p):
    v = ClientView()
    v.apply({"t": "welcome", "id": p.id, "name": p.name})
    for msg in (w.level_msg(p.depth), w.pack_msg(p), w.state_for(p)):
        v.apply(protocol.decode(protocol.encode(msg)))
    return v


def screen(v):
    frame = v.draw()
    return "\n".join("".join(chr(c) for c in frame["ch"][:, y]) for y in range(frame.shape[1]))


def open_dir(lvl, p):
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        n = (p.x + dx, p.y + dy)
        if lvl.walkable[n] and n not in lvl.occupant:
            return dx, dy
    raise AssertionError("boxed in")


def fight(w, lvl, p, kind, hp=None, mid=900):
    """Puts a monster beside the player and has the player hit it, waiting out cooldowns."""
    dx, dy = open_dir(lvl, p)
    m = make_monster(kind, mid)
    m.state = "wandering"                      # a sneak attack always lands
    if hp is not None:
        m.hp = hp
    lvl.place(m, p.x + dx, p.y + dy)
    lvl.monsters.append(m)
    w.submit(p, {"a": "move", "dx": dx, "dy": dy})
    w.advance(TICKS_PER_TURN * 2)
    return m


def score(gold, moves, kills):
    return gold * kills * SCORE_SCALE // max(1, moves)


class ScoreTests(unittest.TestCase):
    def test_starts_at_zero(self):
        w, lvl, a = setup_world()
        self.assertEqual(w.state_for(a)["score"], 0)

    def test_gold_times_kills_divided_by_moves(self):
        w, lvl, a = setup_world()
        a.turns, a.gold, a.kills = 34, 120, 3
        self.assertEqual(w.state_for(a)["score"], score(120, 34, 3))

    def test_a_real_step_costs_score(self):
        w, lvl, a = setup_world()
        a.gold, a.kills, a.turns = 500, 2, 5
        before = w.state_for(a)["score"]
        dx, dy = open_dir(lvl, a)
        w.submit(a, {"a": "move", "dx": dx, "dy": dy})
        self.assertLess(w.state_for(a)["score"], before)

    def test_picking_up_gold_scores(self):
        w, lvl, a = setup_world()
        a.kills = 2
        lvl.items[(a.x, a.y)] = make_gold(30)
        w.submit(a, {"a": "pickup"})
        self.assertEqual(w.state_for(a)["score"], score(30, 1, 2))

    def test_dropped_gold_stops_counting(self):
        w, lvl, a = setup_world()
        a.gold, a.kills = 25, 1
        self.assertEqual(w.score_of(a), score(25, 0, 1))
        w.submit(a, {"a": "dropgold"})
        self.assertEqual(w.score_of(a), 0)

    def test_classic_keeps_the_gold_carried_at_death(self):
        w, lvl, a, b = setup_world(names=("Alice", "Bob"))
        a.turns, a.gold = 10, 50
        expected = w.score_of(a)
        w._kill(a, make_monster("rat", 800))
        self.assertEqual(a.gold, 0)            # it scattered...
        self.assertEqual(w.score_of(a), expected)  # ...but still scores
        self.assertEqual(w.state_for(a)["score_gold"], 50)

    def test_teammate_collecting_scattered_gold_earns_it_too(self):
        w, lvl, a, b = setup_world(names=("Alice", "Bob"))
        a.gold = 50
        spot = (a.x, a.y)
        w._kill(a, make_monster("rat", 800))
        lvl.move(b, *spot)
        b.kills = 1
        w.submit(b, {"a": "pickup"})
        self.assertEqual(b.gold, 50)
        self.assertEqual(w.state_for(b)["score"], score(50, 1, 1))
        self.assertEqual(w.state_for(a)["score_gold"], 50)

    def test_score_is_frozen_after_death(self):
        w, lvl, a, b = setup_world(names=("Alice", "Bob"))
        a.gold = 5
        w._kill(a, make_monster("rat", 800))
        before = w.score_of(a)
        w.advance(TICKS_PER_TURN * 20)
        self.assertEqual(w.score_of(a), before)

    def test_revived_player_scores_on_from_their_real_gold(self):
        w, lvl, a, b = setup_world("Revive", ("Alice", "Bob"))
        a.gold = 40
        w._kill(a, make_monster("rat", 800))
        self.assertEqual(w.state_for(a)["score_gold"], 40)
        w.advance(int(w.revive_seconds * TICKS_PER_SECOND) + 100)
        self.assertTrue(a.alive)
        self.assertIsNone(a.final_gold)
        a.gold = 60
        self.assertEqual(w.state_for(a)["score_gold"], 60)

    def test_new_run_clears_everything(self):
        w, lvl, a = setup_world()
        fight(w, lvl, a, "goblin", hp=1)
        a.gold = 50
        w._kill(a, make_monster("rat", 800))
        w.reset_run()
        st = w.state_for(a)
        self.assertEqual((st["score"], st["tally"], st["hardest"], st["score_gold"]), (0, {}, "", 0))


class TallyTests(unittest.TestCase):
    def test_kills_are_counted_by_monster(self):
        w, lvl, a = setup_world()
        fight(w, lvl, a, "rat", hp=1, mid=901)
        fight(w, lvl, a, "rat", hp=1, mid=902)
        fight(w, lvl, a, "kobold", hp=1, mid=903)
        self.assertEqual(w.state_for(a)["tally"], {"rat": 2, "kobold": 1})
        self.assertEqual(a.kills, 3)

    def test_each_player_has_their_own_tally(self):
        w, lvl, a, b = setup_world(names=("Alice", "Bob"))
        fight(w, lvl, a, "rat", hp=1)
        self.assertEqual(w.state_for(b)["tally"], {})


class HardestTests(unittest.TestCase):
    def test_danger_ranks_the_catalogue_sensibly(self):
        self.assertLess(danger("rat"), danger("goblin"))
        self.assertLess(danger("goblin"), danger("ogre"))
        self.assertEqual(max(MONSTERS, key=danger), "necromancer")

    def test_none_until_a_fight(self):
        w, lvl, a = setup_world()
        self.assertEqual(w.state_for(a)["hardest"], "")

    def test_hitting_something_counts_without_a_kill(self):
        w, lvl, a = setup_world()
        m = fight(w, lvl, a, "ogre")
        self.assertGreater(m.hp, 0)
        self.assertEqual(w.state_for(a)["hardest"], "ogre")

    def test_being_attacked_counts(self):
        w, lvl, a = setup_world()
        ogre = make_monster("ogre", 900)
        ogre.x, ogre.y, ogre.depth = a.x, a.y, a.depth
        w._attack(ogre, a)
        self.assertEqual(a.hardest, "ogre")

    def test_a_weaker_fight_doesnt_replace_it(self):
        w, lvl, a = setup_world()
        fight(w, lvl, a, "goblin", hp=1, mid=901)
        fight(w, lvl, a, "rat", hp=1, mid=902)
        self.assertEqual(a.hardest, "goblin")

    def test_a_stronger_fight_does(self):
        w, lvl, a = setup_world()
        fight(w, lvl, a, "rat", hp=1, mid=901)
        fight(w, lvl, a, "goblin", hp=1, mid=902)
        self.assertEqual(a.hardest, "goblin")

    def test_merely_seeing_a_monster_doesnt_count(self):
        w, lvl, a = setup_world()
        ogre = make_monster("ogre", 900)
        ogre.state = "sleeping"
        far = max(lvl.floor_cells, key=lambda c: abs(c[0] - a.x) + abs(c[1] - a.y))
        lvl.place(ogre, *far)
        lvl.monsters.append(ogre)
        w.advance(TICKS_PER_TURN * 5)
        self.assertEqual(a.hardest, "")


class DisplayTests(unittest.TestCase):
    def test_sidebar_shows_the_score_live(self):
        w, lvl, a = setup_world()
        a.turns, a.gold, a.kills = 12, 7, 2
        self.assertIn(f" Score {score(7, 12, 2)}", screen(view_of(w, a)))

    def test_haste_still_shows_without_taking_a_row(self):
        w, lvl, a = setup_world()
        a.haste_until = 10 ** 9
        self.assertIn("Time 00:00 Haste", screen(view_of(w, a)))

    def test_tally_panel(self):
        w, lvl, a = setup_world()
        fight(w, lvl, a, "rat", hp=1, mid=901)
        fight(w, lvl, a, "rat", hp=1, mid=902)
        fight(w, lvl, a, "goblin", hp=1, mid=903)
        a.gold = 4
        v = view_of(w, a)
        self.assertNotIn("Tally:", screen(v))
        v.show_tally = True
        text = screen(v)
        for part in ("Tally: t closes", f"Score {score(4, 3, 3)}", "4 gold x 3 kills / 3 moves", "Hardest enemy fought: goblin",
                     "Kills: 3", "rat", "goblin"):
            self.assertIn(part, text)

    def test_tally_with_nothing_done(self):
        w, lvl, a = setup_world()
        v = view_of(w, a)
        v.show_tally = True
        self.assertIn("Hardest enemy fought: none yet", screen(v))

    def test_tally_never_covers_the_player(self):
        w, lvl, a = setup_world()
        v = view_of(w, a)
        v.show_tally = True
        v.tally = {k: 5 for k in MONSTERS}
        for x in range(0, MAP_W, 3):
            for y in range(MAP_H):
                v.ents = [{**e, "x": x, "y": y} for e in v.ents]
                self.assertEqual(chr(v.draw()["ch"][MAP_X + x, MAP_Y + y]), "@", (x, y))

    def test_every_monster_fits_the_tally_panel(self):
        w, lvl, a = setup_world()
        v = view_of(w, a)
        v.show_tally, v.kills = True, sum(range(len(MONSTERS)))
        v.tally = {k: i + 1 for i, k in enumerate(MONSTERS)}
        text = screen(v)
        for kind in MONSTERS:
            self.assertIn(kind, text)

    def test_death_screen_shows_the_final_numbers(self):
        w, lvl, a, b = setup_world(names=("Alice", "Bob"))
        fight(w, lvl, a, "goblin", hp=1)
        a.gold = 20
        w._kill(a, make_monster("rat", 800))
        text = screen(view_of(w, a))
        self.assertIn("You have died.", text)
        self.assertIn(f"Score {score(20, 1, 1)}", text)
        self.assertIn("20 gold x 1 kills / 1 moves", text)
        self.assertIn("Kills 1   Hardest enemy fought: goblin", text)

    def test_downed_screen_shows_them_too_and_bones_stay_visible(self):
        for cell_of in (min, max):
            w, lvl, a, b = setup_world("Revive", ("Alice", "Bob"))
            lvl.move(a, *cell_of(lvl.floor_cells, key=lambda c: c[1]))
            a.gold, a.kills = 3, 2
            w._kill(a, make_monster("rat", 800))
            v = view_of(w, a)
            text = screen(v)
            self.assertIn("You are down!", text)
            self.assertIn(f"Score {score(3, 0, 2)}", text)
            self.assertEqual(chr(v.draw()["ch"][MAP_X + a.x, MAP_Y + a.y]), "%")

    def test_help_and_footer_mention_the_tally(self):
        w, lvl, a = setup_world()
        v = view_of(w, a)
        self.assertIn("t tally", screen(v))
        v.show_help = True
        self.assertIn("i or t", screen(v))

    def test_six_players_still_fit_with_the_score_row(self):
        w = World(1)
        ps = [w.join(f"Player{i}") for i in range(6)]
        ps[0].haste_until = 10 ** 9
        self.assertIn("Player5", "".join(chr(c) for c in view_of(w, ps[0]).draw()["ch"][:SIDEBAR_W].ravel(order="F")))


class ScoreboardTests(unittest.TestCase):
    def test_party_wipe_ranks_everyone(self):
        w, lvl, a, b = setup_world(names=("Alice", "Bob"))
        a.turns, b.turns = 5, 50
        b.gold, b.kills = 2, 3
        w._kill(a, make_monster("rat", 800))
        w.drain_outbox()
        w._kill(b, make_monster("rat", 801))
        texts = [m["text"] for _, m in w.drain_outbox()]
        board = [t for t in texts if "points" in t]
        self.assertEqual(board, [f"Bob: {score(2, 50, 3)} points, 3 kills", "Alice: 0 points, 0 kills"])

    def test_no_scoreboard_while_someone_is_alive(self):
        w, lvl, a, b = setup_world(names=("Alice", "Bob"))
        w._kill(a, make_monster("rat", 800))
        self.assertFalse(any("points" in m["text"] for _, m in w.drain_outbox()))


if __name__ == "__main__":
    unittest.main()
