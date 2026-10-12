#!/usr/bin/env python3
"""Panel visualizer: a 3-D model, an as-built wiring diagram, a step-by-step wiring guide and a wire cut list for a
backplate or control panel, all from one JSON spec. Stdlib only.

    python3 build_panel.py panel.json                # check, route every wire, write panel-build/
    python3 build_panel.py panel.json -o out/        # write somewhere else
    python3 build_panel.py panel.json --check        # checks and routes only; writes nothing
    python3 build_panel.py panel.json --wires relay  # cut list as a markdown table (filter by part id or wire number)
    python3 build_panel.py --init my-panel.json      # start a new spec from the minimal example

Frame: origin at the plate's bottom-left corner, x right, y up, z out of the plate's front face (z = 0 on the face).
Units mm. The spec format is in ../references/spec.md.

One wire list feeds every view: the 3-D harness, the as-built diagram, the step pictures and the cut list. Every wire is
routed through the open gaps between the parts (never over a device), and its cut length is the route plus slack and an
allowance for the two terminations.
"""
import argparse, base64, collections, csv, heapq, html, io, json, math, os, re, shutil, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
TEMPLATE = os.path.join(SKILL, "assets", "page.html")
STARTER = os.path.join(SKILL, "examples", "minimal.json")

COLOURS = dict(red="#d4312a", black="#2a2d31", white="#f2f2ef", green="#1f8a3a", yellow="#e3b505", blue="#1f63d6",
               brown="#7b4a2a", grey="#8a8f94", gray="#8a8f94", orange="#e8742a", purple="#7a4fd1", violet="#7a4fd1",
               pink="#e36fa8", copper="#b87333", coax="#3b3f44", tan="#c9a66b")
GROUP_PALETTE = ["#e0794a", "#2bb3a3", "#e8a317", "#8a6fe0", "#b87333", "#4f8fe0", "#d45d8c", "#7a9a3a"]
EXITS = {"up": [(0, 1)], "down": [(0, -1)], "left": [(-1, 0)], "right": [(1, 0)], "updown": [(0, 1), (0, -1)],
         "leftright": [(-1, 0), (1, 0)], "any": [(0, 1), (0, -1), (-1, 0), (1, 0)]}
OUTER = 4.0           # the ring of channels just outside the plate's edges, along the box walls
BEND = 12.0           # routing cost of a bend, in mm: keeps routes to a few clean turns
LIFT = 110.0          # how far Explode lifts a part with explode = 1


class SpecError(Exception):
    pass


def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()

def read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()

def write_text(path, text, newline=None):
    with open(path, "w", encoding="utf-8", newline=newline) as f:
        f.write(text)


def fnum(v, what):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise SpecError(f"{what} must be a number, not {v!r}")
    return float(v)


# ---------------------------------------------------------------- spec: parts and their terminals
TERM_RE = re.compile(r"\s*(top|bottom|left|right|face)\s*@\s*(-?[\d.]+)(?:\s*,\s*(-?[\d.]+))?\s*(?:>\s*([a-z]+))?\s*$")

def parse_terminal(raw, p, name):
    """A terminal in part-local coordinates: x, y from the part's bottom-left corner (a wall item's centre), z out from
    the plate's face, the way its wire leaves (exit) and the label used in wire names."""
    t = {"at": raw} if isinstance(raw, str) else dict(raw)
    w, h = p.get("w", 0.0), p.get("h", 0.0)
    wall = p["mount"] == "wall"
    side, ex, dflt = None, None, "any"
    if "at" in t:
        m = TERM_RE.match(str(t["at"]))
        if not m:
            raise SpecError(f"{p['id']}.{name}: can't read terminal position {t['at']!r} (try 'bottom@30' or 'face@9,10>down')")
        side, a, b, ex = m.groups()
        a = float(a)
        if side == "face":
            if b is None:
                raise SpecError(f"{p['id']}.{name}: 'face@' needs two numbers, x,y")
            x, y = a, float(b)
        else:
            x, y, dflt = {"bottom": (a, -2.0, "down"), "top": (a, h + 2.0, "up"), "left": (-2.0, a, "left"),
                          "right": (w + 2.0, a, "right")}[side]
    else:
        if "x" not in t or "y" not in t:
            raise SpecError(f"{p['id']}.{name}: a terminal needs 'at' or x and y")
        x, y = fnum(t["x"], f"{p['id']}.{name}.x"), fnum(t["y"], f"{p['id']}.{name}.y")
    if wall:
        z, dflt = p["z"], p["_exit"]
    elif side in (None, "face"):
        z = p["z0"] + p["d"] + 2.0
    else:
        z = p["z0"] + p["d"] / 2
    if t.get("z") is not None:
        z = fnum(t["z"], f"{p['id']}.{name}.z")
    ex = t.get("exit") or ex or dflt
    if ex not in EXITS:
        raise SpecError(f"{p['id']}.{name}: exit must be one of {', '.join(EXITS)}, not {ex!r}")
    return dict(name=name, x=x, y=y, z=z, exit=ex, label=t.get("label", name))


def norm_parts(spec, W, H):
    parts = {}
    for raw in spec.get("parts", []):
        p = dict(raw)
        pid = p.get("id")
        if not pid or not isinstance(pid, str) or "." in pid:
            raise SpecError(f"every part needs an id without dots (got {pid!r})")
        if pid in parts:
            raise SpecError(f"two parts are called {pid!r}")
        p.setdefault("name", pid)
        p.setdefault("mount", "plate")
        if p["mount"] not in ("plate", "wall"):
            raise SpecError(f"{pid}: mount must be 'plate' or 'wall'")
        p["x"], p["y"] = fnum(p.get("x"), f"{pid}.x"), fnum(p.get("y"), f"{pid}.y")
        if p["mount"] == "wall":
            p.setdefault("r", 6.0); p.setdefault("len", 16.0); p.setdefault("z", 35.0)
            x, y = p["x"], p["y"]
            p["_axis"] = p.get("axis") or ("x" if x < 0 or x > W else "y" if y < 0 or y > H else "z")
            p["_exit"] = p.get("exit") or ("right" if x < 0 else "left" if x > W else "up" if y < 0 else "down" if y > H else "any")
            p.setdefault("color", "#3b3f44")
            p.setdefault("explode", 0.0)
            p["w"] = p["h"] = 0.0
        else:
            for k in ("w", "h", "d"):
                p[k] = fnum(p.get(k), f"{pid}.{k}")
            p["z0"] = fnum(p.get("z0", 0.0), f"{pid}.z0")
            p.setdefault("color", "#3a3d42")
            p.setdefault("explode", 1.0)
            p["room"] = [float(v) for v in p.get("room", [0, 0, 0, 0])]
            if len(p["room"]) != 4:
                raise SpecError(f"{pid}.room is [left, right, below, above]")
        p["holes"] = [list(hl) for hl in p.get("holes", [])]
        terms = collections.OrderedDict()
        bb = p.get("busbar")
        if bb:
            n, pitch = int(bb.get("screws", 6)), float(bb.get("pitch", 9.0))
            stud = bb.get("studs", p["w"] / 2 - 10.0)
            sgn = -1 if bb.get("a_end", "left") == "left" else 1
            cx, cy = p["w"] / 2, p["h"] / 2
            zt = p["z0"] + min(p["d"], 14.0)
            lug = {"up": "up", "down": "down"}.get(bb.get("lugs", "both"), "updown")
            if stud:
                terms["A"] = dict(name="A", x=cx + sgn * stud, y=cy, z=zt, exit="left" if sgn < 0 else "right", label="stud A")
                terms["B"] = dict(name="B", x=cx - sgn * stud, y=cy, z=zt, exit="right" if sgn < 0 else "left", label="stud B")
            for i in range(n):
                terms[str(i + 1)] = dict(name=str(i + 1), x=cx + sgn * ((n - 1) / 2 - i) * pitch, y=cy, z=zt, exit=lug,
                                         label=f"screw {i + 1}")
        for s in p.get("strips", []):
            names = [str(v) for v in s["names"]]
            at = s.get("at") or [s.get("start", 5.0) + i * s.get("pitch", 5.0) for i in range(len(names))]
            if len(at) != len(names):
                raise SpecError(f"{pid}: a strip has {len(names)} names but {len(at)} positions")
            for nm, a in zip(names, at):
                lab = s.get("label", "{n}").replace("{n}", nm)
                terms[nm] = parse_terminal({"at": f"{s.get('edge', 'bottom')}@{a}", "z": s.get("z"), "exit": s.get("exit"),
                                            "label": lab}, p, nm)
        for nm, raw_t in p.get("terminals", {}).items():
            terms[str(nm)] = parse_terminal(raw_t, p, str(nm))
        p["_terms"] = terms
        parts[pid] = p
    for p in parts.values():
        if p.get("in") and p["in"] not in parts:
            raise SpecError(f"{p['id']} is 'in' {p['in']!r}, which isn't a part")
    return parts


