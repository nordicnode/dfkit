# Playing Dwarf Fortress as an agent

A practical procedure for an AI agent driving DF 0.47.05 through `dfagent`.
The loop is always: **observe → decide → act → verify**.

## 0. Orientation (every session)

```sh
dfagent start --ascii        # or attach to a running game
dfagent where                # mode, menu, pause state, visible key hints
dfagent status               # population, idlers, food, drink, threats, jobs
dfagent screen               # the actual screen, as text
```

`where` tells you which menu you are in; `screen` tells you what it says.
Never act blind in a menu: read it first, then send the key.

## 1. Watching for incidents

```sh
dfagent events --follow --skip-backlog --interval 1
```

One JSON object per line:

| event | meaning | typical response |
| --- | --- | --- |
| `report` | in-game announcement (job cancel, death, mood, caravan, siege) | read the text, act |
| `threat` | hostile unit appeared | pause, check `units`, raise military / burrow |
| `citizen_new` | migrant or birth | beds, food, labors |
| `citizen_gone` | death or left the map | check `reports`, replace the role |
| `pause` / `mode` / `year` | state transitions | re-orient with `where` |

Start the watcher before unpausing; `--skip-backlog` avoids replaying old
reports. Each line is flushed, so a supervisor can read it as a stream.

## 2. Incident playbook

**Job cancelled** — the report names the dwarf and the job. `dfagent reports`
gives coordinates. Fix the cause (missing material, unreachable tile, no
workshop) or cancel the order with `dfagent cmd workorder`.

**No food / no drink** — `status` shows `food` and `drink`. Booze first:

```sh
dfagent cmd workorder add "Make booze" 10
dfagent cmd help workorder          # exact syntax for your version
```

Then build a still/kitchen through the build menu (`dfagent key b`), or
designate plant gathering.

**Migrants** — every `citizen_new` needs a bed:
`dfagent cmd workorder add "Make bed" 1` per dwarf, then assign labors with
`dfagent cmd autolabor 1`.

**Threat** — pause immediately, read the screen:

```sh
dfagent pause on
dfagent status                      # threat_list has id, name, position
dfagent units --table               # everyone, including invaders
dfagent key m                       # military screen if you need squads
```

Use burrows/civilian alerts through the `i` (Zones) and `m` (Military) menus.
Combat itself runs on its own once squads are stationed.

**Wounded** — `status.wounded` counts dwarves with wounds. Build a hospital
zone (`i` menu), enable the Chief Medical Dwarf labor, stock it with thread,
cloth, splints and crutches.

**Strange mood** — a dwarf stops working and claims a workshop. Read
`reports`; make sure the workshop and the material exist. If the mood fails,
the dwarf goes insane (`status.threats` may rise).

**Caravan / trade** — `autotrade` handles hauling; build a trade depot (`b`),
then use the depot menu (`D`) to trade. `dfagent cmd autotrade` toggles it.

**Siege / ambush** — `events` emits `threat` per hostile. Pause, check the
edges of the map with `dfagent screen` after moving the view, seal entrances
with `dfagent dig --box ... --mode dig` or bridges, and station squads.

## 2b. Standing supervision

```sh
dfagent supervise --dry-run        # see what it would do, change nothing
dfagent supervise                  # act
```

The loop evaluates every few seconds and emits one JSON line per decision:

* **threat** → pause the game and name the hostiles
* **food low** → queue `PrepareMeal` if a kitchen and manager exist, otherwise
  alert with the exact missing piece
* **drink low** → queue the brewing reaction if a still and manager exist
* **new citizen** → queue a bed
* **idle dwarves with queued jobs** → enable `autolabor`
* **wounded** → alert for a hospital
* **autosave** → `quicksave` every 5 minutes

Alerts carry the state that justifies them, so an operator can act on the
message without re-reading the whole game.

## 3. Doing work

