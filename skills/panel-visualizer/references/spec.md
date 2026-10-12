# Panel spec reference

One JSON file. Coordinates are in mm, in the plate's frame: the origin is the plate's bottom-left corner, x points
right, y points up (the plate hangs on the back wall of the box), and z points out of the plate's front face toward the
door, with z = 0 on the face.

```json
{
  "title": "12 V pump controller",
  "plate": { "w": 320, "h": 220 },
  "gap": 20,
  "groups": [{ "id": "power", "label": "Supply and bus" }],
  "parts": [ ... ],
  "wires": [ ... ],
  "steps": [ ... ]
}
```

Only `plate.w`, `plate.h` and the `parts` and `wires` you need are required. Everything else has a default.

## Top level

| Field | Default | What it does |
|---|---|---|
| `title` | file name | Page title and heading |
| `eyebrow` | "Panel visualizer" | Small line above the title |
| `intro` | — | Paragraph under the title. `**bold**` and `` `code` `` work; everything else is escaped |
| `description` | generated | The page's meta description |
| `links` | — | `[{ "text": "...", "href": "..." }]`, shown in the eyebrow line |
| `plate` | — | `w`, `h` (required), `t` thickness (5), `color`, `name` (hover text), `note` |
| `gap` | 0 (off) | Minimum clear gap between any two parts at the same depth. 15–25 mm leaves room for fingers and ring lugs |
| `slack` | 0.15 | Cut length = route × (1 + slack) + `ends_mm`, rounded to 10 mm. The route is 3-D: it includes the rise from the plate up to each terminal's height, so a wire's cut length is longer than its line on the plate diagram |
| `ends_mm` | 60 | Allowance for stripping and terminating both ends |
| `colours` | — | Extra insulation colours: `{ "teal": "#178a8a" }` |
| `groups` | from the wires | `[{ "id", "label", "color" }]`: wire groups (duty), in order. They drive the Wires switches, "colour by group" and the default steps. If you list groups, every wire must use one of them |
| `parts` | — | Devices on the plate and items in the box walls, below |
| `wires` | — | Below |
| `steps` | one per group | Below |
| `lanes` | — | Open strips kept clear for bundles: `[{ "x", "y", "w", "h", "label", "allow": [part ids] }]`. A part in a lane fails the check unless it's in `allow`. Each lane becomes a routing channel down its long middle |
| `channels` | — | Extra routing channels taken exactly as given: `{ "y", "x0", "x1" }` (horizontal) or `{ "x", "y0", "y1" }` (vertical). Rarely needed |
| `enclosure` | — | `{ "w", "h", "d" }` inside size, shown as a faint box. Optional `x`, `y` (default: centred on the plate) and `z` (default −(t + 5), just behind the plate) for its back-bottom-left corner, and `name` |
| `facts` | — | Extra fact cards: `[{ "title", "text" }]`. The plate size, wire count and gap cards are automatic |
| `build_order` | — | List of strings, shown as a numbered "Build order" section |

## Parts on the plate

```json
{ "id": "victron", "name": "Victron BlueSolar MPPT 75/10", "label": "Victron",
  "x": 215, "y": 332, "w": 112.9, "h": 99.7, "d": 38.2,
  "color": "#1f7fcc", "room": [0, 0, 34, 0],
  "holes": [[7, 91.9, 4.5, "M4 slot"], [105.9, 91.9, 4.5, "M4 slot"]],
  "strips": [{ "edge": "bottom", "names": ["PV+", "PV-", "BAT+", "BAT-", "LOAD+", "LOAD-"], "at": [30, 42, 58, 70, 86, 98], "z": 18 }],
  "note": "Terminals along its bottom edge." }
```