# ---------------------------------------------------------------- checks
def rect(p):
    return (p["x"], p["y"], p["w"], p["h"])

def overlap(a, b, gap=0.0):
    return not (a[0] + a[2] + gap <= b[0] or b[0] + b[2] + gap <= a[0] or a[1] + a[3] + gap <= b[1] or b[1] + b[3] + gap <= a[1])

def rooms_sided(p):
    l, r, bo, t = p["room"]
    ox, oy, ow, oh = rect(p)
    zs = ((ox - l, oy, l, oh), (ox + ow, oy, r, oh), (ox, oy - bo, ow, bo), (ox, oy + oh, ow, t))
    return [(z, s) for z, s in zip(zs, ("left of", "right of", "below", "above")) if z[2] > 0 and z[3] > 0]

def rooms(p):
    return [z for z, _ in rooms_sided(p)]

def related(a, b):
    return a.get("in") == b["id"] or b.get("in") == a["id"]

def clearance(a, b):
    """Clear distance between two footprints (0 if they touch or overlap)."""
    dx = max(b[0] - (a[0] + a[2]), a[0] - (b[0] + b[2]), 0.0)
    dy = max(b[1] - (a[1] + a[3]), a[1] - (b[1] + b[3]), 0.0)
    return math.hypot(dx, dy) if dx and dy else max(dx, dy)

def off_plate(r, W, H):
    """How far a rectangle runs off each side of the plate, as words; empty if it doesn't."""
    over = [(-r[0], "left"), (r[0] + r[2] - W, "right"), (-r[1], "bottom"), (r[1] + r[3] - H, "top")]
    return ", ".join(f"{v:.1f} mm off the {s}" for v, s in over if v > 0.01)

def check_layout(spec, parts, W, H):
    problems = []
    gap = float(spec.get("gap", 0))
    flat = [p for p in parts.values() if p["mount"] == "plate"]
    for i, a in enumerate(flat):
        ra = rect(a)
        if off_plate(ra, W, H):
            problems.append(f"{a['id']} runs off the plate: {off_plate(ra, W, H)}")
        bb = a.get("busbar")
        if bb and bb.get("studs", a["w"] / 2 - 10.0):
            stud, last = float(bb.get("studs", a["w"] / 2 - 10.0)), (int(bb.get("screws", 6)) - 1) / 2 * float(bb.get("pitch", 9.0))
            if stud - last < 8.0:
                problems.append(f"{a['id']}: its studs sit {stud - last:.1f} mm from its end screws (screws are centred, "
                                f"{bb.get('pitch', 9.0)} mm apart); move the studs out or use fewer screws")
            if stud > a["w"] / 2 - 3.0:
                problems.append(f"{a['id']}: its studs ({stud:g} mm from the centre) are off the end of a {a['w']:g} mm bar")
        if a.get("in"):
            continue
        for b in flat[i + 1:]:
            if b.get("in") or related(a, b):
                continue
            stacked = a["z0"] >= b["z0"] + b["d"] or b["z0"] >= a["z0"] + a["d"]
            if stacked:
                continue
            if overlap(ra, rect(b), -0.01):
                problems.append(f"{a['id']} and {b['id']} collide (stack one on spacers with z0, or move it)")
                continue
            g = min(a.get("gap", gap), b.get("gap", gap))
            if g > 0 and overlap(ra, rect(b), g - 0.01):
                problems.append(f"{a['id']} and {b['id']} are {clearance(ra, rect(b)):.1f} mm apart; they need {g:g} mm")
        for z, side in rooms_sided(a):
            if off_plate(z, W, H):
                problems.append(f"{a['id']}'s wiring room {side} it runs off the plate: {off_plate(z, W, H)}")
            for b in flat:
                if b is a or b.get("in") or related(a, b):
                    continue
                if b["z0"] + b["d"] <= a["z0"] - 4:     # entirely under a raised part: its wiring room is above b
                    continue
                if overlap(z, rect(b), -0.01):
                    problems.append(f"{b['id']} sits in {a['id']}'s wiring room")
    for ln in spec.get("lanes", []):
        lr = (ln["x"], ln["y"], ln["w"], ln["h"])
        for p in flat:
            if p["id"] not in ln.get("allow", []) and not p.get("in") and overlap(lr, rect(p), -0.01):
                problems.append(f"{p['id']} sits in the wiring lane {ln.get('label', '')!r}".replace(" ''", ""))
    return problems


# ---------------------------------------------------------------- routing: channels in the gaps, then Dijkstra
def build_channels(spec, parts, W, H):
    flat = [p for p in parts.values() if p["mount"] == "plate"]
    walls = [p for p in parts.values() if p["mount"] == "wall"]
    gap = float(spec.get("gap", 0)) or 16.0
    x_lo = min([-OUTER] + [p["x"] for p in walls]); x_hi = max([W + OUTER] + [p["x"] for p in walls])
    y_lo = min([-OUTER] + [p["y"] for p in walls]); y_hi = max([H + OUTER] + [p["y"] for p in walls])
    hy, vx = [-OUTER, H + OUTER], [-OUTER, W + OUTER]
    for p in flat:
        if p.get("in"):
            continue
        off = max(4.0, min(10.0, p.get("gap", gap) / 2))
        hy += [p["y"] - off, p["y"] + p["h"] + off]
        vx += [p["x"] - off, p["x"] + p["w"] + off]
    fixed_h, fixed_v = [], []
    for ln in spec.get("lanes", []):                 # an open lane: one channel down its middle
        if ln["h"] >= ln["w"]:
            fixed_v.append((ln["x"] + ln["w"] / 2, ln["y"], ln["y"] + ln["h"]))
        else:
            fixed_h.append((ln["y"] + ln["h"] / 2, ln["x"], ln["x"] + ln["w"]))
    for c in spec.get("channels", []):               # channels drawn by hand: taken as given
        if "y" in c:
            fixed_h.append((float(c["y"]), float(c["x0"]), float(c["x1"])))
        else:
            fixed_v.append((float(c["x"]), float(c["y0"]), float(c["y1"])))
    def dedupe(vals, lo, hi):
        out = []
        for v in sorted(vals):
            if lo - 0.01 <= v <= hi + 0.01 and (not out or v - out[-1] > 2.5):
                out.append(v)
        return out
    obst = [(p["x"] - 1, p["y"] - 1, p["w"] + 2, p["h"] + 2) for p in flat if not p.get("in")]   # its container blocks for it
    def free(c, lo, hi, horiz):
        segs = [(lo, hi)]
        for (ox, oy, ow, oh) in obst:
            a0, a1, b0, b1 = (ox, ox + ow, oy, oy + oh) if horiz else (oy, oy + oh, ox, ox + ow)
            if not (b0 < c < b1):
                continue
            nxt = []
            for (s0, s1) in segs:
                if a1 <= s0 or a0 >= s1:
                    nxt.append((s0, s1))
                else:
                    if a0 > s0:
                        nxt.append((s0, a0))
                    if a1 < s1:
                        nxt.append((a1, s1))
            segs = nxt
        return [s for s in segs if s[1] - s[0] > 1.0]
    hsegs = [(y, a, b) for y in dedupe(hy, y_lo, y_hi) for (a, b) in free(y, x_lo, x_hi, True)] + fixed_h
    vsegs = [(x, a, b) for x in dedupe(vx, x_lo, x_hi) for (a, b) in free(x, y_lo, y_hi, False)] + fixed_v
    return hsegs, vsegs


