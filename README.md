# panel-visualizer

A [Claude Code](https://claude.com/claude-code) skill that turns a list of parts and wires into an interactive page for
an electrical backplate or control panel.

![3-D view of the example solar sensor station](docs/3d-view.png)

From one JSON spec, it builds:

- **a 3-D model**: orbit, five views, an Explode slider, hover names, and switches for wire groups and layers;
- **auto-routed wires**: every wire runs through the gaps between parts (never over a device), in its insulation colour;
- **the plate seen from the front**, with every wire on its route and numbered;
- **a step-by-step wiring guide**: one picture per step, with tick boxes;
- **a cut list** with lengths taken from the routes, plus "wire to buy" totals (HTML, CSV, Markdown);
- **layout checks**: parts that collide, sit closer than your clearance, run off the plate, or block another part's
  wiring room.

The output is a single HTML file. Open it from disk or put it on any static host.

## Install

A Claude Code skill is a folder with a `SKILL.md` in it. To install this one, put the `skills/panel-visualizer` folder
from this repo into `.claude/skills/` in your own repo. Claude Code finds it there, and it shows up in `/skills`.

### Into your repo (recommended)

Run this from your repo's root folder. It downloads only the skill folder:

```bash
mkdir -p .claude/skills && curl -fsSL https://github.com/Parth-Rearden/panel-visualizer/archive/refs/heads/main.tar.gz | tar -xz -C .claude/skills --strip-components=2 panel-visualizer-main/skills/panel-visualizer
```

Then commit it, so everyone who clones your repo gets the skill too:

```bash
git add .claude/skills/panel-visualizer && git commit -m "Add the panel-visualizer skill"
```

<details>
<summary>With <code>git clone</code> instead</summary>

```bash
git clone --depth 1 https://github.com/Parth-Rearden/panel-visualizer /tmp/panel-visualizer
mkdir -p .claude/skills && cp -r /tmp/panel-visualizer/skills/panel-visualizer .claude/skills/
```
</details>

<details>
<summary>Windows (PowerShell)</summary>

```powershell
Invoke-WebRequest https://github.com/Parth-Rearden/panel-visualizer/archive/refs/heads/main.zip -OutFile pv.zip
Expand-Archive pv.zip -DestinationPath pv-tmp
New-Item -ItemType Directory -Force .claude\skills | Out-Null
Copy-Item -Recurse pv-tmp\panel-visualizer-main\skills\panel-visualizer .claude\skills\
Remove-Item -Recurse pv.zip, pv-tmp
```
</details>

<details>
<summary>No terminal: download the ZIP</summary>

1. On this page, click **Code → Download ZIP** and unzip it.
2. In the unzipped folder, open `skills/` and copy the `panel-visualizer` folder.
3. Paste it into your repo at `.claude/skills/`. Create the `.claude` and `skills` folders if they don't exist. On macOS,
   press <kbd>Cmd</kbd>+<kbd>Shift</kbd>+<kbd>.</kbd> in Finder to see folders that start with a dot.
</details>

Afterwards your repo should look like this:

```
your-repo/
└── .claude/
    └── skills/
        └── panel-visualizer/
            ├── SKILL.md            ← must be directly in here
            ├── scripts/build_panel.py
            ├── assets/page.html
            ├── references/spec.md
            └── examples/
```

If `SKILL.md` ends up one level deeper (for example `.claude/skills/panel-visualizer-main/skills/panel-visualizer/`),
Claude Code won't find it. Move the inner `panel-visualizer` folder up into `.claude/skills/`.

### For every project on your machine

The same folder in your home directory makes the skill available everywhere, just for you:

```bash
mkdir -p ~/.claude/skills && curl -fsSL https://github.com/Parth-Rearden/panel-visualizer/archive/refs/heads/main.tar.gz | tar -xz -C ~/.claude/skills --strip-components=2 panel-visualizer-main/skills/panel-visualizer
```

### As a plugin

Inside Claude Code:

```
/plugin marketplace add Parth-Rearden/panel-visualizer
/plugin install panel-visualizer@panel-visualizer
```

Pick a scope when it asks: **project** shares it through your repo's `.claude/settings.json`, and **user** installs it
for every project. Plugin skills are namespaced, so you invoke this one with `/panel-visualizer:panel-visualizer`. Turn
it on and off in `/plugin`.

### Check it worked

1. Start Claude Code in your repo. A session that's already running picks the new skill up by itself. If your repo had
   no `.claude/skills/` folder when the session started, run `/reload-skills` once.
2. Type `/skills`. **panel-visualizer** is in the list with its description. If it isn't set to `on`, select it and
   press <kbd>Space</kbd> or <kbd>Enter</kbd> until it is, then <kbd>Esc</kbd> to save. That choice is saved just for
   you, in `.claude/settings.local.json`.
3. Type `/panel-visualizer` and describe your panel. You can also just ask for a panel layout, and Claude picks the
   skill itself.

### Update or remove

To update, delete the folder and run the install command again:

```bash
rm -rf .claude/skills/panel-visualizer
```

To remove it, just delete the folder.

### Requirements

- [Claude Code](https://claude.com/claude-code).
- Python 3.8 or newer, standard library only, as `python3`. On Windows it's usually `python`: Claude will use whichever
  you have.
- A browser with WebGL to view the page. The page loads three.js from jsDelivr and its fonts from Google Fonts.

## Use it

Invoke it with `/panel-visualizer`, or just describe your panel:

> Lay out my 24 V control panel: a 55 × 90 power supply, a 2-pole breaker, a PLC with I1–I2 and Q1–Q2, two relays and
> + / 0 V bus bars on a 400 × 300 plate. Give me a cut list.

Claude writes the spec, runs the checks, fixes the layout until they pass, builds the page and looks at it.

## Use it without Claude

Python 3.8+, standard library only.

```bash
cd skills/panel-visualizer
python3 scripts/build_panel.py --init my-panel.json    # start from the minimal example
python3 scripts/build_panel.py my-panel.json --check   # checks and routing only, no files
python3 scripts/build_panel.py my-panel.json           # → my-panel-build/my-panel.html
python3 scripts/build_panel.py my-panel.json --wires   # the cut list as a Markdown table
```

A part, a bus bar and a wire look like this:

```jsonc
// a part with a row of terminals along its top edge
{ "id": "relay", "name": "Relay module, 1 channel", "label": "Relay", "x": 130, "y": 30, "w": 50, "h": 40, "d": 20,
  "strips": [{ "edge": "top", "names": ["+", "-", "IN1"], "start": 10, "pitch": 12 }] }

// a bus bar: terminals A, B (studs) and 1–6 (screws)
{ "id": "bar_pos", "name": "Bus bar +12 V", "x": 110, "y": 160, "w": 110, "h": 25, "d": 20,
  "busbar": { "screws": 6, "pitch": 12, "studs": 45, "lugs": "up" } }

// a wire, from part.terminal to part.terminal
{ "from": "bar_pos.2", "to": "relay.+", "gauge": "20 AWG", "colour": "red", "group": "control" }
```

Every field is in [`references/spec.md`](skills/panel-visualizer/references/spec.md).

| Wiring on the plate | One wiring step |
|---|---|
| ![Plate diagram](docs/wiring-on-plate.svg) | ![Step 3](docs/step-03.svg) |

## Examples

| Spec | What it shows |
|---|---|
| [`minimal.json`](skills/panel-visualizer/examples/minimal.json) | A 12 V pump controller: fuse, two bus bars, controller, relay and two glands. 11 wires |
| [`solar-sensor-station.json`](skills/panel-visualizer/examples/solar-sensor-station.json) | A solar sensor station (pictured): a battery in a tray, an MPPT, six bus bars stacked on spacers over other parts, a Modbus relay board, an SSR switching a 24 V sensor rail, and floor sockets. 44 wires |

## How the routing works

A channel runs through every gap: one just off each side of every part, a ring around the plate's edge, and the
middle of any wiring lane you declare. Each wire leaves its terminal in the direction you give it, takes the shortest
path along the channels (with a cost for each bend), and goes straight into the terminal at the other end. Parallel
runs are nudged apart. Cut length is the 3-D route, plus slack, plus an allowance for both terminations.

## Repository layout

```
.claude-plugin/          plugin and marketplace manifests
skills/panel-visualizer/
  SKILL.md               what Claude follows
  scripts/build_panel.py checks, routing, 3-D scene, diagrams and cut list
  assets/page.html       the page template
  references/spec.md     every spec field
  examples/              two specs to copy from
tests/                   python3 -m unittest discover -s tests
```

## Contributing

Issues and pull requests are welcome. Run the tests before sending a change, and rebuild both examples and look at the
pages if you touched the routing or the template.

## License

MIT
