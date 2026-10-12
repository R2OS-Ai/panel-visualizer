---
name: panel-visualizer
description: >
  Builds an interactive 3-D visualizer for an electrical backplate, control panel or enclosure layout from one JSON spec:
  a 3-D model with exploded view, every wire auto-routed through the gaps between parts, an as-built wiring diagram, a
  step-by-step wiring guide (one picture per step), a numbered wire cut list with lengths (HTML, CSV, Markdown) and
  layout checks (overlaps, clearance, wiring room). Use it whenever someone wants to lay out, visualize, plan, check or
  document the wiring of a panel, backplate, DIN-rail or bus-bar board, junction box, solar/battery box, relay or PLC
  cabinet, or asks for a wire cut list, wiring steps or a 3-D view of their wiring, even if they don't say "visualizer".
  Also use it to change, rebuild or preview a panel spec that already exists.
---

# Panel visualizer

One JSON spec describes the plate, the parts on it, their terminals and the wires. `scripts/build_panel.py` checks the
layout, routes every wire along the open gaps (never over a device), and writes a self-contained page:

- a 3-D model: orbit, five views, Explode, hover names, wire colours by insulation or by group, layer switches;
- the plate seen from the front with every wire on its route and numbered;
- a step-by-step wiring guide: each step's wires in colour, earlier ones grey, with tick boxes;
- the cut list (lengths from the routes + slack + termination allowance), "wire to buy" totals, CSV and Markdown.

Paths below are relative to this skill's folder (its base directory is shown when the skill loads). Python 3.8+, stdlib only.

## Workflow

1. **Get the facts before drawing.** For each part: size (w × h footprint on the plate, d out from it), where its
   terminals are, and how it mounts. For each wire: both ends, gauge, insulation colour. Use datasheet dimensions. When
   a figure is a guess, say so in the part's `note` so nobody drills from it.
2. **Start a spec.** Copy the minimal example, or start from the user's existing list:
   ```bash
   python3 scripts/build_panel.py --init panel.json
   ```
   Read `references/spec.md` for every field. `examples/solar-sensor-station.json` is a full real board (44 wires, bus
   bars stacked on spacers over other parts, wall sockets, a battery in a tray). Copy patterns from it.
3. **Check and route, no files written:**
   ```bash
   python3 scripts/build_panel.py panel.json --check
   ```
   It prints `checks: all passed` or `CHECKS FAILED:` with one line per problem. **Fix the layout, not the check.** Each
   check stands for something physical: a finger and a ring lug fitting between parts, a terminal with room for its
   wires, a wire with somewhere to run. Only use `--force` for a throwaway preview, and say that you did.
4. **Build:**
   ```bash
   python3 scripts/build_panel.py panel.json            # → panel-build/panel.html, wiring-on-plate.svg, steps/, cutlist.csv, cutlist.md
   ```
5. **Look at it before you report.** Serve the build folder (`python3 -m http.server 8792 --directory panel-build`)
   and open `panel.html`. Check the console, screenshot the 3-D view and the plate diagram, and read the routes. A wire
   that loops the whole plate usually means a terminal's `exit` points the wrong way. The page loads three.js r128 and
   fonts from public CDNs, so it needs the network. Opening the HTML file directly also works.
6. **Report briefly:** plate size, wire count and total metres, any check you couldn't satisfy, any guessed dimension.

Print the cut list in chat (no files) with `--wires`, optionally filtered by part id or wire number:

```bash
python3 scripts/build_panel.py panel.json --wires            # all wires, markdown table
python3 scripts/build_panel.py panel.json --wires relay 12   # wires touching the relay, and wire 12
```

## Getting the spec right

- **Frame:** origin at the plate's bottom-left, x right, y up, z out of the plate's front face. Units mm. A part's
  `x, y` is its bottom-left corner; `z0` lifts it onto spacers so it can stand over lower parts.
- **Terminals** say where the wire lands *and which way it leaves*: `"bottom@30"` is 30 mm along the bottom edge,
  leaving downward; `"face@9,10>down"` is on the top face, leaving downward. Get the exits right and the routes come
  out right. `strips` place a row of screws; `busbar` places studs A/B and screws 1..N for you.
- **Stacking:** a part with `z0` above another part's top (`z0 + d`) may sit over it, like bus bars on spacers over a
  relay. Wire the lower part first. The `steps` should say so.
- **Wall items** (`"mount": "wall"`: glands, sockets, antennas, earth studs) sit just outside the plate's edges. They
  never block routes.
- **Wire numbers are list positions.** Add new wires at the end. If you insert or delete in the middle, tell the user
  the numbers shifted, because labels and printed cut lists use them.
- **Steps** list wires by number, by `id` or by `"group:<id>"`. Put power sources last (battery, mains, solar) and
  say "fuse out" or "breaker off". The build warns about wires that are in no step.
- **Room and gap:** `gap` is the minimum clearance between parts. `room` is wiring room kept clear on each side of a
  part, where its wires leave. `lanes` are open strips kept clear for bundles; each one becomes a routing channel.

## Changing the visualizer itself

- `scripts/build_panel.py`: checks, routing (channels in the gaps → Dijkstra with a bend cost), 3-D scene, SVGs,
  outputs. `assets/page.html` is the page template (`{{TOKENS}}` filled by the build). Never hand-edit a built page:
  it's regenerated.
- Keep it stdlib-only and the page self-contained, so it works from a plain file or any static host.
- After a change, rebuild both examples and look at both pages:
  ```bash
  python3 scripts/build_panel.py examples/minimal.json && python3 scripts/build_panel.py examples/solar-sensor-station.json
  ```