class Router:
    def __init__(self, hsegs, vsegs):
        self.h, self.v = hsegs, vsegs
        self.hn = [set() for _ in hsegs]             # node coordinates along each segment
        self.vn = [set() for _ in vsegs]
        for i, (y, x0, x1) in enumerate(hsegs):
            for j, (x, y0, y1) in enumerate(vsegs):
                if x0 - 0.01 <= x <= x1 + 0.01 and y0 - 0.01 <= y <= y1 + 0.01:
                    self.hn[i].add(round(x, 2)); self.vn[j].add(round(y, 2))

    def exits(self, pt, ex, o):
        """(node on a channel, stub axis, segment) for each way out of a terminal: straight out to the nearest channel
        that is still past the terminal once the wire's nudge o is applied."""
        out = []
        for (dx, dy) in EXITS[ex]:
            best = None
            if dx == 0:
                for i, (y, x0, x1) in enumerate(self.h):
                    if x0 - 0.01 <= pt[0] <= x1 + 0.01 and (y + o - pt[1]) * dy > 1.0 and (best is None or abs(y - pt[1]) < abs(best[0][1] - pt[1])):
                        best = ((round(pt[0], 2), round(y, 2)), "v", ("h", i))
            else:
                for j, (x, y0, y1) in enumerate(self.v):
                    if y0 - 0.01 <= pt[1] <= y1 + 0.01 and (x + o - pt[0]) * dx > 1.0 and (best is None or abs(x - pt[0]) < abs(best[0][0] - pt[0])):
                        best = ((round(x, 2), round(pt[1], 2)), "h", ("v", j))
            if best:
                out.append(best)
        return out

    def route(self, a, ea, b, eb, o=0.0):
        """Shortest path (length + a cost per bend) from terminal a to terminal b along the channels.
        Returns (nodes, axis of the stub out of a, axis of the stub into b)."""
        sa, sb = self.exits(a, ea, o), self.exits(b, eb, o)
        if not sa or not sb:
            return None
        hn = [set(s) for s in self.hn]; vn = [set(s) for s in self.vn]
        for (node, _, (kind, i)) in sa + sb:
            (hn if kind == "h" else vn)[i].add(node[0] if kind == "h" else node[1])
        adj = collections.defaultdict(list)
        for i, (y, _, _) in enumerate(self.h):
            xs = sorted(hn[i])
            for p, q in zip(xs, xs[1:]):
                u, w = (p, round(y, 2)), (q, round(y, 2))
                adj[u].append((w, "h")); adj[w].append((u, "h"))
        for j, (x, _, _) in enumerate(self.v):
            ys = sorted(vn[j])
            for p, q in zip(ys, ys[1:]):
                u, w = (round(x, 2), p), (round(x, 2), q)
                adj[u].append((w, "v")); adj[w].append((u, "v"))
        goal = {}
        for (node, ax, _) in sb:
            c = math.dist(node, b[:2])
            if node not in goal or c < goal[node][0]:
                goal[node] = (c, ax)
        dist, prev, pq = {}, {}, []
        for (node, ax, _) in sa:
            st, c = (node, ax), math.dist(a[:2], node)
            if c < dist.get(st, 1e18):
                dist[st], prev[st] = c, None
                heapq.heappush(pq, (c, st))
        best, best_st, best_gax = 1e18, None, None
        while pq:
            c, st = heapq.heappop(pq)
            if c > dist.get(st, 1e18) or c >= best:
                continue
            u, ax = st
            if u in goal:
                gc, gax = goal[u]
                tot = c + gc + (BEND if gax != ax else 0.0)
                if tot < best:
                    best, best_st, best_gax = tot, st, gax
            for (w, wax) in adj[u]:
                nc = c + math.dist(u, w) + (BEND if wax != ax else 0.0)
                if nc < dist.get((w, wax), 1e18):
                    dist[(w, wax)], prev[(w, wax)] = nc, st
                    heapq.heappush(pq, (nc, (w, wax)))
        if best_st is None:
            return None
        path, st = [], best_st
        while st is not None:
            path.append(st); st = prev[st]
        path.reverse()
        return [s_[0] for s_ in path], path[0][1], best_gax


def nudge(no):
    """Each wire runs a little to one side of its channel, so parallel runs don't sit on top of each other."""
    return ((no % 7) - 3) * 1.0

def wire_points(a, b, route, no, T):
    """3-D polyline: straight out of terminal a to its channel, down to the plate, along the (nudged) channels, then up
    and straight into terminal b."""
    nodes, ax_a, ax_b = route
    o = nudge(no)
    sh = [(x + o, y + o) for (x, y) in nodes]
    if len(nodes) == 1:
        sh = [nodes[0]]
    else:                                             # the stubs stay in line with their terminals
        sh[0] = (nodes[0][0], nodes[0][1] + o) if ax_a == "v" else (nodes[0][0] + o, nodes[0][1])
        sh[-1] = (nodes[-1][0], nodes[-1][1] + o) if ax_b == "v" else (nodes[-1][0] + o, nodes[-1][1])
    flat = [sh[0]]
    for k in range(1, len(sh)):                       # a jog where a stub meets a nudged channel at a bend
        p, q = flat[-1], sh[k]
        if abs(p[0] - q[0]) > 0.01 and abs(p[1] - q[1]) > 0.01:
            flat.append((p[0], q[1]) if k == len(sh) - 1 else (q[0], p[1]))
        flat.append(q)
    k = 1
    while k < len(flat) - 1:                          # a corner nudged just past a stub doubles back: fold it out
        p, q, r = flat[k - 1], flat[k], flat[k + 1]
        same_line = (abs(p[0] - q[0]) < 0.01 and abs(q[0] - r[0]) < 0.01) or (abs(p[1] - q[1]) < 0.01 and abs(q[1] - r[1]) < 0.01)
        if same_line and (q[0] - p[0]) * (r[0] - q[0]) + (q[1] - p[1]) * (r[1] - q[1]) < 0:
            del flat[k]
            k = max(1, k - 1)
        else:
            k += 1
    zc = T + 3.0 + (no % 5) * 0.9
    raw = [(tuple(a), "a"), ((flat[0][0], flat[0][1], a[2]), "a")]
    raw += [((x, y, zc), "") for (x, y) in flat]
    raw += [((flat[-1][0], flat[-1][1], b[2]), "b"), (tuple(b), "b")]
    out = []
    for pt, tag in raw:
        if out and math.dist(pt, out[-1][0]) < 0.01:
            if tag:
                out[-1] = (out[-1][0], tag)
            continue
        out.append((pt, tag))
    clean = [out[0]]                                  # drop points in the middle of a straight run
    for k in range(1, len(out) - 1):
        p0, p1, p2 = clean[-1][0], out[k][0], out[k + 1][0]
        d1 = [p1[i] - p0[i] for i in range(3)]; d2 = [p2[i] - p1[i] for i in range(3)]
        cr = (d1[1] * d2[2] - d1[2] * d2[1], d1[2] * d2[0] - d1[0] * d2[2], d1[0] * d2[1] - d1[1] * d2[0])
        if max(abs(v) for v in cr) < 1e-6 and sum(d1[i] * d2[i] for i in range(3)) > 0 and not out[k][1]:
            continue
        clean.append(out[k])
    clean.append(out[-1])
    return clean


