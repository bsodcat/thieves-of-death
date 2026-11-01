"""Cult altars, enhanced weapons, and the potion of teleportation's jump between floors."""
import random
import unittest
from unittest import mock

import numpy as np
import tcod.event

import client
from game import commands
from game.constants import CULT_FIRST, LAST_FLOOR, SCREEN_H, TICKS_PER_TURN
from game.entities import make_monster
from game.items import enhance_weapon, make_item
from game.render import ClientView
from game.tiles import ALTAR, ALTAR_SPENT, GLYPH, NAMES
from game.world import World

QUESTION = "Would you like to enhance your weapon?"


def rows_of(frame):
    return "\n".join("".join(chr(c) for c in frame["ch"][:, y]) for y in range(SCREEN_H))


def view_of(w, p):
    v = ClientView()
    v.apply({"t": "welcome", "id": p.id, "name": p.name})
    v.apply(w.level_msg(p.depth))
    v.apply(w.pack_msg(p))
    v.apply(w.state_for(p))
    return v


def cult_floor():
    for seed in range(300):
        w = World(seed)
        for depth in range(CULT_FIRST, CULT_FIRST + 30):
            lvl = w.level(depth)
            spots = np.argwhere(lvl.tiles == ALTAR)
            if len(spots):
                return w, lvl, (int(spots[0][0]), int(spots[0][1]))
    raise AssertionError("no altar")


def at_altar(armed=True):
    """A player beside an altar with its guards gone."""
    w, lvl, altar = cult_floor()
    p = w.join("A")
    w.levels[p.depth].remove(p)
    for m in list(lvl.monsters):
        lvl.remove(m)
    lvl.monsters.clear()
    x, y = altar
    lvl.place(p, x - 1, y)
    if armed:
        sword = make_item("sword")
        p.pack.append(sword)
        w._use(p, 0)
    w.drain_outbox()
    return w, lvl, p, altar


def bump(w, p):
    w.advance(300)
    w.submit(p, {"a": "move", "dx": 1, "dy": 0})
    return [m for _, m in w.drain_outbox()]


def accept(w, p, altar):
    w.advance(300)
    w.submit(p, {"a": "enhance", "x": altar[0], "y": altar[1]})


class AltarPlacementTests(unittest.TestCase):
    def test_every_cult_has_one(self):
        for seed in range(20):
            w = World(seed)
            for depth in range(CULT_FIRST, CULT_FIRST + 20):
                lvl = w.level(depth)
                cult = any(m.kind == "cult_leader" for m in lvl.monsters)
                self.assertEqual(cult, bool((lvl.tiles == ALTAR).any()), (seed, depth))

    def test_only_where_there_are_cultists(self):
        lvl = World(1).level(3)
        self.assertFalse((lvl.tiles == ALTAR).any())

    def test_they_surround_it(self):
        w, lvl, altar = cult_floor()
        cult = [m for m in lvl.monsters if m.kind.startswith("cult")]
        beside = [m for m in cult if max(abs(m.x - altar[0]), abs(m.y - altar[1])) == 1]
        self.assertGreaterEqual(len(beside), 6)
        sides = {(np.sign(m.x - altar[0]), np.sign(m.y - altar[1])) for m in beside}
        self.assertGreaterEqual(len(sides), 6)

    def test_it_blocks_the_way_but_not_the_view(self):
        w, lvl, (x, y) = cult_floor()
        self.assertFalse(lvl.walkable[x, y] or lvl.hover[x, y])
        self.assertTrue(lvl._base_transparent[x, y])
        self.assertNotIn((x, y), lvl.floor_cells)
        self.assertNotIn((x, y), lvl.land_cells)

    def test_nothing_lies_on_it(self):
        w, lvl, altar = cult_floor()
        self.assertNotIn(altar, lvl.items)

    def test_it_doesnt_block_the_floor(self):
        for seed in range(40):
            w = World(seed)
            lvl = w.level(CULT_FIRST + 2)
            self.assertTrue(lvl.mainland[lvl.down_front])

    def test_the_console_can_add_one(self):
        w = World(2)
        p = w.join("A")
        p.can_command = True
        commands.run(w, p, "spawn cult")
        self.assertTrue((w.levels[1].tiles == ALTAR).any())

    def test_guards_go_back_to_it(self):
        w, lvl, altar = cult_floor()
        leader = next(m for m in lvl.monsters if m.kind == "cult_leader")
        self.assertEqual(leader.post, altar)
        for m in lvl.monsters:
            if m is not leader:
                m.next_time = 10 ** 9
        spot = next(c for c in lvl.land_cells if 4 <= max(abs(c[0] - altar[0]), abs(c[1] - altar[1])) <= 8
                    and c not in lvl.occupant)
        lvl.move(leader, *spot)
        leader.state = "wandering"
        walk = lvl.distances_to(*altar)
        before = walk[leader.x, leader.y]
        for _ in range(4):
            w._monster_turn(leader, lvl)
        self.assertLess(walk[leader.x, leader.y], before)