```sh
# find diggable rock, then dig it (never guess: air is not diggable)
dfagent scan --x0 90 --x1 110 --y0 90 --y1 110 --z0 178 --z1 178 --shape wall --limit 50
dfagent dig --box 90 90 178 99 99 178 --mode dig

# stairs / ramps / channels
dfagent dig 95 95 178 --mode upstair
dfagent dig 95 95 178 --mode channel

# put the cursor somewhere, then drive a menu with keys
dfagent cursor -x 95 -y 95 -z 178
dfagent key d t                     # designations -> chop trees
dfagent key enter                   # corner 1
dfagent key right right down down   # corner 2
dfagent key enter                   # confirm

# clear a bad designation so the queue can drain
dfagent undesignate 100 100 180 115 115 180

# production without the UI
dfagent buildings                   # what exists, is there a manager
dfagent build carpenter -x 92 -y 101 -z 178
dfagent order ConstructBed 1        # manager work order
dfagent order --reaction BREW_DRINK_FROM_PLANT 5

# any DFHack command
dfagent cmd stocks
dfagent cmd quicksave

# anything else: Lua
dfagent lua "print(df.global.cur_year)"
```

Discover commands with `dfagent commands --search <term>` and read their docs
with `dfagent cmd help <command>`. `dfagent recipes` lists the common ones.

## 3a. First hour checklist

1. Deconstruct the wagon to free the embark supplies (logs are inside it).
2. Build a carpenter's workshop and queue a bed and a chair directly:
   `q` on the workshop, `a` for the task list, then the hotkey.
3. Place the chair (`dfagent build chair ...`), then make it a room:
   `q` on it, `r`, `+` to size, and assign it as the manager's office.
4. Make a food stockpile (`p` in the UI, or `dfagent stockpile ... --template ID`
   after one exists) so meals are stored instead of rotting on the floor.
5. Build a kitchen and queue `Prepare Easy Meal` the same way — meals appear
   in the food count within a minute.
6. Build a still before the drink stock runs out; brewing is a reaction at the
   still (`q`, `a`, `b`). It needs *unrotten DRINK_MAT-producing plants* —
   plump helmets qualify, many gathered shrubs do not. A farm plot with spawn
   is the sustainable source.

## 3b. When nothing is happening

```sh
dfagent diagnose
```

It reconciles status, buildings, the job queue and recent cancellations.
Typical findings and what they mean:

* `cancels Construct Bed: Needs logs` — the workshop has no input material.
  Chop trees (`d t`), or check that logs are reachable.
* `N job(s) are waiting without a worker` — stuck queue; check labors and paths.
* `no manager assigned` — work orders will not be processed.
* `no kitchen` / `no still` — food and brewing have no workshop.
* `food is low` and the queue is empty — nothing is producing food.

Furniture placement is a two-step chain: a carpenter makes the item
(`key q` on the workshop, then `a` for the task list), then the item is
placed as a building.

## 4. Safety rules for an agent

1. `dfagent pause on` before anything irreversible.
2. `dfagent cmd quicksave` before large designations, military changes or
   trade.
3. Verify every action: after digging, read the designation back; after a
   build order, check `status.jobs`; after combat, check `reports`.
4. Never edit files outside the game directory or publish credentials. The
   RPC is bound to 127.0.0.1; do not enable `allow_remote`.
5. Never delete job structs directly: 0.47.05 crashes when a unit touches a
   freed job. Clear designations and let the game cancel them.
6. If DF crashes or the RPC stops answering, restart with `dfagent start --ascii`
   and reload the save (Start Playing → the region → Dwarf Fortress).

## 5. Known limits

* No stable API for squads, trade or hospital UI: drive those with keys and
  read the screen.
* Adventure mode uses different screens; the same primitives apply but the
  playbook above is fortress-only.
* `screen` requires the ASCII profile (`start --ascii`); a graphics tileset
  does not write text into DF's buffer.

## Hard-won facts (dfkit era)

- **An open workshop/building menu pauses the game.** Time (`cur_year_tick`)
  does not advance while the `q` menu is open; always `esc` back to normal
  dwarf mode before expecting jobs to run.
- **Workshop jobs need `building.jobs`.** `dfhack.job.linkIntoWorld` alone
  leaves a job in the global list that no dwarf ever claims. Insert it into
  the building's `jobs` vector first (`agent/queue_job.lua`).
- **Brewing has three preconditions**: a still, an unrotten DRINK_MAT plant,
  and an *empty* food-storage item (barrel/pot). `agent/ready.lua` reports all
  three. Plants conjured with modtools are rejected as reagents; use real
  farm/gathered plants.
- **Stale jobs hold items** (`in_job=true`). `agent/discard_job.lua` releases
  them safely; never delete a job struct directly.
- **Semantic menus beat key sequences**: `dfkit menu` parses `key: Label` and
  `Label (key)`; `dfkit menu "text"` presses the right key.