# ---------------------------------------------------------------- the build
def esc(s):
    return html.escape(str(s if s is not None else ""), quote=True)

def md(s):
    """Escaped text with **bold** and `code`."""
    t = esc(s)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    return re.sub(r"`(.+?)`", r"<code>\1</code>", t)

def colour_hex(c):
    if isinstance(c, str) and re.fullmatch(r"#[0-9a-fA-F]{3}([0-9a-fA-F]{3})?", c):
        return c
    return COLOURS.get(str(c).lower())

def awg(g):
    m = re.search(r"(\d+)\s*AWG", str(g), re.I)
    return int(m.group(1)) if m else None

def stl_bbox(path):
    d = read_bytes(path)
    lo, hi = [1e18] * 3, [-1e18] * 3
    n = struct.unpack("<I", d[80:84])[0] if len(d) >= 84 else 0
    if len(d) == 84 + 50 * n and n:
        for i in range(n):
            for k in range(3):
                v = struct.unpack_from("<3f", d, 84 + i * 50 + 12 + 12 * k)
                for a_ in range(3):
                    lo[a_] = min(lo[a_], v[a_]); hi[a_] = max(hi[a_], v[a_])
    else:                                             # ASCII STL
        for m in re.finditer(rb"vertex\s+(\S+)\s+(\S+)\s+(\S+)", d):
            v = [float(q) for q in m.groups()]
            for a_ in range(3):
                lo[a_] = min(lo[a_], v[a_]); hi[a_] = max(hi[a_], v[a_])
    if lo[0] > hi[0]:
        raise SpecError(f"{path}: no triangles")
    return lo, hi


def build(spec_path, check_only=False):
    spec_dir = os.path.dirname(os.path.abspath(spec_path))
    spec = json.loads(read_text(spec_path))
    pl = spec.get("plate") or {}
    W, H = fnum(pl.get("w"), "plate.w"), fnum(pl.get("h"), "plate.h")
    T = float(pl.get("t", 5.0))
    parts = norm_parts(spec, W, H)
    problems = check_layout(spec, parts, W, H)
    warnings = []

    colours = dict(COLOURS)
    for k, v in (spec.get("colours") or {}).items():
        colours[k.lower()] = v
    groups = collections.OrderedDict()
    for k, g in enumerate(spec.get("groups", [])):
        groups[g["id"]] = dict(id=g["id"], label=g.get("label", g["id"]), color=g.get("color", GROUP_PALETTE[k % len(GROUP_PALETTE)]))

    # terminals in plate coordinates
    def term_world(p, t):
        return (p["x"] + t["x"], p["y"] + t["y"], T + t["z"])
    def resolve(ref, where):
        pid, _, tn = str(ref).partition(".")
        p = parts.get(pid)
        if not p:
            problems.append(f"{where}: no part called {pid!r}")
            return None
        terms = p["_terms"]
        if not tn:
            if "" in terms:
                t = terms[""]
            elif len(terms) == 1:
                t = next(iter(terms.values()))
            elif not terms:
                t = (dict(name="", x=0.0, y=0.0, z=p["z"], exit=p["_exit"], label="") if p["mount"] == "wall" else
                     dict(name="", x=p["w"] / 2, y=p["h"] / 2, z=p["z0"] + p["d"] + 2.0, exit="any", label=""))
            else:
                problems.append(f"{where}: {pid} has terminals {', '.join(terms)}: name one, as {pid}.{next(iter(terms))}")
                return None
        else:
            t = terms.get(tn)
            if not t:
                problems.append(f"{where}: {pid} has no terminal {tn!r} (it has {', '.join(terms) or 'none'})")
                return None
        lab = p.get("label") or p["name"]
        return dict(p=p, t=t, pt=term_world(p, t), label=(f"{lab} {t['label']}" if t["label"] else lab).strip())

    wires = []
    for k, raw in enumerate(spec.get("wires", [])):
        no = k + 1
        where = f"wire {no}"
        a, b = resolve(raw.get("from"), where), resolve(raw.get("to"), where)
        col = raw.get("colour", raw.get("color", "black"))
        hexc = colour_hex(col) or colours.get(str(col).lower())
        if not hexc:
            problems.append(f"{where}: unknown colour {col!r} (add it under \"colours\")")
            hexc = "#888888"
        gid = raw.get("group", "wires")
        if gid not in groups:
            if spec.get("groups"):
                problems.append(f"{where}: group {gid!r} isn't in \"groups\"")
            groups[gid] = dict(id=gid, label=gid.replace("_", " ").capitalize(), color=GROUP_PALETTE[len(groups) % len(GROUP_PALETTE)])
        if not a or not b:
            continue
        wires.append(dict(no=no, id=raw.get("id"), a=a, b=b, frm=raw.get("from_label") or a["label"], to=raw.get("to_label") or b["label"],
                          gauge=raw.get("gauge", ""), colour=str(col), hex=hexc, group=gid, note=raw.get("note", ""),
                          plan_number=raw.get("plan_number", True), r=raw.get("r")))
    for g in groups.values():
        g["n"] = sum(1 for w in wires if w["group"] == g["id"])

    hsegs, vsegs = build_channels(spec, parts, W, H)
    router = Router(hsegs, vsegs)
    slack, ends = float(spec.get("slack", 0.15)), float(spec.get("ends_mm", 60))
    for w in wires:
        nodes = router.route(w["a"]["pt"], w["a"]["t"]["exit"], w["b"]["pt"], w["b"]["t"]["exit"], nudge(w["no"]))
        if not nodes:
            problems.append(f"wire {w['no']} ({w['frm']} → {w['to']}) finds no route: give a terminal a different exit, or make room")
            w["pts"] = None
            continue
        pts = wire_points(w["a"]["pt"], w["b"]["pt"], nodes, w["no"], T)
        w["pts"] = [q for q, _ in pts]
        w["lf"] = [w["a"]["p"]["explode"] if tag == "a" else w["b"]["p"]["explode"] if tag == "b" else 0.0 for _, tag in pts]
        w["route_mm"] = sum(math.dist(w["pts"][i], w["pts"][i + 1]) for i in range(len(w["pts"]) - 1))
        w["mm"] = int(round((w["route_mm"] * (1 + slack) + ends) / 10.0) * 10)

    # steps: by number, by wire id, or "group:<id>"; without steps, one step per group
    byid = {w["id"]: w["no"] for w in wires if w["id"]}
    nos_ok = {w["no"] for w in wires}
    broken = {raw.get("id") for raw in spec.get("wires", []) if raw.get("id")} - set(byid)   # already reported above
    broken |= set(range(1, len(spec.get("wires", [])) + 1)) - nos_ok
    steps = []
    raw_steps = spec.get("steps") or [dict(title=g["label"], wires=[f"group:{g['id']}"], notes=[]) for g in groups.values() if g["n"]]
    for k, s in enumerate(raw_steps):
        ns = []
        for ref in s.get("wires", []):
            if isinstance(ref, int):
                ok = ref in nos_ok
                ns += [ref] if ok else []
            elif isinstance(ref, str) and ref.startswith("group:"):
                got = [w["no"] for w in wires if w["group"] == ref[6:]]
                ok = bool(got) or ref[6:] in groups
                ns += got
            else:
                ok = ref in byid
                ns += [byid[ref]] if ok else []
            if not ok and ref not in broken:
                problems.append(f"step {k + 1}: no wire {ref!r}")
        steps.append(dict(title=s.get("title", f"Step {k + 1}"), wires=list(dict.fromkeys(ns)), notes=s.get("notes", [])))
    seen = collections.Counter(n for s in steps for n in s["wires"])
    missing = sorted(nos_ok - set(seen))
    if missing:
        warnings.append(f"wires in no step: {', '.join(map(str, missing))}")
    twice = sorted(n for n, c in seen.items() if c > 1)
    if twice:
        warnings.append(f"wires in more than one step: {', '.join(map(str, twice))}")

    return dict(spec=spec, spec_dir=spec_dir, W=W, H=H, T=T, parts=parts, wires=wires, groups=groups, steps=steps,
                problems=problems, warnings=warnings, colours=colours, channels=(hsegs, vsegs))


