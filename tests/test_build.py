"""Build both examples and check every route: python3 -m unittest discover tests"""
import json, math, os, re, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(ROOT, "skills", "panel-visualizer")
sys.path.insert(0, os.path.join(SKILL, "scripts"))
sys.dont_write_bytecode = True
import build_panel as bp  # noqa: E402

EXAMPLES = [os.path.join(SKILL, "examples", f) for f in ("minimal.json", "solar-sensor-station.json")]
DIRS = {"up": (0, 1), "down": (0, -1), "left": (-1, 0), "right": (1, 0)}


def route_faults(w):
    """Diagonal segments, runs that double back, and stubs that leave a terminal against its exit."""
    P, out = w["pts"], []
    for i in range(len(P) - 1):
        if sum(1 for k in range(3) if abs(P[i + 1][k] - P[i][k]) > 0.01) > 1:
            out.append(f"W{w['no']} segment {i} is diagonal")
    for i in range(len(P) - 2):
        d1 = [P[i + 1][k] - P[i][k] for k in range(3)]
        d2 = [P[i + 2][k] - P[i + 1][k] for k in range(3)]
        n1, n2 = math.sqrt(sum(v * v for v in d1)), math.sqrt(sum(v * v for v in d2))
        if n1 > 0.01 and n2 > 0.01 and sum(a * b for a, b in zip(d1, d2)) < -0.99 * n1 * n2:
            out.append(f"W{w['no']} doubles back at point {i + 1}")
    for end, pt, nxt in (("a", P[0], P[1]), ("b", P[-1], P[-2])):
        ex = w[end]["t"]["exit"]
        dx, dy = nxt[0] - pt[0], nxt[1] - pt[1]
        if ex in DIRS and (abs(dx) > 0.01 or abs(dy) > 0.01) and dx * DIRS[ex][0] + dy * DIRS[ex][1] <= 0:
            out.append(f"W{w['no']} leaves its {end} end against exit {ex}")
    return out


class Examples(unittest.TestCase):
    def test_examples_pass_checks_and_route_cleanly(self):
        for spec in EXAMPLES:
            with self.subTest(spec=os.path.basename(spec)):
                B = bp.build(spec)
                self.assertEqual(B["problems"], [])
                self.assertEqual(B["warnings"], [])
                self.assertEqual(len(B["wires"]), len(json.loads(bp.read_text(spec))["wires"]))
                for w in B["wires"]:
                    self.assertTrue(w["pts"], f"W{w['no']} has no route")
                    self.assertEqual(route_faults(w), [])
                    self.assertGreater(w["mm"], 0)

    def test_page_and_files_are_written(self):
        for spec in EXAMPLES:
            with self.subTest(spec=os.path.basename(spec)), tempfile.TemporaryDirectory() as out:
                B = bp.build(spec)
                stem = os.path.splitext(os.path.basename(spec))[0]
                path, size, n = bp.write_outputs(B, out, stem)
                page = bp.read_text(path)
                self.assertIsNone(re.search(r"\{\{[A-Z0-9_]+\}\}", page), "a template token was left unfilled")
                for f in ("wiring-on-plate.svg", "cutlist.csv", "cutlist.md"):
                    self.assertTrue(os.path.getsize(os.path.join(out, f)) > 0, f)
                self.assertEqual(len(os.listdir(os.path.join(out, "steps"))), len(B["steps"]))


class Checks(unittest.TestCase):
    def build_with(self, change):
        spec = json.loads(bp.read_text(EXAMPLES[0]))
        change(spec)
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(spec, f)
        try:
            return bp.build(f.name)["problems"]
        finally:
            os.remove(f.name)

    def test_collision(self):
        def move(s):
            next(p for p in s["parts"] if p["id"] == "relay")["x"] = 70
        self.assertTrue(any("collide" in p for p in self.build_with(move)))

    def test_too_close_reports_the_distance(self):
        def move(s):
            next(p for p in s["parts"] if p["id"] == "relay")["x"] = 105
        self.assertIn("controller and relay are 15.0 mm apart; they need 20 mm", self.build_with(move))

    def test_unknown_terminal_names_the_choices(self):
        def bad(s):
            s["wires"][0]["to"] = "fuse.input"
        problems = self.build_with(bad)
        self.assertTrue(any("fuse has no terminal 'input' (it has in, out)" in p for p in problems))
        self.assertFalse(any(p.startswith("step") for p in problems), "a broken wire shouldn't also fail its step")

    def test_stacking_over_a_lower_part_is_allowed(self):
        def stack(s):
            relay = next(p for p in s["parts"] if p["id"] == "relay")
            relay.update(x=40, y=35, z0=30, room=[0, 0, 0, 0])
        self.assertFalse(any("collide" in p for p in self.build_with(stack)))


if __name__ == "__main__":
    unittest.main()
