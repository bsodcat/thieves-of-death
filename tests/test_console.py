"""The test console and the potion of teleportation."""
import asyncio
import socket
import threading
import time
import unittest
from unittest import mock

import numpy as np
import tcod.event

import client
from game import commands, mapgen, protocol
from game.constants import SCREEN_H, TELEPORT_STEPS, MAP_H, MAP_W
from game.items import ITEMS, make_item
from game.render import MARK_ITEM, MARK_MONSTER, ClientView
from game.entities import make_monster
from game.tiles import DEEP, LAVA, LOCKED, PIT, WALKABLE, WALL
from game.world import Level, LockedRoom, World
from server import GameServer, is_local


def rows_of(frame):
    return "\n".join("".join(chr(c) for c in frame["ch"][:, y]) for y in range(SCREEN_H))


def host(name="Host", seed=3):
    w = World(seed)
    p = w.join(name)
    p.can_command = True
    return w, p


def run(w, p, text):
    """The lines a command sends back to that player's console."""
    w.drain_outbox()
    commands.run(w, p, text)
    return [m["text"] for pid, m in w.drain_outbox() if pid == p.id and m["t"] == "console"]


class PermissionTests(unittest.TestCase):
    def test_only_the_hosts_computer_counts(self):
        self.assertTrue(is_local(("127.0.0.1", 5000)))
        self.assertTrue(is_local(("::1", 5000, 0, 0)))
        self.assertFalse(is_local(("192.168.1.20", 5000)))
        self.assertFalse(is_local(("100.64.0.5", 5000)))
        self.assertFalse(is_local(None))

    def test_a_remote_player_is_refused_and_nothing_happens(self):
        w, p = host()
        guest = w.join("Guest")
        lines = run(w, guest, "gold 500")
        self.assertIn("host's computer", lines[0])
        self.assertEqual(guest.gold, 0)

    def test_players_arent_trusted_by_default(self):
        self.assertFalse(World(1).join("A").can_command)

    def test_the_party_is_told(self):
        w, p = host()
        guest = w.join("Guest")
        w.drain_outbox()
        commands.run(w, p, "gold 500")
        told = [m["text"] for pid, m in w.drain_outbox() if pid == guest.id]
        self.assertTrue(any("Host used the console: gold 500" in t for t in told))

    def test_looking_things_up_isnt_announced(self):
        w, p = host()
        guest = w.join("Guest")
        w.drain_outbox()
        commands.run(w, p, "help")
        self.assertFalse([m for pid, m in w.drain_outbox() if pid == guest.id])


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.w, self.p = host()

    def test_help_lists_every_command(self):
        text = "\n".join(run(self.w, self.p, "help"))
        for name in commands.COMMANDS:
            self.assertIn(name, text)

    def test_every_listed_command_says_what_it_does(self):
        for fn, usage, what in commands.COMMANDS.values():
            self.assertTrue(usage and what)
            self.assertLessEqual(24 + len(what), 68, what)

    def test_nonsense_is_handled(self):
        for line in ("", "   ", "wibble", "give", "give wibble", "give wand x", "give wand -1", "gold", "gold lots",
                     "gold 99999999999", "goto", "goto 0", "goto 99999", "spawn", "spawn wibble", "spawn rat 999",
                     "stealth", "stealth 500", "\x00\x01", "give " + "x" * 5000):
            lines = run(self.w, self.p, line)
            if line.strip():
                self.assertTrue(lines, repr(line))

    def test_give_every_item(self):
        for name in commands.item_names():
            self.p.pack.clear()
            run(self.w, self.p, f"give {name}")
            self.assertEqual(len(self.p.pack), 0 if name == "gold" else 1, name)  # gold isn't a pack item
        self.assertGreater(self.p.gold, 0)

    def test_names_can_be_cut_short(self):
        run(self.w, self.p, "give tele 3")
        self.assertEqual((self.p.pack[0].kind, self.p.pack[0].count), ("teleportation", 3))

    def test_a_short_name_with_two_matches_asks_which(self):
        self.assertIn("Which item?", run(self.w, self.p, "give l")[0])

    def test_a_full_pack_is_reported(self):
        self.assertIn("full", run(self.w, self.p, "give dagger 99")[0])
        self.assertEqual(len(self.p.pack), 10)

    def test_gold_and_heal(self):
        run(self.w, self.p, "gold 250")
        self.assertEqual(self.p.gold, 250)
        self.p.hp, self.p.stamina = 1, 0
        run(self.w, self.p, "heal")
        self.assertEqual((self.p.hp, self.p.stamina), (self.p.max_hp, 100))

    def test_god_stops_all_damage(self):
        from game.entities import make_monster
        run(self.w, self.p, "god")
        self.assertTrue(self.p.god)
        m = make_monster("ogre", 900)
        for _ in range(20):
            self.w._attack(m, self.p)
        self.assertEqual(self.p.hp, self.p.max_hp)
        run(self.w, self.p, "god")
        self.assertFalse(self.p.god)

    def test_goto(self):
        run(self.w, self.p, "goto 51")
        self.assertEqual(self.p.depth, 51)
        self.assertTrue(self.p.needs_level)
        self.assertNotIn(self.p, self.w.levels[1].occupant.values())
        self.assertEqual(self.w.levels[51].occupant[(self.p.x, self.p.y)], self.p)

    def test_floor_moves_you(self):
        self.assertEqual(run(self.w, self.p, "floor 12"), ["Host is on floor 12."])
        self.assertEqual(self.p.depth, 12)
        self.assertTrue(self.p.needs_level)
        self.assertIs(self.w.levels[12].occupant[(self.p.x, self.p.y)], self.p)
        self.assertNotIn(self.p, self.w.levels[1].occupant.values())

    def test_floor_moves_another_player(self):
        guest = self.w.join("Guest Two")
        for name in ("Guest Two", "guest"):
            run(self.w, self.p, f"floor 7 {name}")
            self.assertEqual(guest.depth, 7)
            self.assertEqual(self.p.depth, 1)
            self.w.warp(guest, 1)
        guest.needs_level = False
        self.w.drain_outbox()
        commands.run(self.w, self.p, "floor 7 guest")
        self.assertTrue(guest.needs_level)
        self.assertIn("Host moved you to floor 7.", str(self.w.drain_outbox()))

    def test_floor_refuses_bad_input(self):
        for line, text in (("floor", "floor <number>"), ("floor x", "isn't a number"), ("floor 0", "from 1"),
                           ("floor 1000", "from 1"), ("floor 3 nobody", "No player")):
            self.assertIn(text, run(self.w, self.p, line)[0])
        self.assertEqual(self.p.depth, 1)

    def test_floor_needs_them_alive(self):
        guest = self.w.join("Guest")
        self.w._kill(guest, None)
        self.assertIn("Guest has to be alive", run(self.w, self.p, "floor 3 guest")[0])

    def test_a_guest_cant_use_floor(self):
        guest = self.w.join("Guest")
        run(self.w, guest, "floor 9")
        self.assertEqual(guest.depth, 1)

    def test_floor_can_be_shortened(self):
        run(self.w, self.p, "fl 4")
        self.assertEqual(self.p.depth, 4)

    def test_spawn(self):
        before = len(self.w.levels[1].monsters)
        run(self.w, self.p, "spawn ogre 3")
        self.assertEqual(len(self.w.levels[1].monsters), before + 3)
        for m in self.w.levels[1].monsters:
            self.assertEqual(self.w.levels[1].occupant[(m.x, m.y)], m)
        self.w.advance(500)

    def test_spawn_cult(self):
        run(self.w, self.p, "spawn cult")
        cult = [m for m in self.w.levels[1].monsters if m.kind.startswith("cult")]
        self.assertGreaterEqual(len(cult), 6)

    def test_killall_drops_the_wand(self):
        run(self.w, self.p, "spawn cult")
        run(self.w, self.p, "killall")
        lvl = self.w.levels[1]
        self.assertEqual(lvl.monsters, [])
        self.assertTrue(any(i.category == "wand" for i in lvl.items.values()))

    def test_killall_works_while_dead(self):
        self.w._kill(self.p, None)
        run(self.w, self.p, "killall")
        self.assertEqual(self.w.levels[1].monsters, [])

    def test_stealth_respects_the_cap(self):
        run(self.w, self.p, "stealth 80")
        self.assertEqual(self.p.stealth, 80)
        self.p.stealth_cap = 40
        run(self.w, self.p, "stealth 80")
        self.assertEqual(self.p.stealth, 40)

    def test_commands_that_need_you_alive_say_so(self):
        self.w._kill(self.p, None)
        for line in ("goto 3", "spawn rat", "heal", "teleport"):
            self.assertIn("alive", run(self.w, self.p, line)[0])

    def test_info(self):
        self.w.locked_rooms = {6: LockedRoom(6, 4, "red")}
        text = "\n".join(run(self.w, self.p, "info"))
        self.assertIn(f"Seed {self.w.seed}", text)
        self.assertIn("red on 6, key on 4", text)

    def test_a_key_fits_this_floors_door(self):
        self.w.locked_rooms = {2: LockedRoom(2, 4, "red")}
        run(self.w, self.p, "goto 2")
        run(self.w, self.p, "give red_key")
        self.assertEqual(self.p.pack[0].opens, 2)
        self.assertEqual(self.w.levels[2].tiles[self.w.levels[2].lock], LOCKED["red"])


