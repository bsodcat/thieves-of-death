"""Shared setup for the 2.10 tests: an empty first floor with an open patch cleared in it."""
from game import protocol
from game.constants import MAP_H, MAP_W
from game.entities import make_monster
from game.render import ClientView
from game.tiles import FLOOR
from game.world import World


def empty_world(seed=1, names=("Alice",)):
    w = World(seed)
    lvl = w.level(1)
    for m in list(lvl.monsters):
        lvl.remove(m)
    lvl.monsters.clear()
    lvl.items.clear()
    for npc in list(lvl.npcs):
        lvl.remove(npc)
    lvl.npcs.clear()
    return (w, lvl, *[w.join(n) for n in names])


def open_spot(lvl, reach=3):
    """The middle of a square of bare floor, `reach` tiles out each way, cleared away from the stairs
    so nothing in it gets in the way of a test."""
    stairs = (lvl.up, lvl.down, lvl.up_front, lvl.down_front)
    centers = [(x, y) for x in range(reach + 2, MAP_W - reach - 2, 3) for y in range(reach + 2, MAP_H - reach - 2, 3)]
    x, y = max(centers, key=lambda c: (min(max(abs(c[0] - s[0]), abs(c[1] - s[1])) for s in stairs), c))
    for cx in range(x - reach - 1, x + reach + 2):
        for cy in range(y - reach - 1, y + reach + 2):
            if lvl.tiles[cx, cy] != FLOOR:
                lvl._set_tile(cx, cy, FLOOR)
            lvl.mainland[cx, cy] = True
            lvl.items.pop((cx, cy), None)
    lvl.land_cells = sorted(set(lvl.land_cells) | {(cx, cy) for cx in range(x - reach - 1, x + reach + 2)
                                                   for cy in range(y - reach - 1, y + reach + 2)})
    lvl._paths.clear()
    return x, y


def put(lvl, a, x, y):
    if lvl.occupant.get((a.x, a.y)) is a:
        lvl.move(a, x, y)
    else:
        lvl.place(a, x, y)


def add(w, lvl, kind, x, y, state="hunting", target=None):
    m = make_monster(kind, next(w._ids))
    m.state = state
    lvl.place(m, x, y)
    lvl.monsters.append(m)
    if target is not None:
        m.target_id, m.last_seen = target.id, (target.x, target.y)
    return m


def said(w):
    return " ".join(m["text"] for _, m in w.drain_outbox() if m["t"] == "msg")


def logged(w):
    return " ".join(m.get("line", "") for m in w.drain_ledger())


def view_of(w, p):
    v = ClientView()
    v.apply({"t": "welcome", "id": p.id, "name": p.name})
    for msg in (w.level_msg(p.depth), w.pack_msg(p), w.state_for(p)):
        v.apply(protocol.decode(protocol.encode(msg)))
    return v


def deliver(w, v, pid):
    for to, msg in w.drain_outbox():
        if to in (None, pid):
            v.apply(protocol.decode(protocol.encode(msg)))


def seconds(s):
    from game.constants import TICKS_PER_SECOND
    return int(s * TICKS_PER_SECOND)
