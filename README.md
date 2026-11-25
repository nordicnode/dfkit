# dfkit

Agent tooling for Dwarf Fortress 0.47.05 + DFHack: a transport (`dfagent`) and
an agent framework (`dfkit`) that observes the fortress, runs verified actions,
pursues persistent goals and reacts to game events.

```
dfkit state                 fortress summary from the world model
dfkit task brew --wait 60   run a composed task and verify it
dfkit goal add drink "drink >= 40" brew --priority 6
dfkit run --interval 15     daemon: events -> goals -> tasks -> journal
```

## Requirements

- Dwarf Fortress 0.47.05 with DFHack (r5) running, RPC enabled on a port
  (`DFHACK_PORT`, default 5001).
- Python 3.10+ and `protobuf` (`pip install -r requirements.txt`).
- The `agent/lua/agent/*.lua` helpers are run inside the game; point DFHack's
  script path at this folder or copy them into `df_linux/hack/scripts/agent/`.

## Layout

```
dfagent.py, dfhack_client.py   RPC transport + CLI
dfkit/                         world model, actions, tasks, goals, events,
                               semantic menus, daemon, CLI
lua/agent/                     DFHack-side helpers (jobs, status, buildings,
                               stockpiles, farm-ready probes, event watcher)
proto/                         DFHack protobuf definitions (+ generated stubs)
docs/FRAMEWORK.md              architecture and verified behaviour
docs/PLAYBOOK.md               hard-won facts about driving DF 0.47.05
```

---

# dfagent — play Dwarf Fortress from a script or an AI agent

Dwarf Fortress 0.47.05 + DFHack 0.47.05-r5 expose a protobuf RPC interface.
`dfagent` is a Python client for it: observe the game, send keys, designate
tiles, run any DFHack command or Lua snippet. No image scraping, no OCR.

```
~/Games/df-0.47.05/agent/
├── dfhack_client.py     RPC transport + generated protobuf stubs
├── dfagent.py           command line interface
├── dfagent              launcher (uses .venv, port 5001)
├── init-agent.txt       vanilla curses profile for readable screen capture
├── proto/               0.47.05-r5 .proto definitions
└── .venv/               protobuf runtime only
```

## Quickstart

```sh
dfagent start --ascii     # launch DF with ASCII tiles, wait for RPC
dfagent screen            # what a human would see, as text
dfagent observe           # JSON: versions, paused, map, units, reports
dfagent stop              # close DF and restore your graphics profile
```

`--ascii` temporarily swaps `data/init/init.txt` for `init-agent.txt`
(vanilla curses font, no graphics, no intro). The Kruggsmash profile is saved
as `init.txt.graphics` and restored by `dfagent stop`. Without `--ascii` the
game looks better but `screen` returns the graphics buffer, which is not text.

Port: the launcher sets `DFHACK_PORT=5001` because 5000 is taken on this
machine. `dfagent` uses the same default; override with `--port` or the env var.

## Commands

| command | what it does |
| --- | --- |
| `start [--ascii]` | launch DF and wait for the RPC port |
| `stop` | close DF and restore the graphics profile |
| `version` | DF, DFHack and RemoteFortressReader versions |
| `where` | mode, current menu, pause state, visible key hints |
| `status` | population, dwarves, idlers, food/drink/wood, threats, job count, wounds |
| `events [--follow] [--skip-backlog]` | JSON-lines event stream: reports, migrants, deaths, threats, mode/pause changes |
| `commands [--search X]` | searchable index of every DFHack command and its description |
| `recipes` | curated action cookbook |
| `cursor [-x N] [-y N] [-z N]` | read or set the map cursor |
| `observe [--screen]` | one JSON snapshot: versions, paused, map, units, reports |
| `screen [--json]` | current screen rendered from the DF text buffer |
| `units [--table] [--limit N]` | every unit, full JSON |
| `unit ID` | one unit |
| `map` | map size, world/save names |
| `scan --x0 .. --x1 .. --y0 .. --y1 .. --z0 .. --z1 .. [--shape wall]` | find tiles of a shape (wall, floor, tree, ramp ...) |
| `undesignate X0 Y0 Z0 X1 Y1 Z1` | clear dig/chop designations in a box |
| `jobs [--limit N]` | queued jobs with type, position, worker and wait timer |
| `diagnose` | reconciles status, buildings, jobs and cancellations into findings |
| `buildings` | workshops, furnaces, beds, farms, manager flag, manager orders |
| `build <name> -x N -y N -z N` | place a workshop/furnace/furniture without the UI |
| `stockpile X0 Y0 Z0 X1 Y1 Z1 --type food [--type wood] [--template ID]` | create a stockpile, optionally copying category settings |
| `order <JobType> [N]` | queue a manager work order (`--reaction NAME` for reactions) |
| `supervise [--once] [--dry-run]` | policy loop: threats, food/drink, migrants, idlers, autosave |
| `blocks --x0 .. --x1 .. --y0 .. --y1 .. --z0 .. --z1 ..` | raw block tiles, water, magma, dig designations |
| `items` | item/material list |
| `reports [--limit N]` | announcements and combat reports |
| `pause on\|off\|toggle` | pause control (falls back to the space key) |
| `key enter esc up down e 1 ...` | inject key presses into any menu |
| `dig X Y Z [...] [--mode ...]` | designate tiles |
| `dig --box X0 Y0 Z0 X1 Y1 Z1 [--mode ...]` | designate a rectangular area |
| `cmd <dfhack command> [args...]` | any DFHack console command |
| `lua <code>` | evaluate Lua inside DFHack |