class AuraTests(unittest.TestCase):
    def test_it_glows_purple_around_the_altar(self):
        w, lvl, p, (x, y) = at_altar()
        frame = view_of(w, p).draw()
        r, g, b = (int(c) for c in frame["bg"][21 + x - 1, 3 + y + 1])
        self.assertGreater(b, 100)
        self.assertGreater(b, g * 2)
        self.assertGreater(r, g)

    def test_it_pulses(self):
        w, lvl, p, (x, y) = at_altar()
        v = view_of(w, p)
        colors = set()
        for t in (0.0, 0.5, 1.0, 1.5):
            with mock.patch("game.render.time.monotonic", return_value=t):
                colors.add(tuple(int(c) for c in v.draw()["bg"][21 + x, 3 + y]))
        self.assertGreater(len(colors), 1)

    def test_a_spent_altar_doesnt(self):
        w, lvl, p, altar = at_altar()
        accept(w, p, altar)
        v = view_of(w, p)
        x, y = altar
        r, g, b = (int(c) for c in v.draw()["bg"][21 + x + 1, 3 + y + 1])
        self.assertLess(b, 90)

    def test_it_has_a_name_and_glyph(self):
        self.assertEqual(NAMES[ALTAR], "altar")
        self.assertEqual(NAMES[ALTAR_SPENT], "cold altar")
        self.assertIn(chr(int(GLYPH[ALTAR])), rows_of(view_of(*at_altar()[::2]).draw()))


class AskingTests(unittest.TestCase):
    def test_walking_into_it_asks_the_question(self):
        w, lvl, p, altar = at_altar()
        turns = p.turns
        prompts = [m for m in bump(w, p) if m["t"] == "prompt"]
        self.assertEqual(prompts[0]["text"], QUESTION)
        self.assertEqual(p.turns, turns)
        self.assertEqual((p.x, p.y), (altar[0] - 1, altar[1]))

    def test_with_no_weapon_it_doesnt(self):
        w, lvl, p, altar = at_altar(armed=False)
        msgs = bump(w, p)
        self.assertFalse([m for m in msgs if m["t"] == "prompt"])
        self.assertIn("wants a weapon", str(msgs))

    def test_a_cold_altar_says_nothing_more(self):
        w, lvl, p, altar = at_altar()
        accept(w, p, altar)
        w.drain_outbox()
        self.assertFalse([m for m in bump(w, p) if m["t"] == "prompt"])

    def test_it_shows_on_screen(self):
        w, lvl, p, altar = at_altar()
        v = view_of(w, p)
        for m in bump(w, p):
            v.apply(m)
        text = rows_of(v.draw())
        self.assertIn(QUESTION, text)
        self.assertIn("y yes", text)

    def test_walking_away_closes_it(self):
        w, lvl, p, altar = at_altar()
        v = view_of(w, p)
        for m in bump(w, p):
            v.apply(m)
        lvl.move(p, altar[0] - 4 if lvl.walkable[altar[0] - 4, altar[1]] else altar[0], altar[1] + 3)
        v.apply(w.state_for(p))
        self.assertIsNone(v.prompt)