# ---------------------------------------------------------------- 3-D scene
def M(x=0.0, y=0.0, z=0.0):
    return [1, 0, 0, x, 0, 1, 0, y, 0, 0, 1, z, 0, 0, 0, 1]

def scene(B):
    W, H, T, parts, spec = B["W"], B["H"], B["T"], B["parts"], B["spec"]
    objs, blobs, labels = [], {}, []
    def add(oid, name, layer, geom, color, m, note="", lift=0.0, opacity=1.0):
        objs.append(dict(id=oid, name=name, layer=layer, geom=geom, color=color, m=m, note=note, lift=lift, opacity=opacity))
    def box(oid, name, layer, x, y, z, w, h, d, color, note="", lift=0.0, opacity=1.0):
        add(oid, name, layer, f"box:{w:.2f}:{h:.2f}:{d:.2f}", color, M(x + w / 2, y + h / 2, z + d / 2), note, lift, opacity)
    def cylz(oid, name, layer, x, y, z, r, d, color, note="", lift=0.0, opacity=1.0):
        add(oid, name, layer, f"cyl:{r:.2f}:{d:.2f}", color, [1, 0, 0, x, 0, 0, -1, y, 0, 1, 0, z + d / 2, 0, 0, 0, 1], note, lift, opacity)

    pl = spec["plate"]
    box("plate", pl.get("name", f"Backplate {W:g} × {H:g} × {T:g} mm"), "plate", 0, 0, 0, W, H, T, pl.get("color", "#e8742a"), pl.get("note", ""))
    for p in parts.values():
        pid, li, nm, note = p["id"], p["explode"], p["name"], p.get("note", "")
        if p["mount"] == "wall":
            ax, x, y, z = p["_axis"], p["x"], p["y"], T + p["z"]
            m = ([0, -1, 0, x, 1, 0, 0, y, 0, 0, 1, z, 0, 0, 0, 1] if ax == "x" else
                 [1, 0, 0, x, 0, 0, -1, y, 0, 1, 0, z, 0, 0, 0, 1] if ax == "z" else M(x, y, z))
            add(pid, nm, "walls", f"cyl:{p['r']:.2f}:{p['len']:.2f}", p["color"], m, note, li)
            continue
        zb = T + p["z0"]
        if p["z0"] > 0:                               # spacers under a stacked part
            spots = [(hl[0], hl[1]) for hl in p["holes"]] or [(6, 6), (p["w"] - 6, 6), (6, p["h"] - 6), (p["w"] - 6, p["h"] - 6)]
            for k, (hx, hy) in enumerate(spots):
                cylz(f"{pid}_sp{k}", f"Spacer {p['z0']:g} mm under the {nm}", "parts", p["x"] + hx, p["y"] + hy, T, 3.0, p["z0"], "#efefe8", lift=li)
        if p.get("mesh"):
            path = os.path.join(B["spec_dir"], p["mesh"])
            lo, hi = stl_bbox(path)
            key = os.path.splitext(os.path.basename(path))[0]
            if key not in blobs:
                blobs[key] = base64.b64encode(read_bytes(path)).decode()
            cx, cy = p["x"] + p["w"] / 2, p["y"] + p["h"] / 2
            mx, my = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2
            rot = int(p.get("mesh_rot", 0)) % 360
            c, s = {0: (1, 0), 90: (0, 1), 180: (-1, 0), 270: (0, -1)}[rot]
            m = [c, -s, 0, cx - (c * mx - s * my), s, c, 0, cy - (s * mx + c * my), 0, 0, 1, zb - lo[2], 0, 0, 0, 1]
            add(pid, nm, "parts", key, p["color"], m, note, li, p.get("opacity", 1.0))
        elif p.get("busbar"):
            base = min(10.0, p["d"])
            box(pid, nm, "parts", p["x"], p["y"], zb, p["w"], p["h"], base, p["color"], note, li)
            if p["d"] > base:
                box(pid + "_cov", nm + ": clear cover", "parts", p["x"] + 1, p["y"] + 1, zb + base, p["w"] - 2, p["h"] - 2, p["d"] - base,
                    p["busbar"].get("cover", "#c9ccd0"), lift=li, opacity=0.3)
        elif p.get("shape") == "cylinder":
            r = min(p["w"], p["h"]) / 2
            cylz(pid, nm, "parts", p["x"] + p["w"] / 2, p["y"] + p["h"] / 2, zb, r, p["d"], p["color"], note, li, p.get("opacity", 1.0))
        else:
            box(pid, nm, "parts", p["x"], p["y"], zb, p["w"], p["h"], p["d"], p["color"], note, li, p.get("opacity", 1.0))
        if p.get("opacity", 1.0) < 0.5:                  # see-through (a tray, a keep-out space): outline its edges
            objs[-1]["edges"] = True
        for tn, t in p["_terms"].items():             # every terminal: a small stud you can hover
            x, y, z = p["x"] + t["x"], p["y"] + t["y"], T + t["z"]
            big = p.get("busbar") and tn in ("A", "B")
            cylz(f"{pid}_t_{tn}", f"{p.get('label') or nm} · {t['label'] or tn}", "terminals", x, y, z - 4, 3.2 if big else 1.8, 4.0,
                 "#c4c9ce", lift=li)
        for k, hl in enumerate(p["holes"]):           # screws through the part into the plate
            hx, hy, d = hl[0], hl[1], hl[2] if len(hl) > 2 else 4.3
            top = T + p["z0"] + p.get("flange", 3.0)
            cylz(f"{pid}_b{k}", f"Screw ({nm})", "screws", p["x"] + hx, p["y"] + hy, -2, d / 2 - 0.25, top + 2, "#c4c9ce", lift=li)
            cylz(f"{pid}_bh{k}", f"Screw head ({nm})", "screws", p["x"] + hx, p["y"] + hy, top, d / 2 + 1.6, 2.2, "#c4c9ce", lift=li)
        for k, (x, y, w, h) in enumerate(rooms(p)):
            box(f"wz_{pid}{k}", f"Wiring room for the {nm}: kept clear", "zones", x, y, T, w, h, 1.0, "#2bb3a3", opacity=0.35)
        if p.get("label"):
            labels.append(dict(t=p["label"], p=[p["x"] + p["w"] / 2, p["y"] + p["h"] / 2, T + p["z0"] + p["d"] + 8], lift=li))
    for k, ln in enumerate(spec.get("lanes", [])):
        box(f"lane{k}", ln.get("label", "Wiring lane: kept open for the wires"), "zones", ln["x"], ln["y"], T, ln["w"], ln["h"], 1.0, "#9aa3ab", opacity=0.45)
        if ln.get("label"):
            labels.append(dict(t=ln["label"], p=[ln["x"] + ln["w"] / 2, ln["y"] + ln["h"] / 2, T + 30], lift=0))
    en = spec.get("enclosure")
    if en:
        ew, eh, ed = en["w"], en["h"], en["d"]
        box("enclosure", en.get("name", f"Enclosure: at least {ew:g} × {eh:g} × {ed:g} mm inside"), "box",
            en.get("x", -(ew - W) / 2), en.get("y", -(eh - H) / 2), T + en.get("z", -(T + 5)), ew, eh, ed, "#9aa3ab", opacity=0.07)
    wires3d = []
    for w in B["wires"]:
        if not w["pts"]:
            continue
        g = awg(w["gauge"])
        r = w["r"] or (1.9 if g is not None and g <= 10 else 1.7 if g is not None and g <= 12 else 1.4 if w["colour"] == "coax"
                       else 1.25 if g is not None and g <= 16 else 1.0)
        wires3d.append(dict(id=f"w{w['no']}", label=f"W{w['no']}: {w['frm']} → {w['to']} · {w['gauge']} {w['colour']}".strip(),
                            note=w["note"], color=w["hex"], group=w["group"], r=r, pts=[[round(v, 2) for v in q] for q in w["pts"]],
                            lf=w["lf"]))
    ys = [0.0] + [p["y"] for p in parts.values() if p["mount"] == "wall"]
    view = dict(cx=W / 2, cy=(H + min(ys)) / 2, cz=60.0, s=max(W, H * 0.8) / 450.0)
    return objs, blobs, wires3d, labels, view