def open_spot(lvl, tile_test):
    """A floor tile with a matching tile to its right."""
    return next(c for c in lvl.floor_cells if tile_test((c[0] + 1, c[1])))


class CollisionTests(unittest.TestCase):
    def setUp(self):
        self.w, self.p = host()
        self.lvl = self.w.levels[1]
        for m in list(self.lvl.monsters):
            self.lvl.remove(m)
        self.lvl.monsters.clear()
        self.lvl.items.clear()

    def step(self, dx=1, dy=0):
        self.w.advance(300)
        self.w.submit(self.p, {"a": "move", "dx": dx, "dy": dy})
        self.w.advance(1)

    def ghost(self):
        self.assertEqual(run(self.w, self.p, "collision off"), ["Collision is off."])

    def monster(self, x, y):
        m = make_monster("ogre", 950 + x)
        m.next_time = 10 ** 9
        self.lvl.place(m, x, y)
        self.lvl.monsters.append(m)
        return m

    def test_collision_is_on_by_default(self):
        self.assertFalse(self.p.noclip)

    def test_on_its_own_it_toggles(self):
        run(self.w, self.p, "collision")
        self.assertTrue(self.p.noclip)
        run(self.w, self.p, "collision")
        self.assertFalse(self.p.noclip)

    def test_walks_through_walls(self):
        spot = open_spot(self.lvl, lambda c: self.lvl.tiles[c] == WALL)
        self.lvl.move(self.p, *spot)
        self.ghost()
        self.step()
        self.assertEqual((self.p.x, self.p.y), (spot[0] + 1, spot[1]))
        self.step()
        self.assertEqual(self.p.x, spot[0] + 2)

    def test_walls_stop_you_with_collision_on(self):
        spot = open_spot(self.lvl, lambda c: self.lvl.tiles[c] == WALL)
        self.lvl.move(self.p, *spot)
        self.step()
        self.assertEqual((self.p.x, self.p.y), spot)

    def test_walks_through_enemies_without_hitting_them(self):
        spot = open_spot(self.lvl, lambda c: self.lvl.walkable[c])
        self.lvl.move(self.p, *spot)
        m = self.monster(spot[0] + 1, spot[1])
        self.ghost()
        self.step()
        self.assertEqual((self.p.x, self.p.y), (spot[0] + 2, spot[1]))
        self.assertEqual(m.hp, m.max_hp)
        self.assertIs(self.lvl.occupant[(m.x, m.y)], m)
        self.assertIs(self.lvl.occupant[(self.p.x, self.p.y)], self.p)

    def test_walks_through_a_line_of_them(self):
        spot = open_spot(self.lvl, lambda c: self.lvl.walkable[c])
        self.lvl.move(self.p, *spot)
        for i in (1, 2, 3):
            self.monster(spot[0] + i, spot[1])
        self.ghost()
        self.step()
        self.assertEqual(self.p.x, spot[0] + 4)

    def test_hazards_dont_touch_you(self):
        for tile in (DEEP, PIT, LAVA):
            gen = mapgen.generate(1, 1)
            x, y = open_spot(self.lvl, lambda c: self.lvl.tiles[c] == 1)
            gen.tiles[x + 1, y] = tile
            self.w.levels[1] = lvl = Level(1, gen)
            lvl.place(self.p, x, y)
            self.ghost()
            self.step()
            self.assertEqual((self.p.depth, self.p.x, self.p.hp), (1, x + 1, self.p.max_hp))
            run(self.w, self.p, "collision on")
            self.assertTrue(lvl.walkable[self.p.x, self.p.y])

    def test_you_can_walk_into_a_locked_room_and_out_again(self):
        self.w.locked_rooms = {2: LockedRoom(2, 4, "red")}
        self.w.warp(self.p, 2)
        lvl = self.w.levels[2]
        self.ghost()
        spot = next(c for c in map(tuple, np.argwhere(lvl.vault)))
        lvl.move(self.p, int(spot[0]), int(spot[1]))
        run(self.w, self.p, "collision on")
        self.assertFalse(lvl.vault[self.p.x, self.p.y])
        self.assertTrue(lvl.walkable[self.p.x, self.p.y])

    def test_turning_it_back_on_inside_a_wall_frees_you(self):
        self.ghost()
        wall = next((x, y) for x in range(1, MAP_W - 1) for y in range(1, MAP_H - 1)
                    if self.lvl.tiles[x, y] == WALL and self.lvl.tiles[x - 1, y] == WALL
                    and self.lvl.tiles[x + 1, y] == WALL and self.lvl.tiles[x, y - 1] == WALL
                    and self.lvl.tiles[x, y + 1] == WALL)
        self.lvl.move(self.p, *wall)
        run(self.w, self.p, "collision on")
        self.assertTrue(self.lvl.walkable[self.p.x, self.p.y])

    def test_stairs_still_work(self):
        self.lvl.move(self.p, *self.lvl.down_front)
        self.ghost()
        self.step(self.lvl.down[0] - self.p.x, self.lvl.down[1] - self.p.y)
        self.assertEqual(self.p.depth, 2)

    def test_the_edge_of_the_map_stops_you(self):
        self.ghost()
        self.lvl.move(self.p, MAP_W - 1, 5)
        self.step()
        self.assertEqual(self.p.x, MAP_W - 1)

    def test_diagonals_ignore_corners(self):
        x, y = next((x, y) for x, y in self.lvl.floor_cells if self.lvl.tiles[x + 1, y] == WALL
                    and self.lvl.tiles[x, y + 1] == WALL)
        self.lvl.move(self.p, x, y)
        self.ghost()
        self.step(1, 1)
        self.assertEqual((self.p.x, self.p.y), (x + 1, y + 1))

    def test_dying_inside_a_wall_leaves_bones_where_they_can_be_reached(self):
        self.w.join("Friend")
        self.ghost()
        wall = next((x, y) for x in range(2, MAP_W - 2) for y in range(2, MAP_H - 2)
                    if not self.lvl.hover[x - 1:x + 2, y - 1:y + 2].any())
        self.lvl.move(self.p, *wall)
        self.w._kill(self.p, None)
        self.assertTrue(self.lvl.walkable[self.p.x, self.p.y])

    def test_rejoining_from_inside_a_wall_is_safe(self):
        self.ghost()
        wall = next((x, y) for x in range(2, MAP_W - 2) for y in range(2, MAP_H - 2)
                    if not self.lvl.hover[x - 1:x + 2, y - 1:y + 2].any())
        self.lvl.move(self.p, *wall)
        self.w.leave(self.p)
        back = self.w.join("Host")
        self.assertTrue(self.lvl.walkable[back.x, back.y])

    def test_god_mode_alone_still_collides_and_fights(self):
        spot = open_spot(self.lvl, lambda c: self.lvl.walkable[c])
        self.lvl.move(self.p, *spot)
        m = self.monster(spot[0] + 1, spot[1])
        m.state = "sleeping"
        run(self.w, self.p, "god")
        self.step()
        self.assertEqual((self.p.x, self.p.y), spot)
        self.assertLess(m.hp, m.max_hp)

    def test_a_guest_cant_use_it(self):
        guest = self.w.join("Guest")
        run(self.w, guest, "collision off")
        self.assertFalse(guest.noclip)

    def test_nonsense_is_refused(self):
        self.assertIn("No setting", run(self.w, self.p, "collision maybe")[0])
        self.assertFalse(self.p.noclip)