Exit code 0 on success, 1 on an RPC or connection error. Data on stdout,
errors on stderr.

## The agent loop

See `PLAYBOOK.md` for the full incident and task procedure.

1. `dfagent where` + `dfagent status` + `dfagent screen` — orientation.
2. `dfagent events --follow --skip-backlog` — react to what happens.
3. Decide.
4. Act:
   ```sh
   dfagent key down enter                       # drive a menu
   dfagent dig 100 100 178 --mode channel       # designate tiles
   dfagent lua "df.global.pause_state = false"  # anything Lua can reach
   dfagent cmd quicksave
   ```
4. Let ticks pass (`dfagent pause off`, sleep, `pause on`) and observe again.

Useful Lua probes:

```lua
print(df.global.cursor.x, df.global.cursor.y, df.global.cursor.z)
print(df.global.cur_year, df.global.cur_year_tick)
for _, u in ipairs(df.global.world.units.active) do
  print(u.id, dfhack.units.getReadableName(u))
end
```

## Implementation notes

* **Screen capture.** `CopyScreen` returns DF's 4-byte-per-tile text buffer.
  In 0.47.05 that buffer is stored **column-major** (`index = x * height + y`),
  not row-major as the field order suggests. The renderer accounts for it.
  It only contains text when DF runs without a graphics tileset, hence
  `--ascii`.
* **Pause.** `SetPauseState` sets the flag, but just after a save loads DF
  re-asserts it. `pause` verifies and falls back to injecting the space key.
* **Keys.** `PassKeyboardEvent` pushes SDL 1.2 key events (`type` 2/3,
  `sym` = SDL keysym, `state` 1/0). Keyboard control works in every menu.
* **Map blocks.** `BlockRequest` takes **block** coordinates (`tile // 16`)
  and its `max_z` is **exclusive** (`z0, z1 + 1` to read one z-level). Inside
  a block, tiles are column-major (`(x % 16) * 16 + (y % 16)`), matching the
  screen buffer. `scan` handles all of this.
* **Names.** DFHack returns CP437 bytes; the client decodes UTF-8 when valid
  and falls back to CP437, so dwarven names survive the RPC.
* **Threats.** Real invaders do not always have `isOpposedToLife` set, so the
  status probe also checks `unit.flags1.active_invader`. Both are needed to
  catch sieges and modtools-spawned units.
* **Release the wagon.** Embark supplies start *inside* the wagon
  (`item.flags.in_building`), so no workshop can use the logs until the wagon
  is deconstructed (`buildings.deconstruct`). `diagnose` surfaces the resulting
  "Needs logs" cancellations.
* **Direct workshop jobs.** `q` on a workshop, then `a`, queues a job without
  a manager. This is the reliable path in 0.47.05: manager orders validate but
  do not always spawn jobs, even with an office.
* **Food counts edibles, not just meals.** `status.food` counts FOOD, PLANT,
  MEAT and FISH stack sizes, so a fort with raw plants is not reported as
  starving.
* **Stockpile settings are two-level.** Creating a stockpile sets the category
  flags but leaves the per-subtype vectors empty, and DF only fills those when
  a category is first chosen in the UI. Build one stockpile per category by
  hand once, then create the rest with `--template <its id>`; dwarves will
  haul normally (`StoreItemInStockpile` jobs).
* **Furniture needs an item.** `build bed/chair/table` creates a construction
  site that consumes the matching item, so a carpenter must make one first.
  The q menu on a workshop (`key q`, then `a`) queues those jobs directly,
  without the manager.
* **Do not delete job structs.** DF 0.47.05 crashes when a freed job is still
  referenced. `undesignate` clears designations and lets the game cancel the
  work itself; there is deliberately no "delete job" command.
* **Manager orders.** The shipped `workorder` script checks a stale
  `assignments_by_type` cache and refuses to queue on a fresh fort. `dfagent`
  creates `df.manager_order` records itself (`agent/order.lua`), and the
  manager flag is resolved through `entity.positions.assignments` rather than
  that cache.

## Scope and status

Verified end to end on a real fortress (`region4`, "Lina Yula"):

* generated a world through the UI with `key` presses and `screen` feedback,
* embarked and started a fort ("Ostathîton"),
* `map` returned real dimensions (12×12 blocks, 201 z-levels),
* `units` listed the 7 dwarves and animals by name and position,
* `dig` set a tile designation that was read back from the map,
* `reports` returned in-game announcements with text and coordinates,
* pause/unpause advanced the game clock, `quicksave` wrote `world.sav`.

Not covered: adventure mode, military/work-order automation beyond raw
`cmd` / `lua` calls, and multi-tile map decoding helpers (use `blocks` or Lua).

Regenerate the protobuf stubs if you change DFHack versions:

```sh
cd ~/Games/df-0.47.05/agent
protoc -Iproto --python_out=. proto/*.proto
```


## dfkit — agent framework

`dfagent` is the transport. `dfkit` adds a world model, verified actions,
composed tasks, a semantic menu driver and a daemon loop. See
`docs/FRAMEWORK.md`.

    dfkit state                 fortress summary from the world model
    dfkit snapshot              persist current state to world.db
    dfkit actions               list actions and tasks
    dfkit plan brew             show the plan for a task
    dfkit task brew --wait 60   run it, verify a new drink stack
    dfkit menu ["text"]         parse the current screen; optionally choose
    dfkit run --once            one daemon policy pass
    dfkit journal 20            recent decisions
    dfkit watch                 stream game events to dfkit-events.jsonl
    dfkit events                recent incidents
    dfkit goal add NAME "expr" TASK --priority N
    dfkit goal list|check|done ID