# ---------------------------------------------------------------- the plate, front view (SVG)
SVG_CSS = """<style>.pl{fill:var(--sch-blk2,#eef0ec);stroke:var(--sch-mut,#5d676c);stroke-width:1.2}
.wz{fill:#2bb3a3;opacity:.16}.pt{fill:var(--sch-blk,#f6f7f4);stroke:var(--sch-ink,#1b2124);stroke-width:1.4}
.und{fill:none;stroke:var(--sch-mut,#5d676c);stroke-width:1.2;stroke-dasharray:3 3}.ghost{fill:none;stroke:#e8742a;stroke-width:2}
.hole{fill:var(--sch-bg,#fff);stroke:var(--sch-ink,#1b2124);stroke-width:1}
.pn{font:700 12px 'Barlow Condensed',Arial Narrow,sans-serif;fill:var(--sch-ink,#1b2124)}.tn{font:600 10px 'JetBrains Mono',monospace;fill:var(--sch-ink,#1b2124)}
.cap,.lg{font:12px 'Atkinson Hyperlegible',system-ui,sans-serif;fill:var(--sch-mut,#5d676c)}.wr{fill:none;stroke-linejoin:round;stroke-linecap:round;opacity:.92}
.wn{fill:var(--sch-bg,#fff);stroke:var(--sch-ink,#1b2124);stroke-width:1.1}.wnt{font:700 10px 'JetBrains Mono',monospace;fill:var(--sch-ink,#1b2124)}
.wall{fill:#3b3f44;stroke:var(--sch-ink,#1b2124)}.lane{fill:none;stroke:var(--sch-mut,#5d676c);stroke-width:1.2;stroke-dasharray:3 3}
.sw{stroke:var(--sch-ink,#1b2124);stroke-width:.8}</style>"""