class ViewTests(unittest.TestCase):
    def view(self):
        w, p = host()
        v = ClientView()
        v.apply({"t": "welcome", "id": p.id, "name": p.name})
        v.apply(w.level_msg(1))
        v.apply(w.state_for(p))
        return v, w, p

    def test_hidden_until_opened(self):
        v, w, p = self.view()
        self.assertNotIn("Test console", rows_of(v.draw()))
        v.console_open = True
        self.assertIn("Test console", rows_of(v.draw()))

    def test_typing_and_replies_are_drawn(self):
        v, w, p = self.view()
        v.console_open, v.console_buf = True, "give wand"
        self.assertIn("> give wand_", rows_of(v.draw()))
        sent = v.console_submit()
        self.assertEqual((sent, v.console_buf), ("give wand", ""))
        v.apply({"t": "console", "text": "Gave you 1 x wand of fire.", "c": [1, 2, 3]})
        text = rows_of(v.draw())
        self.assertIn("> give wand", text)
        self.assertIn("Gave you 1", text)

    def test_every_line_of_help_fits(self):
        v, w, p = self.view()
        v.console_open = True
        commands.run(w, p, "help")
        for _, msg in w.drain_outbox():
            v.apply(msg)
        self.assertLessEqual(len(commands.COMMANDS), 200)
        for line, _ in v.console_log:
            self.assertLessEqual(len(line), 68)

    def test_all_of_help_is_on_screen_at_once(self):
        v, w, p = self.view()
        v.console_open = True
        v.console_buf = "help"
        v.console_submit()
        commands.run(w, p, "help")
        for _, msg in w.drain_outbox():
            v.apply(msg)
        text = rows_of(v.draw())
        self.assertIn("> help", text)
        for _, usage, _ in commands.COMMANDS.values():
            self.assertIn(usage, text)

    def test_help_explains_one_command(self):
        w, p = host()
        self.assertEqual(run(w, p, "help god"), ["god: Take no damage, on or off"])

    def test_long_lines_wrap_and_lose_nothing(self):
        v, w, p = self.view()
        commands.run(w, p, "list")
        for _, msg in w.drain_outbox():
            v.apply(msg)
        self.assertIn("cult_leader", "".join(line for line, _ in v.console_log))

    def test_list_is_in_tidy_columns(self):
        from game.render import CONSOLE_WIDTH
        w, p = host()
        w.drain_outbox()
        commands.run(w, p, "list")
        sent = [m for _, m in w.drain_outbox() if m["t"] == "console"]
        rows = [m["text"] for m in sent]
        self.assertTrue(all(len(r) <= CONSOLE_WIDTH - 4 for r in rows))  # nothing wraps
        self.assertEqual(sum(tuple(m["c"]) == commands.HEADING for m in sent), 2)
        self.assertTrue(any(r.startswith("Weapons") and "sword" in r for r in rows))
        listed = " ".join(rows).split()
        for name in [*commands.item_names(), *commands.MONSTERS]:
            self.assertIn(name, listed)

    def test_list_just_the_monsters(self):
        w, p = host()
        rows = " ".join(run(w, p, "list mon"))
        self.assertIn("skeleton_warrior", rows)
        self.assertNotIn("greatsword", rows)

    def test_up_and_down_recall(self):
        v, w, p = self.view()
        for line in ("first", "second"):
            v.console_buf = line
            v.console_submit()
        v.console_recall(1)
        self.assertEqual(v.console_buf, "second")
        v.console_recall(1)
        self.assertEqual(v.console_buf, "first")
        v.console_recall(1)
        self.assertEqual(v.console_buf, "first")
        v.console_recall(-1)
        v.console_recall(-1)
        self.assertEqual(v.console_buf, "")

    def test_clear_stays_on_the_client(self):
        v, w, p = self.view()
        v.console_log.append(("old", (1, 2, 3)))
        v.console_buf = "clear"
        self.assertEqual(v.console_submit(), "")
        self.assertEqual(len(v.console_log), 0)

    def test_reveal_fills_the_map(self):
        v, w, p = self.view()
        self.assertFalse(v.seen[1].all())
        commands.run(w, p, "reveal")
        v.apply(w.state_for(p))
        self.assertTrue(v.seen[1].all())

    def test_reveal_maps_each_new_floor_too(self):
        v, w, p = self.view()
        commands.run(w, p, "reveal")
        w.warp(p, 4)
        v.apply(w.level_msg(4))
        v.apply(w.state_for(p))
        self.assertTrue(v.seen[4].all())

    def test_reveal_shows_and_marks_everything_on_the_floor(self):
        v, w, p = self.view()
        lvl = w.levels[1]
        far = next(m for m in lvl.monsters if not w.fov(p)[m.x, m.y])
        self.assertNotIn(far.id, [e["id"] for e in w.state_for(p)["ents"]])
        commands.run(w, p, "reveal")
        v.apply(w.state_for(p))
        self.assertEqual({e["id"] for e in v.ents if e["hl"]}, {m.id for m in lvl.monsters})
        self.assertEqual(set(v.item_memory[1]), set(lvl.items))
        frame = v.draw()
        self.assertEqual(int(frame["ch"][21 + far.x, 3 + far.y]), ord(far.glyph))
        self.assertEqual(tuple(int(c) for c in frame["bg"][21 + far.x, 3 + far.y]), MARK_MONSTER)
        x, y = next(c for c in lvl.items if c not in lvl.occupant)
        self.assertEqual(tuple(int(c) for c in frame["bg"][21 + x, 3 + y]), MARK_ITEM)

    def test_reveal_marks_what_appears_later(self):
        v, w, p = self.view()
        commands.run(w, p, "reveal")
        lvl = w.levels[1]
        spot = next(c for c in lvl.land_cells if not w.fov(p)[c] and c not in lvl.occupant and c not in lvl.items)
        rat = make_monster("rat", 9001)
        lvl.place(rat, *spot)
        lvl.monsters.append(rat)
        lvl.items[spot] = make_item("sword")
        v.apply(w.state_for(p))
        self.assertIn(9001, [e["id"] for e in v.ents if e["hl"]])
        self.assertIn(spot, v.item_memory[1])
        del lvl.items[spot]
        v.apply(w.state_for(p))
        self.assertNotIn(spot, v.item_memory[1])

    def test_reveal_turns_off(self):
        v, w, p = self.view()
        commands.run(w, p, "reveal")
        commands.run(w, p, "reveal")
        v.apply(w.state_for(p))
        self.assertFalse([e for e in v.ents if e.get("hl")])

    def test_reveal_doesnt_flood_the_sidebar(self):
        v, w, p = self.view()
        commands.run(w, p, "reveal")
        v.apply(w.state_for(p))
        frame = v.draw()
        hidden = next(m for m in w.levels[1].monsters if not w.fov(p)[m.x, m.y])
        sidebar = "\n".join("".join(chr(c) for c in frame["ch"][:20, y]) for y in range(24))
        visible_names = {m.name for m in w.levels[1].monsters if w.fov(p)[m.x, m.y]}
        if hidden.name not in visible_names:
            self.assertNotIn(hidden.name, sidebar)

    def test_reveal_is_only_for_you(self):
        w, p = host()
        guest = w.join("Guest")
        commands.run(w, p, "reveal")
        self.assertFalse(w.state_for(guest)["reveal"])

    def test_ultrabright_lights_the_whole_floor(self):
        v, w, p = self.view()
        x, y = next((x, y) for x in range(MAP_W) for y in range(MAP_H) if not v.seen[1][x, y] and v.levels[1][x, y] == 0)
        self.assertEqual(tuple(int(c) for c in v.draw()["bg"][21 + x, 3 + y]), (0, 0, 0))
        commands.run(w, p, "ultrabright")
        v.apply(w.state_for(p))
        frame = v.draw()
        self.assertGreater(int(frame["bg"][21 + x, 3 + y][0]), 40)
        self.assertEqual(int(frame["ch"][21 + x, 3 + y]), ord("#"))
        self.assertEqual(v.describe(x, y)[0][0], "Granite wall")

    def test_ultrabright_alone_shows_no_monsters(self):
        v, w, p = self.view()
        commands.run(w, p, "ultrabright")
        v.apply(w.state_for(p))
        m = next(m for m in w.levels[1].monsters if not w.fov(p)[m.x, m.y])
        self.assertNotEqual(int(v.draw()["ch"][21 + m.x, 3 + m.y]), ord(m.glyph))

    def test_ultrabright_stays_on_across_floors_and_toggles_off(self):
        v, w, p = self.view()
        commands.run(w, p, "ultrabright")
        w.warp(p, 6)
        v.apply(w.level_msg(6))
        v.apply(w.state_for(p))
        self.assertTrue(v.bright)
        commands.run(w, p, "ultrabright")
        v.apply(w.state_for(p))
        self.assertFalse(v.bright)

    def test_ultrabright_doesnt_change_what_auto_walk_knows(self):
        v, w, p = self.view()
        commands.run(w, p, "ultrabright")
        v.apply(w.state_for(p))
        self.assertFalse(v.seen[1].all())

    def test_a_guest_gets_neither(self):
        w, p = host()
        guest = w.join("Guest")
        commands.run(w, guest, "ultrabright")
        commands.run(w, guest, "reveal")
        self.assertFalse(guest.bright or guest.reveal)

    def test_never_covers_the_player(self):
        v, w, p = self.view()
        v.console_open = True
        for x in range(0, MAP_W, 6):
            for y in range(0, MAP_H, 3):
                v.ents = [{**e, "x": x, "y": y} for e in v.ents]
                frame = v.draw()
                self.assertNotEqual(tuple(frame["bg"][21 + x, 3 + y]), (20, 20, 34), (x, y))