class EnhanceTests(unittest.TestCase):
    def test_yes_improves_the_weapon_and_spends_the_altar(self):
        w, lvl, p, altar = at_altar()
        accept(w, p, altar)
        self.assertEqual(p.weapon.enhanced, 1)
        self.assertEqual(p.weapon.name, "sword +1")
        self.assertEqual(lvl.tiles[altar], ALTAR_SPENT)
        self.assertEqual(p.turns, 1)
        self.assertIn("Purple fire", str(w.drain_outbox()))

    def test_it_only_works_once(self):
        w, lvl, p, altar = at_altar()
        accept(w, p, altar)
        accept(w, p, altar)
        self.assertEqual(p.weapon.enhanced, 1)

    def test_the_client_sees_the_altar_go_out(self):
        w, lvl, p, altar = at_altar()
        v = view_of(w, p)
        accept(w, p, altar)
        for _, m in w.drain_outbox():
            v.apply(m)
        self.assertEqual(v.levels[p.depth][altar], ALTAR_SPENT)

    def test_you_must_be_next_to_it(self):
        w, lvl, p, altar = at_altar()
        lvl.move(p, *next(c for c in lvl.land_cells if max(abs(c[0] - altar[0]), abs(c[1] - altar[1])) > 3))
        accept(w, p, altar)
        self.assertEqual(p.weapon.enhanced, 0)
        self.assertEqual(lvl.tiles[altar], ALTAR)

    def test_a_forged_message_does_nothing(self):
        w, lvl, p, altar = at_altar()
        for x, y in ((None, 1), ("a", 2), (True, 2), (-1, 0), (9999, 0), (altar[0] - 1, altar[1])):
            w.advance(300)
            w.submit(p, {"a": "enhance", "x": x, "y": y})
        self.assertEqual(p.weapon.enhanced, 0)

    def test_every_buff_can_happen_and_stays_with_the_weapon(self):
        seen = set()
        for seed in range(300):
            sword = make_item("sword")
            seen.add(enhance_weapon(sword, random.Random(seed)))
        joined = " ".join(seen)
        for word in ("harder", "more often", "faster", "less noise", "alight", "freeze", "heals"):
            self.assertIn(word, joined)

    def test_they_stack(self):
        sword, rng = make_item("sword"), random.Random(1)
        for _ in range(8):
            enhance_weapon(sword, rng)
        self.assertEqual(sword.name, "sword +8")
        self.assertEqual(len(sword.magic), len(set(sword.magic)))
        self.assertGreaterEqual(sword.attack_cost, TICKS_PER_TURN // 2)

    def test_stats_reach_the_player(self):
        w, lvl, p, altar = at_altar()
        p.weapon.damage = (20, 30)
        p.weapon.accuracy = 15
        w._use(p, 0)
        w._use(p, 0)
        self.assertEqual(p.damage, (20, 30))
        self.assertEqual(p.accuracy, 115)
        p.weapon = None
        w._use(p, 0)
        w._use(p, 0)

    def test_a_teammate_can_inherit_it(self):
        w, lvl, p, altar = at_altar()
        accept(w, p, altar)
        w.advance(300)
        w.submit(p, {"a": "drop", "slot": 0})
        self.assertTrue(any(i.enhanced == 1 for i in lvl.items.values()))

    def test_it_shows_in_the_pack(self):
        sword = make_item("sword")
        sword.magic = ("fire",)
        self.assertIn("fire", sword.info)


class WeaponMagicTests(unittest.TestCase):
    def setUp(self):
        self.w = World(3)
        self.p = self.w.join("A")
        self.lvl = self.w.levels[1]
        self.sword = make_item("sword")
        self.p.pack.append(self.sword)
        self.w._use(self.p, 0)
        self.m = make_monster("ogre", 900)
        self.m.hp = self.m.max_hp = 100000
        self.m.state = "wandering"           # a sneak attack always lands

    def test_fire_burns(self):
        self.sword.magic = ("fire",)
        self.w._attack(self.p, self.m)
        self.assertGreater(self.m.burning, 0)
        self.assertIs(self.m.burned_by, self.p)

    def test_frost_sometimes_freezes(self):
        self.sword.magic = ("frost",)
        hits = 0
        for _ in range(200):
            self.m.state, self.m.frozen_until = "wandering", 0
            self.w._attack(self.p, self.m)
            hits += self.m.frozen_until > 0
        self.assertTrue(10 < hits < 90, hits)

    def test_drain_heals(self):
        self.sword.magic = ("drain",)
        self.p.hp = 10
        self.w._attack(self.p, self.m)
        self.assertGreater(self.p.hp, 10)
        self.p.hp = self.p.max_hp
        self.m.state = "wandering"
        self.w._attack(self.p, self.m)
        self.assertEqual(self.p.hp, self.p.max_hp)

    def test_a_plain_weapon_does_none_of_it(self):
        self.w._attack(self.p, self.m)
        self.assertEqual((self.m.burning, self.m.frozen_until), (0, 0))

    def test_monsters_cant_use_it(self):
        self.p.hp = self.p.max_hp = 100000
        self.w._attack(self.m, self.p)
        self.assertEqual(self.m.burning, 0)


class FakeNet:
    def __init__(self, world, player, prompt):
        self.world, self.player, self.prompt, self.sent, self.fresh = world, player, prompt, [], True

    def poll(self):
        if self.fresh:
            self.fresh = False
            return [{"t": "welcome", "id": self.player.id, "name": self.player.name},
                    self.world.level_msg(self.player.depth), self.world.state_for(self.player), self.prompt]
        return []

    def send(self, msg):
        self.sent.append(msg)


class FakeContext:
    def present(self, console, keep_aspect=True):
        pass


class KeyTests(unittest.TestCase):
    def answer(self, *syms):
        w, lvl, p, altar = at_altar()
        prompt = {"t": "prompt", "text": QUESTION, "x": altar[0], "y": altar[1]}
        net = FakeNet(w, p, prompt)
        events = [tcod.event.KeyDown(scancode=tcod.event.Scancode.UNKNOWN, sym=s, mod=tcod.event.Modifier.NONE)
                  for s in syms]
        batches = iter([[], *([e] for e in events), [tcod.event.Quit()]])
        with mock.patch("client.tcod.event.get", lambda: next(batches)), mock.patch("client.time.sleep"):
            client.play(FakeContext(), client.new_console(), net)
        return [m for m in net.sent if m.get("a") in ("enhance", "hold")], altar

    def test_y_says_yes(self):
        acts, altar = self.answer(tcod.event.KeySym.y)
        self.assertEqual(acts[0], {"t": "act", "a": "enhance", "x": altar[0], "y": altar[1]})

    def test_y_doesnt_also_walk(self):
        acts, _ = self.answer(tcod.event.KeySym.y)
        self.assertFalse([a for a in acts if a["a"] == "hold" and (a["dx"] or a["dy"])])

    def test_enter_says_yes_and_doesnt_open_chat(self):
        acts, _ = self.answer(tcod.event.KeySym.RETURN)
        self.assertEqual(acts[0]["a"], "enhance")

    def test_n_says_no(self):
        acts, _ = self.answer(tcod.event.KeySym.n)
        self.assertFalse([a for a in acts if a["a"] == "enhance"])
        self.assertFalse([a for a in acts if a["a"] == "hold" and (a["dx"] or a["dy"])])

    def test_esc_says_no(self):
        acts, _ = self.answer(tcod.event.KeySym.ESCAPE)
        self.assertFalse([a for a in acts if a["a"] == "enhance"])

    def test_afterwards_y_walks_again(self):
        acts, _ = self.answer(tcod.event.KeySym.n, tcod.event.KeySym.y)
        self.assertTrue([a for a in acts if a["a"] == "hold" and a["dx"] == -1 and a["dy"] == -1])


class TeleportPotionTests(unittest.TestCase):
    def setUp(self):
        self.w = World(4)
        self.p = self.w.join("A")

    def drink(self):
        self.p.pack.append(make_item("teleportation"))
        self.w.submit(self.p, {"a": "use", "slot": len(self.p.pack) - 1})
        self.w.advance(TICKS_PER_TURN)
        self.w.advance(TICKS_PER_TURN)

    def test_it_changes_floor(self):
        self.drink()
        self.assertNotEqual(self.p.depth, 1)
        self.assertTrue(1 <= self.p.depth <= LAST_FLOOR)
        self.assertTrue(self.p.needs_level)

    def test_it_covers_the_whole_dungeon(self):
        floors = []
        for _ in range(150):
            self.w.levels[self.p.depth].remove(self.p)
            self.w.levels[1].place(self.p, *self.w.levels[1].free_near(*self.w.levels[1].up_front))
            self.w._teleport_floor(self.p)
            floors.append(self.p.depth)
        self.assertLess(min(floors), 15)
        self.assertGreater(max(floors), 85)
        self.assertNotIn(1, floors)

    def test_you_land_properly(self):
        self.w.levels[1].items.clear()
        for _ in range(25):
            self.w._teleport_floor(self.p)
            lvl = self.w.levels[self.p.depth]
            self.assertIs(lvl.occupant[(self.p.x, self.p.y)], self.p)
            self.assertTrue(lvl.mainland[self.p.x, self.p.y])
            if lvl.vault is not None:
                self.assertFalse(lvl.vault[self.p.x, self.p.y])

    def test_you_leave_the_old_floor(self):
        spot = (self.p.x, self.p.y)
        self.drink()
        self.assertNotIn(spot, self.w.levels[1].occupant)

    def test_it_stops_a_held_direction(self):
        self.p.hold = (1, 0)
        self.w._teleport_floor(self.p)
        self.assertIsNone(self.p.hold)

    def test_running_from_an_awake_necromancer_still_counts(self):
        self.w.warp(self.p, LAST_FLOOR)
        self.w._hunt(self.w.necromancer, self.p)
        self.w._teleport_floor(self.p)
        self.assertTrue(self.p.chased)

    def test_the_console_teleport_stays_on_the_floor(self):
        self.p.can_command = True
        commands.run(self.w, self.p, "teleport")
        self.assertEqual(self.p.depth, 1)

    def test_it_says_so(self):
        self.assertEqual(make_item("teleportation").info, "jump to a random floor")


if __name__ == "__main__":
    unittest.main()