def plate_svg(B, show=None, done=()):
    W, H, parts, wires = B["W"], B["H"], B["parts"], B["wires"]
    walls = [p for p in parts.values() if p["mount"] == "wall"]
    S = min(800.0 / W, 1500.0 / H)
    x_lo = min([0.0] + [p["x"] for p in walls]); x_hi = max([W] + [p["x"] for p in walls])
    y_lo = min([0.0] + [p["y"] for p in walls]); y_hi = max([H] + [p["y"] for p in walls])
    MGL = 110.0 if any(p["x"] < 0 for p in walls) else 30.0
    MGR = 110.0 if any(p["x"] > W for p in walls) else 30.0
    X = lambda x: MGL + (x - x_lo) * S
    Y = lambda y: 60.0 + (y_hi - y) * S
    VW = X(x_hi) + MGR
    o = [f'<rect class="pl" x="{X(0):.1f}" y="{Y(H):.1f}" width="{W * S:.1f}" height="{H * S:.1f}" rx="4"/>',
         f'<text class="cap" x="{X(0):.1f}" y="{Y(H) - 12:.1f}">Plate {W:g} × {H:g} mm, seen from the front</text>']
    for p in parts.values():
        if p["mount"] == "plate":
            for (x, y, w, h) in rooms(p):
                o.append(f'<rect class="wz" x="{X(x):.1f}" y="{Y(y + h):.1f}" width="{w * S:.1f}" height="{h * S:.1f}"/>')
    for ln in B["spec"].get("lanes", []):
        o.append(f'<rect class="lane" x="{X(ln["x"]):.1f}" y="{Y(ln["y"] + ln["h"]):.1f}" width="{ln["w"] * S:.1f}" height="{ln["h"] * S:.1f}"/>')
    flat = sorted((p for p in parts.values() if p["mount"] == "plate"), key=lambda q: (q["z0"], -q["d"]))
    raised = [p for p in flat if p["z0"] > 0]
    covered = {q["id"] for q in flat for r_ in raised if q is not r_ and q["z0"] + q["d"] <= r_["z0"] and overlap(rect(q), rect(r_), -0.01)}
    for p in flat:
        ghost = p.get("opacity", 1.0) < 0.5
        cls = "ghost" if ghost else "und" if p["id"] in covered else "pt"
        o.append(f'<rect class="{cls}" x="{X(p["x"]):.1f}" y="{Y(p["y"] + p["h"]):.1f}" width="{p["w"] * S:.1f}" height="{p["h"] * S:.1f}" rx="3"><title>{esc(p["name"])}</title></rect>')
        for hl in p["holes"]:
            hx, hy, d = hl[0], hl[1], hl[2] if len(hl) > 2 else 4.3
            if len(hl) > 3 and "slot" in str(hl[3]):
                o.append(f'<rect class="hole" x="{X(p["x"] + hx - 4 - d / 2):.1f}" y="{Y(p["y"] + hy) - d / 2 * S:.1f}" width="{(8 + d) * S:.1f}" height="{d * S:.1f}" rx="{d / 2 * S:.1f}"/>')
            else:
                o.append(f'<circle class="hole" cx="{X(p["x"] + hx):.1f}" cy="{Y(p["y"] + hy):.1f}" r="{d / 2 * S:.1f}"/>')
        if ghost:
            continue
        nm = p.get("label") or p["id"]
        cx, cy = X(p["x"] + p["w"] / 2), Y(p["y"] + p["h"] / 2)
        tr = f' transform="rotate(-90 {cx:.1f} {cy:.1f})"' if p["h"] > p["w"] * 1.6 and p["w"] < 40 else ""
        o.append(f'<text class="pn" x="{cx:.1f}" y="{cy + 4:.1f}" text-anchor="middle"{tr}>{esc(nm)}</text>')
    for p in walls:
        x, y, nm = X(p["x"]), Y(p["y"]), esc(p.get("label") or p["id"])
        o.append(f'<rect class="wall" x="{x - 8:.1f}" y="{y - 8:.1f}" width="16" height="16" rx="3"><title>{esc(p["name"])}</title></rect>')
        if p["x"] < 0:
            o.append(f'<text class="tn" x="{x - 12:.1f}" y="{y + 4:.1f}" text-anchor="end">{nm}</text>')
        elif p["x"] > W:
            o.append(f'<text class="tn" x="{x + 12:.1f}" y="{y + 4:.1f}">{nm}</text>')
        elif p["y"] < 0:
            o.append(f'<text class="tn" x="{x:.1f}" y="{y + 22:.1f}" text-anchor="middle">{nm}</text>')
        else:
            o.append(f'<text class="tn" x="{x:.1f}" y="{y - 12:.1f}" text-anchor="middle">{nm}</text>')
    used, drawn = [], []
    for w in wires:
        if not w["pts"]:
            continue
        pts = []
        for q in w["pts"]:
            v = (round(X(q[0]), 1), round(Y(q[1]), 1))
            if not pts or v != pts[-1]:
                pts.append(v)
        d = "M" + " L".join(f"{a},{b}" for a, b in pts)
        if show is not None and w["no"] not in show:
            if w["no"] in done:
                o.append(f'<path class="wr" d="{d}" stroke="#9aa3ab" stroke-width="1.6" opacity=".55"/>')
            continue
        col = "var(--sch-ink,#2a2d31)" if w["colour"].lower() == "black" else w["hex"]
        g = awg(w["gauge"])
        wd = (3.2 if g is not None and g <= 12 else 2.2) + (1.2 if show else 0)
        o.append(f'<path class="wr" d="{d}" stroke="{col}" stroke-width="{wd}"><title>W{w["no"]}: {esc(w["frm"])} → {esc(w["to"])}</title></path>')
        if w["colour"].lower() == "white":
            o.append(f'<path class="wr" d="{d}" stroke="#8a8f94" stroke-width="1" stroke-dasharray="2 3"/>')
        if show:
            for q in (pts[0], pts[-1]):
                o.append(f'<circle cx="{q[0]}" cy="{q[1]}" r="4.5" fill="{col}" stroke="var(--sch-bg,#fff)" stroke-width="1.5"/>')
        if (show is None and not w["plan_number"]) or len(pts) < 2:
            continue
        drawn.append((w, pts))
    for w, pts in drawn:                              # numbers, nudged so they don't sit on each other
        segs = sorted(range(len(pts) - 1), key=lambda i: -math.dist(pts[i], pts[i + 1]))
        spot = None
        for i in segs:
            for f in (0.5, 0.3, 0.7, 0.15, 0.85):
                c = (pts[i][0] + (pts[i + 1][0] - pts[i][0]) * f, pts[i][1] + (pts[i + 1][1] - pts[i][1]) * f)
                if all(math.dist(c, u) > 21 for u in used):
                    spot = c; break
            if spot:
                break
        spot = spot or ((pts[0][0] + pts[1][0]) / 2, (pts[0][1] + pts[1][1]) / 2)
        used.append(spot)
        o.append(f'<circle class="wn" cx="{spot[0]:.1f}" cy="{spot[1]:.1f}" r="9.5"/><text class="wnt" x="{spot[0]:.1f}" y="{spot[1] + 3.8:.1f}" text-anchor="middle">{w["no"]}</text>')
    yl = Y(y_lo) + 40
    o.append(f'<text class="lg" x="{X(x_lo):.1f}" y="{yl:.1f}">Numbers = wire numbers in the cut list · green = wiring room, kept clear · dashed = under a stacked part, or a wiring lane</text>')
    xs, yl = X(x_lo), yl + 22
    seen = []
    for w in wires:
        if w["colour"].lower() not in seen:
            seen.append(w["colour"].lower())
            o.append(f'<rect class="sw" x="{xs:.1f}" y="{yl - 10:.1f}" width="12" height="12" rx="2" fill="{w["hex"]}"/><text class="lg" x="{xs + 16:.1f}" y="{yl:.1f}">{esc(w["colour"])}</text>')
            xs += 26 + 7 * len(w["colour"])
            if xs > VW - 90:
                xs, yl = X(x_lo), yl + 20
    VH = yl + 16
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {VW:.0f} {VH:.0f}" role="img" aria-label="Wiring on the plate, front view">'
            + SVG_CSS + "".join(o) + "</svg>")


# ---------------------------------------------------------------- output
def cut_rows(B):
    return [dict(no=w["no"], frm=w["frm"], to=w["to"], gauge=w["gauge"], colour=w["colour"], mm=w.get("mm"),
                 group=B["groups"][w["group"]]["label"], note=w["note"]) for w in B["wires"]]

def markdown_table(B, filt=()):
    rows = cut_rows(B)
    if filt:
        keep = set()
        for w in B["wires"]:
            if str(w["no"]) in filt or w["a"]["p"]["id"] in filt or w["b"]["p"]["id"] in filt:
                keep.add(w["no"])
        rows = [r for r in rows if r["no"] in keep]
    out = ["| # | From | To | Gauge | Colour | mm | Group | Note |", "|---|---|---|---|---|---|---|---|"]
    out += [f"| {r['no']} | {r['frm']} | {r['to']} | {r['gauge']} | {r['colour']} | {r['mm'] or '—'} | {r['group']} | {r['note']} |"
            for r in rows]
    return "\n".join(out)

def buy_totals(B):
    """(gauge, colour) -> (wires, total cut mm, hex), thickest first."""
    buy = collections.OrderedDict()
    for w in sorted(B["wires"], key=lambda q: (awg(q["gauge"]) or 99, q["gauge"], q["colour"])):
        k = (w["gauge"], w["colour"])
        n, mm, hexc = buy.get(k, (0, 0, w["hex"]))
        buy[k] = (n + 1, mm + (w.get("mm") or 0), hexc)
    return buy