class FakeNet:
    def __init__(self, world, player):
        self.world, self.player, self.sent, self.fresh = world, player, [], True

    def poll(self):
        if self.fresh:
            self.fresh = False
            return [{"t": "welcome", "id": self.player.id, "name": self.player.name},
                    self.world.level_msg(1), self.world.state_for(self.player)]
        return []

    def send(self, msg):
        self.sent.append(msg)


class FakeContext:
    def present(self, console, keep_aspect=True):
        pass


class KeyHandlingTests(unittest.TestCase):
    """Sends the real play loop the same events a keyboard would."""

    def play(self, *events):
        w, p = host()
        net = FakeNet(w, p)
        batches = iter([[], *([e] for e in events), [tcod.event.Quit()]])
        with mock.patch("client.tcod.event.get", lambda: next(batches)), mock.patch("client.time.sleep"):
            self.assertFalse(client.play(FakeContext(), client.new_console(), net))
        return [m for m in net.sent if m.get("t") == "cmd"], [m for m in net.sent if m.get("t") == "act"]

    @staticmethod
    def key(sym):
        return tcod.event.KeyDown(scancode=tcod.event.Scancode.UNKNOWN, sym=sym, mod=tcod.event.Modifier.NONE)

    def typed(self, text):
        return [tcod.event.TextInput(text=c) for c in text]

    def test_backquote_opens_it_and_enter_sends_the_line(self):
        keys = tcod.event.KeySym
        cmds, acts = self.play(self.key(keys.GRAVE), tcod.event.TextInput(text="`"), *self.typed("gold 5"),
                               self.key(keys.RETURN))
        self.assertEqual(cmds, [{"t": "cmd", "text": "gold 5"}])

    def test_f2_opens_it_too(self):
        keys = tcod.event.KeySym
        cmds, _ = self.play(self.key(keys.F2), *self.typed("heal"), self.key(keys.RETURN))
        self.assertEqual(cmds[0]["text"], "heal")

    def test_typing_in_it_doesnt_play_the_game(self):
        keys = tcod.event.KeySym
        _, acts = self.play(self.key(keys.GRAVE), self.key(keys.h), self.key(keys.UP), *self.typed("gq"))
        self.assertFalse([a for a in acts if a["a"] in ("pickup", "move")
                          or (a["a"] == "hold" and (a["dx"] or a["dy"]))])

    def test_esc_closes_it_and_the_game_gets_keys_again(self):
        keys = tcod.event.KeySym
        cmds, acts = self.play(self.key(keys.GRAVE), self.key(keys.ESCAPE), tcod.event.TextInput(text="g"))
        self.assertIn({"t": "act", "a": "pickup"}, acts)

    def test_backspace_and_recall(self):
        keys = tcod.event.KeySym
        cmds, _ = self.play(self.key(keys.F2), *self.typed("healx"), self.key(keys.BACKSPACE), self.key(keys.RETURN),
                            self.key(keys.UP), self.key(keys.RETURN))
        self.assertEqual([c["text"] for c in cmds], ["heal", "heal"])

    def test_opening_it_stops_walking(self):
        keys = tcod.event.KeySym
        _, acts = self.play(self.key(keys.UP), self.key(keys.GRAVE))
        self.assertEqual(acts[-1]["a"], "hold")
        self.assertEqual((acts[-1]["dx"], acts[-1]["dy"]), (0, 0))


