"""Auto-walking: routes, what they're allowed to know, and how the view uses them."""
import unittest

import numpy as np

from game import pathing, protocol
from game.constants import MAP_H, MAP_W
from game.entities import make_monster
from game.render import ClientView
from game.tiles import STAIRS_DOWN, STAIRS_UP, WALKABLE
from game.world import World


def grid(*rows):
    """A walkable map from strings: . is floor, # is wall. rows[y][x]."""
    return np.array([[rows[y][x] == "." for y in range(len(rows))] for x in range(len(rows[0]))])


def walk(walkable, start, goal, limit=100, **kwargs):
    """Follows next_step, checking each step is legal, and returns where it ended."""
    pos, steps = start, 0
    while steps < limit:
        step = pathing.next_step(walkable, pos, goal, **kwargs)
        if step is None:
            return pos, steps
        nx, ny = pos[0] + step[0], pos[1] + step[1]
        if (nx, ny) == goal and not walkable[goal]:
            return goal, steps + 1
        assert walkable[nx, ny], (pos, step)
        if step[0] and step[1]:
            assert walkable[nx, pos[1]] and walkable[pos[0], ny], "cut a corner"
        pos, steps = (nx, ny), steps + 1
    raise AssertionError("never arrived")


class RouteTests(unittest.TestCase):
    def test_straight_line(self):
        w = grid(".....")
        self.assertEqual(pathing.next_step(w, (0, 0), (4, 0)), (1, 0))
        self.assertEqual(walk(w, (0, 0), (4, 0)), ((4, 0), 4))

    def test_diagonal_when_its_shorter(self):
        w = grid("....", "....", "....", "....")
        self.assertEqual(walk(w, (0, 0), (3, 3)), ((3, 3), 3))

    def test_already_there(self):
        self.assertIsNone(pathing.next_step(grid("..."), (1, 0), (1, 0)))

    def test_around_a_wall(self):
        w = grid(".....",
                 ".###.",
                 ".....")
        self.assertEqual(walk(w, (2, 0), (2, 2))[0], (2, 2))

    def test_through_a_gap(self):
        w = grid("..#..",
                 "..#..",
                 ".....",
                 "..#..")
        self.assertEqual(walk(w, (0, 0), (4, 0))[0], (4, 0))

    def test_never_cuts_a_corner(self):
        w = grid("..#",
                 "#..",
                 "...")
        self.assertEqual(walk(w, (0, 0), (2, 1))[0], (2, 1))
        corner = grid(".#",
                      "..")
        self.assertEqual(pathing.next_step(corner, (0, 0), (1, 1)), (0, 1))

    def test_unreachable_goes_as_close_as_it_can(self):
        w = grid("..#..")
        self.assertEqual(walk(w, (0, 0), (4, 0))[0], (1, 0))

    def test_stays_put_when_already_closest(self):
        self.assertIsNone(pathing.next_step(grid("..#.."), (1, 0), (4, 0)))

    def test_walks_around_blockers(self):
        w = grid("...",
                 "...",
                 "...")
        self.assertEqual(walk(w, (0, 1), (2, 1), blocked={(1, 1)})[0], (2, 1))

    def test_goal_can_hold_a_monster(self):
        w = grid("...")
        self.assertEqual(pathing.next_step(w, (1, 0), (2, 0), blocked={(2, 0)}), (1, 0))

    def test_stairs_need_permission(self):
        w = grid("...#")
        self.assertEqual(walk(w, (0, 0), (3, 0), enter_goal=True)[0], (3, 0))
        self.assertEqual(walk(w, (0, 0), (3, 0))[0], (2, 0))

    def test_every_real_level_route_is_legal(self):
        w = World(4)
        lvl = w.level(1)
        for goal in lvl.floor_cells[::40]:
            end, _ = walk(lvl.walkable, lvl.up_front, goal, limit=300)
            self.assertEqual(end, goal)


def setup_world():
    w = World(1)
    lvl = w.level(1)
    for m in list(lvl.monsters):
        lvl.remove(m)
    lvl.monsters.clear()
    lvl.items.clear()
    return w, lvl, w.join("Alice")


def view_of(w, p):
    v = ClientView()
    v.apply({"t": "welcome", "id": p.id, "name": p.name})
    for msg in (w.level_msg(p.depth), w.pack_msg(p), w.state_for(p)):
        v.apply(protocol.decode(protocol.encode(msg)))
    return v