def write_outputs(B, out_dir, stem):
    spec = B["spec"]
    objs, blobs, wires3d, labels, view = scene(B)
    psvg = plate_svg(B)
    os.makedirs(os.path.join(out_dir, "steps"), exist_ok=True)
    for f in os.listdir(os.path.join(out_dir, "steps")):
        if f.startswith("step-") and f.endswith(".svg"):
            os.remove(os.path.join(out_dir, "steps", f))
    wmap = {w["no"]: w for w in B["wires"]}
    step_html, done = [], []
    for i, s in enumerate(B["steps"]):
        svg = plate_svg(B, show=set(s["wires"]), done=set(done))
        done += s["wires"]
        write_text(os.path.join(out_dir, "steps", f"step-{i + 1:02d}.svg"), svg)
        rows = "".join(f'<tr><td class="n">{n}</td><td>{esc(wmap[n]["frm"])}</td><td>{esc(wmap[n]["to"])}</td><td>{esc(wmap[n]["gauge"])}</td>'
                       f'<td><span class="sw" style="background:{wmap[n]["hex"]}"></span>{esc(wmap[n]["colour"])}</td><td class="n">{wmap[n].get("mm") or "—"}</td>'
                       f'<td><input type="checkbox" data-tick="{n}" aria-label="Wire {n} done"></td></tr>' for n in s["wires"] if n in wmap)
        tbl = (f'<table class="st"><thead><tr><th>#</th><th>From</th><th>To</th><th>Gauge</th><th>Colour</th><th>mm</th><th>Done</th></tr></thead>'
               f'<tbody>{rows}</tbody></table>' if rows else "")
        step_html.append(f'<article class="step" data-step="{i + 1}"{" hidden" if i else ""}><div class="stepgrid"><div class="stepfig">{svg}</div>'
                         f'<div class="steptext"><div class="eyebrow">Step {i + 1} of {len(B["steps"])}</div><h3 class="sth">{esc(s["title"])}</h3><ul>'
                         + "".join(f"<li>{md(n)}</li>" for n in s["notes"]) + f"</ul>{tbl}</div></div></article>")
    tabs = "".join(f'<button data-go="{i + 1}" aria-pressed="{"true" if i == 0 else "false"}">{i + 1}</button>' for i in range(len(B["steps"])))
    rows = cut_rows(B)
    cut = "".join(f'<tr><td class="n">{r["no"]}</td><td>{esc(r["frm"])}</td><td>{esc(r["to"])}</td><td>{esc(r["gauge"])}</td>'
                  f'<td><span class="sw" style="background:{B["wires"][k]["hex"]}"></span>{esc(r["colour"])}</td><td class="n">{r["mm"] or "—"}</td>'
                  f'<td>{esc(r["group"])}{(" · " + esc(r["note"])) if r["note"] else ""}</td></tr>' for k, r in enumerate(rows))
    buf = io.StringIO()
    cw = csv.writer(buf)
    cw.writerow(["#", "From", "To", "Gauge", "Colour", "mm", "Group", "Note"])
    for r in rows:
        cw.writerow([r["no"], r["frm"], r["to"], r["gauge"], r["colour"], r["mm"] or "", r["group"], r["note"]])
    csv_text = buf.getvalue()
    buy = buy_totals(B)
    buy_rows = "".join(f'<tr><td>{esc(g)}</td><td><span class="sw" style="background:{hx}"></span>{esc(c)}</td><td class="n">{n}</td>'
                       f'<td class="n">{mm / 1000:.2f} m</td></tr>' for (g, c), (n, mm, hx) in buy.items())
    W, H = B["W"], B["H"]
    flat = [p for p in B["parts"].values() if p["mount"] == "plate"]
    total = sum(w.get("mm") or 0 for w in B["wires"]) / 1000
    facts = [(f"{W:g} × {H:g} mm", f"The plate, with {len(flat)} parts on it" + (f" and {len(B['parts']) - len(flat)} in the box walls." if len(B["parts"]) > len(flat) else ".")),
             (f"{len(B['wires'])} wires", f"{total:.1f} m in all, cut lengths included. Every wire runs in a gap, never over a device.")]
    if spec.get("gap"):
        facts.append((f"{spec['gap']:g} mm apart", "The closest any two parts may sit, so fingers and ring lugs fit. The build refuses anything tighter."))
    if spec.get("enclosure"):
        en = spec["enclosure"]
        facts.append((f"{en['w']:g} × {en['h']:g} × {en['d']:g} mm", "The enclosure needed, inside."))
    facts += [(f.get("title", ""), f.get("text", "")) for f in spec.get("facts", [])]
    facts_html = "".join(f'<div class="fact"><b>{md(a)}</b><span>{md(b)}</span></div>' for a, b in facts)
    build_order = spec.get("build_order", [])
    build_html = (f'<h2 class="sec">Build order</h2><ol class="steps">' + "".join(f"<li>{md(s)}</li>" for s in build_order) + "</ol>") if build_order else ""
    links = " · ".join(f'<a href="{esc(l["href"])}">{esc(l["text"])}</a>' for l in spec.get("links", []))
    eyebrow = esc(spec.get("eyebrow", "Panel visualizer")) + (f" · {links}" if links else "")
    def js(v):
        return json.dumps(v, separators=(",", ":")).replace("</", "<\\/")
    vals = dict(TITLE=esc(spec.get("title", stem)), DESC=esc(spec.get("description", f"3-D model, wiring diagram, wiring steps and cut list for {spec.get('title', stem)}.")),
                EYEBROW=eyebrow, INTRO=md(spec.get("intro", "")), FACTS=facts_html, STEPS="".join(step_html), STEPTABS=tabs,
                NSTEPS=str(len(B["steps"])), PSVG=psvg, ROWS=cut, NW=str(len(B["wires"])), BUYROWS=buy_rows, BUILD=build_html,
                OBJ=js(objs), BLOB=js(blobs), WIRES=js(wires3d), LABELS=js(labels), GROUPS=js(list(B["groups"].values())),
                VIEW=js(view), LIFT=js(LIFT), CSV=js(csv_text), KEY=js("panel-visualizer:" + spec.get("title", stem)), CSVNAME=js(stem + "-cutlist.csv"))
    page = re.sub(r"\{\{([A-Z0-9_]+)\}\}", lambda m: vals[m.group(1)], read_text(TEMPLATE))
    html_path = os.path.join(out_dir, stem + ".html")
    write_text(html_path, page)
    write_text(os.path.join(out_dir, "wiring-on-plate.svg"), psvg)
    write_text(os.path.join(out_dir, "cutlist.csv"), csv_text, newline="")
    buy_md = "\n".join(["| Gauge | Colour | Wires | Total cut length |", "|---|---|---|---|"] +
                       [f"| {g} | {c} | {n} | {mm / 1000:.2f} m |" for (g, c), (n, mm, _) in buy.items()])
    write_text(os.path.join(out_dir, "cutlist.md"),
        f"# {spec.get('title', stem)}: wire cut list\n\n" + markdown_table(B) + "\n\n## Wire to buy\n\n" + buy_md + "\n")
    return html_path, len(page), len(objs)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build a panel's 3-D page, wiring diagram, wiring steps and cut list from a JSON spec.")
    ap.add_argument("spec", nargs="?", help="the panel spec (JSON)")
    ap.add_argument("-o", "--out", help="output folder (default: <spec name>-build next to the spec)")
    ap.add_argument("--check", action="store_true", help="run the checks and route the wires; write nothing")
    ap.add_argument("--wires", nargs="*", metavar="FILTER", help="print the cut list as markdown (filter by part id or wire number); write nothing")
    ap.add_argument("--force", action="store_true", help="write the page even if checks fail")
    ap.add_argument("--init", metavar="NEW_SPEC", help="copy the minimal example to NEW_SPEC to start a new panel")
    a = ap.parse_args(argv)
    if a.init:
        if os.path.exists(a.init):
            sys.exit(f"{a.init} already exists")
        shutil.copyfile(STARTER, a.init)
        print(f"wrote {a.init}: edit the plate, parts and wires, then run build_panel.py {a.init}")
        return 0
    if not a.spec:
        ap.error("give a spec file, or --init NEW_SPEC")
    try:
        B = build(a.spec)
    except (SpecError, KeyError, json.JSONDecodeError) as e:
        sys.exit(f"spec error: {e}")
    if a.wires is not None:
        print(markdown_table(B, set(a.wires)))
        return 0
    for w in B["warnings"]:
        print("warning:", w)
    if B["problems"]:
        print("CHECKS FAILED:")
        for p in B["problems"]:
            print("  -", p)
        if not a.force or a.check:
            return 1
    stem = os.path.splitext(os.path.basename(a.spec))[0]
    total = sum(w.get("mm") or 0 for w in B["wires"]) / 1000
    if a.check:
        print(f"checks: all passed · {len(B['parts'])} parts, {len(B['wires'])} wires routed, {total:.1f} m of wire, {len(B['steps'])} steps")
        return 0
    out = a.out or os.path.join(B["spec_dir"], stem + "-build")
    path, size, n = write_outputs(B, out, stem)
    print(f"{path}: {n} objects, {len(B['wires'])} wires ({total:.1f} m), {len(B['steps'])} steps, {size / 1e3:.0f} kB")
    if not B["problems"]:
        print("checks: all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