class RealConnectionTests(unittest.TestCase):
    def test_a_command_from_this_computer_works_over_a_real_connection(self):
        loop = asyncio.new_event_loop()
        world = World(seed=3)
        server = loop.run_until_complete(GameServer(world).start("127.0.0.1", 0))
        port = server.sockets[0].getsockname()[1]
        threading.Thread(target=loop.run_forever, daemon=True).start()
        sock = socket.create_connection(("127.0.0.1", port), timeout=5)
        file = sock.makefile("r", encoding="utf-8")
        sock.sendall(protocol.encode({"t": "hello", "name": "Host"}))
        sock.sendall(protocol.encode({"t": "cmd", "text": "gold 77"}))
        end, reply = time.time() + 5, None
        while time.time() < end and reply is None:
            msg = protocol.decode(file.readline())
            if msg.get("t") == "console":
                reply = msg["text"]
        file.close()
        sock.close()

        async def shutdown():
            server.close()
            for task in asyncio.all_tasks():
                if task is not asyncio.current_task():
                    task.cancel()
            await asyncio.sleep(0.05)
        asyncio.run_coroutine_threadsafe(shutdown(), loop).result(5)
        loop.call_soon_threadsafe(loop.stop)
        self.assertEqual(reply, "You have 77 gold.")


