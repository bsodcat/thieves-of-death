"""The Look panel: pointing the mouse at the map to identify what's there."""
import unittest

import numpy as np

from game import protocol
from game.constants import LOOK_Y, MAP_H, MAP_W, MAP_X, MAP_Y, SCREEN_H, SCREEN_W, SIDEBAR_W
from game.entities import MONSTERS, make_monster
from game.items import ITEMS, make_gold, make_item
from game.render import HOVER_BG, ClientView
from game.tiles import DESCRIPTIONS, DOOR, NAMES, WALL
from game.world import World


def setup_world(mode="Classic", names=("Alice",)):
    w = World(1, mode=mode)
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


def texts(lines):
    return " ".join(t for t, _ in lines)


def look_area(v):
    frame = v.draw()
    return "\n".join("".join(chr(c) for c in frame["ch"][:SIDEBAR_W, y]).rstrip() for y in range(LOOK_Y, SCREEN_H))


def nearby_floor(lvl, w, p):
    return next(c for c in lvl.floor_cells if w.fov(p)[c] and c != (p.x, p.y) and c not in lvl.occupant)


def point(v, x, y):
    v.mouse = (MAP_X + x, MAP_Y + y)


class TileTests(unittest.TestCase):
    def test_every_tile_has_a_name_and_description(self):
        self.assertEqual(len(NAMES), len(DESCRIPTIONS))
        self.assertTrue(all(DESCRIPTIONS))

    def test_floor_and_wall(self):
        w, lvl, a = setup_world()
        v = view_of(w, a)
        floor = nearby_floor(lvl, w, a)
        self.assertIn("Floor", texts(v.describe(*floor)))
        wall = next((x, y) for x in range(MAP_W) for y in range(MAP_H) if lvl.tiles[x, y] == WALL and w.fov(a)[x, y])
        self.assertIn("Granite wall", texts(v.describe(*wall)))

    def test_stairs_explain_themselves(self):
        w, lvl, a = setup_world()
        lvl.move(a, *lvl.down_front)
        self.assertIn("go deeper", texts(view_of(w, a).describe(*lvl.down)))
        lvl.move(a, *lvl.up_front)
        self.assertIn("go back up", texts(view_of(w, a).describe(*lvl.up)))

    def test_doors_explain_themselves(self):
        w, lvl, a = setup_world()
        door = next(((x, y) for x in range(MAP_W) for y in range(MAP_H) if lvl.tiles[x, y] == DOOR))
        v = view_of(w, a)
        v.seen[1][door] = True
        self.assertIn("Blocks sight", texts(v.describe(*door)))

    def test_unexplored_gives_nothing_away(self):
        w, lvl, a = setup_world()
        v = view_of(w, a)
        hidden = next((x, y) for x in range(MAP_W) for y in range(MAP_H) if not v.seen[1][x, y])
        self.assertEqual(v.describe(*hidden)[0][0], "Unexplored")
        for x, y in [lvl.down, *lvl.floor_cells]:
            if not v.seen[1][x, y]:
                self.assertNotIn("stair", texts(v.describe(x, y)).lower())

    def test_monsters_out_of_sight_stay_hidden(self):
        w, lvl, a = setup_world()
        spot = next(c for c in lvl.floor_cells if not w.fov(a)[c])
        rat = make_monster("rat", 900)
        lvl.place(rat, *spot)
        lvl.monsters.append(rat)
        v = view_of(w, a)
        self.assertNotIn("Rat", texts(v.describe(*spot)))

    def test_remembered_tile_is_marked(self):
        w, lvl, a = setup_world()
        v = view_of(w, a)
        floor = nearby_floor(lvl, w, a)
        v.visible[floor] = False
        self.assertIn("As you remember it", texts(v.describe(*floor)))