| Field | Default | What it does |
|---|---|---|
| `id` | required | Unique, no dots. Wires refer to `id.terminal` |
| `name` | id | Full name, shown on hover |
| `label` | — | Short name: the 3-D label, the plate diagram, and the start of wire-end names. Without one the diagram shows the id and there's no 3-D label |
| `x`, `y` | required | Bottom-left corner of the footprint |
| `w`, `h`, `d` | required | Footprint width (x), height (y), and depth out from the plate (z) |
| `z0` | 0 | Stands on spacers this tall. A part may sit over another one if its `z0` is at or above the lower part's top (`z0 + d`). Spacers are drawn under its `holes`, or at its corners |
| `color`, `opacity` | dark grey, 1 | Below 0.5 the part draws as an outline (a tray, a keep-out space) |
| `note` | — | Extra hover text |
| `room` | `[0,0,0,0]` | Wiring room kept clear on the `[left, right, below, above]` sides: where its wires leave. No other part may sit in it, except one entirely under a stacked part's room |
| `gap` | spec `gap` | This part's own clearance. Use a smaller one for bus bars paired 10 mm apart |
| `holes` | — | `[dx, dy, dia]` or `[dx, dy, dia, "kind"]` from the part's corner. A kind containing "slot" draws a ±4 mm slot. Drawn as screws |
| `flange` | 3 | Height of the part's mounting flange, for drawing the screw heads |
| `terminals` | — | `{ "name": terminal }`, below |
| `strips` | — | Rows of terminals, below |
| `busbar` | — | Makes it a bus bar, below |
| `mesh`, `mesh_rot` | — | A real model: path to an STL (relative to the spec), centred on the footprint and sitting on `z0`. `mesh_rot`: 0, 90, 180 or 270° about z. The STL is embedded in the page, so watch the page size |
| `shape` | box | `"cylinder"` draws a round part in the footprint |
| `explode` | 1 | How far Explode lifts it. 0 keeps it still, 1.6 pulls it further (a battery sliding out) |
| `in` | — | The id of the part holding it (a battery in its tray). It isn't checked against its container, and the container blocks routes for it |

### Terminals

A terminal is where a wire lands and the way the wire leaves it. Write it as a short string or as an object.

| Short form | Where | Leaves |
|---|---|---|
| `"bottom@30"` | 30 mm along the bottom edge, 2 mm outside it | down |
| `"top@30"` | along the top edge | up |
| `"left@20"`, `"right@20"` | 20 mm up the left / right edge | left / right |
| `"face@9,10"` | on the top face at (9, 10) | any way |
| `"bottom@30>left"` | add `>exit` to any of them to change the way it leaves | left |

Object form: `{ "x": 9, "y": 10, "z": 38, "exit": "down", "label": "screw 1" }`, or `{ "at": "bottom@30", "z": 18 }`.

- `exit`: `up`, `down`, `left`, `right`, `updown`, `leftright` or `any`. The router goes straight out that way to the
  nearest channel. A wrong exit is the most common cause of a silly route.
- `z` (height out from the plate) defaults to mid-height for edge terminals and just above the top face for face terminals.
- `label` (default: the terminal's name) is used in wire-end names: "Victron PV+", "Relay board screw 6".

### Strips

```json
"strips": [{ "edge": "bottom", "names": ["1", "2", "3", "4"], "start": 20, "pitch": 7, "z": 42, "label": "screw {n}" }]
```

A row of terminals along one edge: positions from `start` + k × `pitch`, or an explicit `at` list. `exit` defaults to the edge's direction.

### Bus bars

```json
"busbar": { "screws": 10, "pitch": 9, "studs": 55, "a_end": "left", "lugs": "down", "cover": "#c9ccd0" }
```

This makes terminals `A` and `B` (studs at the two ends, leaving sideways) and `1`..`N` (screws, leaving by `lugs`:
`up`, `down` or `both`). The screws are centred on the bar, `pitch` apart, numbered from the A end. `studs` is each
stud's distance from the centre (default w/2 − 10; 0 means no studs). It must leave at least 8 mm between a stud and the
end screw, or the check fails. Terminals sit 14 mm up from the bar's base (or at its top if it's shallower). The bar
draws as a 10 mm base with a clear cover up to `d`. In a stacked pair, give the lower bar `lugs: "down"` and the upper
`lugs: "up"`, so every screw stays reachable.