def refresh(v, w, p):
    v.apply(protocol.decode(protocol.encode(w.state_for(p))))
    if p.needs_level:
        v.apply(protocol.decode(protocol.encode(w.level_msg(p.depth))))
        v.apply(protocol.decode(protocol.encode(w.state_for(p))))
        p.needs_level = False


class ViewTests(unittest.TestCase):
    def test_walks_to_a_seen_tile_through_the_real_server(self):
        w, lvl, a = setup_world()
        v = view_of(w, a)
        goal = max((c for c in lvl.floor_cells if w.fov(a)[c]), key=lambda c: abs(c[0] - a.x) + abs(c[1] - a.y))
        for _ in range(60):
            step = v.walk_step(*goal)
            if step is None:
                break
            w.submit(a, {"a": "hold", "dx": step[0], "dy": step[1], "press": True})
            w.advance(100)
            refresh(v, w, a)
        self.assertEqual((a.x, a.y), goal)

    def test_stops_on_arrival(self):
        w, lvl, a = setup_world()
        self.assertIsNone(view_of(w, a).walk_step(a.x, a.y))

    def test_dead_players_dont_walk(self):
        w, lvl, a = setup_world()
        w._kill(a, make_monster("rat", 800))
        self.assertIsNone(view_of(w, a).walk_step(1, 1))

    def test_unseen_floor_isnt_used_for_routes(self):
        w, lvl, a = setup_world()
        v = view_of(w, a)
        v.seen[1][:] = False
        v.seen[1][a.x, a.y] = True
        goal = next(c for c in lvl.floor_cells if c != (a.x, a.y))
        self.assertIsNone(v.walk_step(*goal))    # knows of nowhere to go

    def test_unseen_stairs_cant_be_entered(self):
        w, lvl, a = setup_world()
        v = view_of(w, a)
        lvl.move(a, *lvl.down_front)
        refresh(v, w, a)
        v.seen[1][lvl.down] = False
        self.assertIsNone(v.walk_step(*lvl.down))

    def test_walks_into_seen_stairs(self):
        w, lvl, a = setup_world()
        lvl.move(a, *lvl.down_front)
        v = view_of(w, a)
        self.assertEqual(v.walk_step(*lvl.down), (lvl.down[0] - a.x, lvl.down[1] - a.y))

    def test_wont_push_at_the_sealed_way_out_on_floor_one(self):
        w, lvl, a = setup_world()
        lvl.move(a, *lvl.up_front)
        self.assertIsNone(view_of(w, a).walk_step(*lvl.up))

    def test_can_go_back_up_from_deeper_floors(self):
        w, lvl, a = setup_world()
        lower = w.level(2)
        lvl.remove(a)
        lower.place(a, *lower.up_front)
        self.assertEqual(lower.tiles[lower.up], STAIRS_UP)
        a.needs_level = True
        v = view_of(w, a)
        self.assertEqual(v.walk_step(*lower.up), (lower.up[0] - a.x, lower.up[1] - a.y))

    def test_targeting_a_monster_attacks_it(self):
        w, lvl, a = setup_world()
        spot = next(c for c in lvl.floor_cells if max(abs(c[0] - a.x), abs(c[1] - a.y)) == 1 and w.fov(a)[c]
                    and not lvl.diagonal_blocked(a.x, a.y, *c) and c not in lvl.occupant)
        rat = make_monster("rat", 900)
        rat.hp = 99
        lvl.place(rat, *spot)
        lvl.monsters.append(rat)
        step = view_of(w, a).walk_step(*spot)
        self.assertEqual(step, (spot[0] - a.x, spot[1] - a.y))
        w.submit(a, {"a": "hold", "dx": step[0], "dy": step[1], "press": True})
        self.assertLess(rat.hp, 99)

    def test_routes_around_a_monster_in_the_way(self):
        w = World(1)
        open_room = np.ones((MAP_W, MAP_H), dtype=bool)
        self.assertEqual(pathing.next_step(open_room, (1, 1), (3, 1), blocked={(2, 1)})[0], 1)

    def test_bones_dont_block_the_way(self):
        w = World(1, mode="Revive")
        lvl = w.level(1)
        for m in list(lvl.monsters):
            lvl.remove(m)
        lvl.monsters.clear()
        a, b = w.join("A"), w.join("B")
        spot = (b.x, b.y)
        w._kill(b, make_monster("rat", 800))
        v = view_of(w, a)
        self.assertEqual(v.walk_step(*spot), (spot[0] - a.x, spot[1] - a.y))


if __name__ == "__main__":
    unittest.main()