class ActorTests(unittest.TestCase):
    def monster(self, kind, state):
        w, lvl, a = setup_world()
        spot = nearby_floor(lvl, w, a)
        m = make_monster(kind, 900)
        m.state = state
        lvl.place(m, *spot)
        lvl.monsters.append(m)
        return view_of(w, a), spot

    def test_every_monster_has_a_description(self):
        self.assertTrue(all(t.get("desc") for t in MONSTERS.values()))

    def test_monster_details(self):
        v, spot = self.monster("goblin", "hunting")
        text = texts(v.describe(*spot))
        for part in ("Goblin", "Health 15/15", "Hunting you", "Hits for 2-5"):
            self.assertIn(part, text)

    def test_monster_states_read_plainly(self):
        v, spot = self.monster("rat", "sleeping")
        self.assertIn("Asleep", texts(v.describe(*spot)))
        v, spot = self.monster("rat", "wandering")
        self.assertIn("Wandering", texts(v.describe(*spot)))

    def test_speed_is_mentioned(self):
        v, spot = self.monster("jackal", "wandering")
        self.assertIn("Fast.", texts(v.describe(*spot)))
        v, spot = self.monster("ogre", "wandering")
        self.assertIn("Slow hits.", texts(v.describe(*spot)))

    def test_yourself_and_teammates(self):
        w, lvl, a, b = setup_world(names=("Alice", "Bob"))
        v = view_of(w, a)
        self.assertIn("You", texts(v.describe(a.x, a.y)))
        self.assertIn("Bob", texts(v.describe(b.x, b.y)))
        self.assertIn("Health 40/40", texts(v.describe(b.x, b.y)))

    def test_teammate_sensed_through_walls(self):
        w, lvl, a, b = setup_world(names=("Alice", "Bob"))
        spot = next(c for c in lvl.floor_cells if not w.fov(a)[c])
        lvl.move(b, *spot)
        self.assertIn("Bob", texts(view_of(w, a).describe(*spot)))

    def test_bones(self):
        w, lvl, a, b = setup_world("Revive", ("Alice", "Bob"))
        spot = (a.x, a.y)
        w._kill(a, make_monster("rat", 800))
        text = texts(view_of(w, b).describe(*spot))
        self.assertIn("Alice's bones", text)
        self.assertIn("revive them", text)
        self.assertIn("Your bones", texts(view_of(w, a).describe(*spot)))


class ItemTests(unittest.TestCase):
    def item_view(self, item):
        w, lvl, a = setup_world()
        spot = nearby_floor(lvl, w, a)
        lvl.items[spot] = item
        return view_of(w, a), spot

    def test_weapons_and_armor_show_stats_and_how_to_get_them(self):
        v, spot = self.item_view(make_item("sword"))
        text = texts(v.describe(*spot))
        self.assertIn("Sword", text)
        self.assertIn("Dmg 5-9, noise 15", text)
        self.assertIn("press g", text)

    def test_potions_say_they_collect_themselves(self):
        v, spot = self.item_view(make_item("healing"))
        text = texts(v.describe(*spot))
        self.assertIn("Heals 20", text)
        self.assertIn("Walk over it", text)

    def test_gold(self):
        v, spot = self.item_view(make_gold(37))
        text = texts(v.describe(*spot))
        self.assertIn("37 gold", text)
        self.assertIn("Walk over it", text)

    def test_remembered_item(self):
        v, spot = self.item_view(make_item("sword"))
        v.visible[spot] = False
        self.assertIn("As you remember it", texts(v.describe(*spot)))

    def test_player_standing_on_an_item_shows_both(self):
        w, lvl, a = setup_world()
        lvl.items[(a.x, a.y)] = make_item("sword")
        text = texts(view_of(w, a).describe(a.x, a.y))
        self.assertIn("You", text)
        self.assertIn("Sword", text)


class SidebarListTests(unittest.TestCase):
    def test_asleep_sits_on_the_health_bar_so_long_names_fit(self):
        w, lvl, a = setup_world()
        rat = make_monster("rat", 900)
        rat.state = "sleeping"
        lvl.place(rat, *nearby_floor(lvl, w, a))
        lvl.monsters.append(rat)
        frame = view_of(w, a).draw()
        sidebar = "\n".join("".join(chr(c) for c in frame["ch"][:SIDEBAR_W, y]) for y in range(LOOK_Y))
        self.assertIn("r rat", sidebar)
        self.assertIn("asleep", sidebar)
        self.assertNotIn("(asleep)", sidebar)