## Items in the box walls

```json
{ "id": "gland", "name": "PV cable gland (right wall)", "label": "PV gland", "mount": "wall", "x": 376, "y": 500,
  "terminals": { "+": { "x": 0, "y": 4 }, "-": { "x": 0, "y": -4 } } }
```

Glands, sockets, connectors, antennas and earth studs. `x, y` is the item's centre, just outside the plate: x < 0 is the
left wall, x > w the right wall, y < 0 the floor, y > h the top. They're drawn as cylinders (`r` 6, `len` 16) pointing
into the box, at height `z` (35). They never block routes and aren't layout-checked. Terminal positions are relative to
the item's centre, and they leave toward the plate unless `exit` says otherwise. An item with no terminals can be wired
by its id alone.

## Wires

```json
{ "id": "pump+", "from": "relay.NO1", "to": "gland_pump.+", "gauge": "18 AWG", "colour": "orange", "group": "load",
  "note": "switched +12 V to the pump" }
```

| Field | What it does |
|---|---|
| `from`, `to` | `part.terminal`, or `part` alone for a part's only (or unnamed `""`) terminal, or its centre if it has none |
| `gauge` | Free text. A number before "AWG" sets the 3-D thickness and groups "wire to buy" |
| `colour` | red, black, white, green, yellow, blue, brown, grey / gray, orange, purple / violet, pink, copper, coax, tan, any `#hex`, or a name from `colours` |
| `group` | A group id |
| `id` | Optional handle for `steps` |
| `from_label`, `to_label` | Override the generated end names (part label + terminal label) |
| `note` | Shown in the cut list and on hover |
| `plan_number` | `false` keeps its number off the overview diagram (useful for many identical leads). It's still numbered in the step pictures and the cut list |
| `r` | 3-D tube radius override |

**Wire number = position in the list (1-based).** Add new wires at the end so existing numbers don't move.

## Steps

```json
{ "title": "Supply last", "wires": ["group:power", 12, "pump+"], "notes": ["Fuse **out** until the end."] }
```

`wires` takes numbers, wire `id`s and `group:<id>`. Each step's picture shows its own wires in colour and earlier steps'
wires in grey. A step with no wires (a final check) is fine. Without `steps`, you get one step per group.

## What the checks catch

- a part off the plate, or its wiring room running off it (with the side and how far);
- two parts colliding at the same depth (stack one with `z0`, or move it);
- two parts closer than `gap` (or their own `gap`), with the actual distance;
- a bus bar whose studs sit on its end screws or off its ends;
- a part sitting in another part's wiring room, unless it's entirely below a stacked part;
- a part in a lane;
- a wire naming a part or terminal that doesn't exist, an unknown colour or group;
- a wire with no route (a terminal pointing into a wall of parts);
- a step naming a wire that doesn't exist. Wires in no step, or in two, are warnings.

## How wires are routed

Channels run through the gaps:

- a line 4–10 mm off each side of every part (half the part's gap, capped), running across the plate until another part
  cuts it, so a channel near a part may belong to its neighbour;
- a ring 4 mm outside the plate's edges, along the box walls (leave that space between the plate and the walls; it's
  also how wires reach wall items);
- the middle of every lane, and any `channels`.

A wire leaves its terminal straight out along its `exit` to the nearest channel past the terminal. It follows the
cheapest path (length plus 12 mm per bend) to the channel nearest its other end, then goes straight in. Runs sit just
off the plate, and each wire is nudged up to ±3 mm so parallel runs don't overlap. Stacked parts block the channels
under them, so wires run around them, never through them.

## Outputs (`<spec>-build/`)

| File | What it is |
|---|---|
| `<spec>.html` | The page: 3-D model, steps, plate diagram, cut list, wire to buy, build order. Self-contained except three.js and fonts from public CDNs |
| `wiring-on-plate.svg` | The plate diagram on its own |
| `steps/step-NN.svg` | Each step's picture, for printing |
| `cutlist.csv`, `cutlist.md` | The cut list. The Markdown also has the wire-to-buy totals |