class TeleportTests(unittest.TestCase):
    def setUp(self):
        self.w = World(4)
        self.p = self.w.join("A")
        self.lvl = self.w.levels[1]

    def drink(self):
        self.p.pack.append(make_item("teleportation"))
        self.w.submit(self.p, {"a": "use", "slot": len(self.p.pack) - 1})
        self.w.advance(1)

    def test_spawns_on_any_floor(self):
        t = ITEMS["teleportation"]
        self.assertEqual(t["depths"][0], 1)
        seen = set()
        for seed in range(30):
            w = World(seed)
            for depth in (1, 15, 60):
                if any(i.kind == "teleportation" for i in w.level(depth).items.values()):
                    seen.add(depth)
        self.assertEqual(seen, {1, 15, 60})

    def test_lands_far_away_on_open_floor(self):
        for _ in range(40):
            walk = self.lvl.distances_to(self.p.x, self.p.y)
            before = (self.p.x, self.p.y)
            self.w.teleport(self.p)
            spot = (self.p.x, self.p.y)
            self.assertNotEqual(spot, before)
            self.assertGreaterEqual(walk[spot], TELEPORT_STEPS * 2)
            self.assertTrue(self.lvl.walkable[spot])
            self.assertIs(self.lvl.occupant[spot], self.p)

    def test_reaches_all_over_the_floor(self):
        spots = set()
        for _ in range(60):
            self.w.teleport(self.p)
            spots.add((self.p.x // 20, self.p.y // 10))
        self.assertGreater(len(spots), 4)

    def test_the_potion_is_used_up(self):
        self.drink()
        self.assertEqual(self.p.pack, [])
        self.assertIn(f"you're on floor {self.p.depth}!", str(self.w.drain_outbox()))

    def test_never_into_a_locked_room(self):
        w = World(5)
        w.locked_rooms = {1: LockedRoom(1, 3, "red")}
        p = w.join("A")
        lvl = w.levels[1]
        for _ in range(200):
            w.teleport(p)
            self.assertFalse(lvl.vault[p.x, p.y])

    def test_never_onto_water_pits_or_lava(self):
        for seed in range(6):
            w = World(seed)
            p = w.join("A")
            w.warp(p, 52)
            for _ in range(30):
                w.teleport(p)
                self.assertTrue(WALKABLE[w.levels[52].tiles[p.x, p.y]])

    def test_it_stops_a_held_direction(self):
        self.p.hold = (1, 0)
        self.w.teleport(self.p)
        self.assertIsNone(self.p.hold)

    def test_picks_up_what_you_land_on(self):
        self.p.gold = 0
        for c in list(self.lvl.floor_cells):
            if c not in self.lvl.occupant:
                self.lvl.items[c] = make_item("healing")
        self.w.teleport(self.p)
        self.assertEqual(self.p.pack[0].kind, "healing")

    def test_a_blink_is_shown(self):
        self.w.drain_outbox()
        self.w.teleport(self.p)
        fx = [m for _, m in self.w.drain_outbox() if m["t"] == "fx"]
        self.assertEqual(fx[0]["kind"], "blink")
        v = ClientView()
        v.apply(fx[0])
        self.assertEqual(len(v.bolts), 1)


if __name__ == "__main__":
    unittest.main()