class PanelTests(unittest.TestCase):
    def test_reserved_area_is_at_the_bottom_left(self):
        self.assertEqual(SCREEN_H - LOOK_Y, 10)

    def test_hint_until_the_mouse_is_over_the_map(self):
        w, lvl, a = setup_world()
        v = view_of(w, a)
        area = look_area(v)
        self.assertIn("Look", area)
        self.assertIn("Point the mouse", area)
        v.mouse = (2, 2)                       # over the sidebar
        self.assertIn("Point the mouse", look_area(v))
        self.assertIsNone(v.hovered())

    def test_map_edges(self):
        v = ClientView()
        for mouse, expected in (((MAP_X, MAP_Y), (0, 0)), ((MAP_X + MAP_W - 1, MAP_Y + MAP_H - 1), (MAP_W - 1, MAP_H - 1)),
                                ((MAP_X - 1, MAP_Y), None), ((MAP_X + MAP_W, MAP_Y), None),
                                ((MAP_X, MAP_Y - 1), None), ((MAP_X, MAP_Y + MAP_H), None)):
            v.mouse = mouse
            self.assertEqual(v.hovered(), expected)

    def test_hover_highlights_the_tile(self):
        w, lvl, a = setup_world()
        v = view_of(w, a)
        floor = nearby_floor(lvl, w, a)
        point(v, *floor)
        frame = v.draw()
        self.assertEqual(tuple(frame["bg"][MAP_X + floor[0], MAP_Y + floor[1]]), HOVER_BG)
        self.assertIn("Floor", look_area(v))

    def test_pointing_everywhere_never_breaks(self):
        w, lvl, a = setup_world()
        v = view_of(w, a)
        for x in range(MAP_W):
            for y in range(MAP_H):
                self.assertTrue(v.describe(x, y))
        for x in range(SCREEN_W):
            v.mouse = (x, MAP_Y)
            self.assertEqual(v.draw().shape, (SCREEN_W, SCREEN_H))

    def test_before_the_map_arrives(self):
        v = ClientView()
        v.mouse = (MAP_X, MAP_Y)
        self.assertEqual(v.draw().shape, (SCREEN_W, SCREEN_H))

    def test_longest_descriptions_fit_the_panel(self):
        limit = SCREEN_H - LOOK_Y - 1
        import textwrap
        for t in MONSTERS.values():
            line = f"{t['desc']} Hits for {t['damage'][0]}-{t['damage'][1]}. Fast. Slow hits."
            self.assertLessEqual(3 + len(textwrap.wrap(line, SIDEBAR_W - 2)), limit, t["name"])
        for kind in ITEMS:
            item = make_item(kind)
            rows = 1 + len(textwrap.wrap(item.info, SIDEBAR_W - 2)) + 2
            self.assertLessEqual(rows, limit, kind)

    def test_full_party_and_a_crowd_leave_the_panel_clear(self):
        w = World(1)
        lvl = w.level(1)
        ps = [w.join(f"Player{i}") for i in range(6)]
        v = view_of(w, ps[0])
        v.ents += [{"id": 1000 + i, "g": "r", "c": [160, 130, 110], "x": 2, "y": 2 + i, "name": "rat", "hp": 6,
                    "mhp": 6, "p": False, "seen": True, "st": "wandering"} for i in range(20)]
        frame = v.draw()
        heading = "".join(chr(c) for c in frame["ch"][:SIDEBAR_W, LOOK_Y]).rstrip()
        self.assertEqual(heading.strip(), "Look")
        above = "".join(chr(c) for c in frame["ch"][:SIDEBAR_W, LOOK_Y - 1]).strip()
        self.assertEqual(above, "")
        self.assertTrue(np.all(frame["bg"][:SIDEBAR_W, LOOK_Y] == (14, 14, 22)))


if __name__ == "__main__":
    unittest.main()
