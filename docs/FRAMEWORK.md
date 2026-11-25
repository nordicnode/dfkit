# dfkit — the agent framework

`dfagent` is a transport: it can send any DFHack command. `dfkit` is the layer
above it that lets an agent *act with intent*: observe a typed world, pick an
action whose preconditions hold, execute it, and prove it worked.

## Layers

```
dfkit state / task / run            CLI for a human or an agent
        │
   daemon.tick()                    policy loop: observe → decide → act → journal
        │
   tasks.py                          composed goals (brew, cook, build, …)
        │
   actions.py                        typed actions, each verifies its effect
        │
   model.py                          world model + SQLite history
        │
   dfhack_client (RPC) → DFHack Lua  agent/*.lua helpers
```

### 1. World model (`dfkit/model.py`, `world.db`)

Every tick stores one snapshot: status (population, food, drink, threats,
idlers), buildings (workshops with ids and tiles, stockpiles), jobs, inventory
counts, and the tail of the report log. History is kept in SQLite so an agent
can answer "what changed since the last tick" instead of re-deriving state.

Queries: `workshop(kind)`, `stockpiles()`, `item_count(name)`,
`find_area(w, h)` (free floor with no building), `ready()` (brewability and
empty storage), `recent_cancels()`.

### 2. Actions (`dfkit/actions.py`)

An action returns `{ok, detail, evidence}`. It checks the world before acting
and re-reads it afterwards, so a "success" always means "verified in the game".

| action | verifies |
|---|---|
| `pause` | `client.paused()` equals the request |
| `dig` | designation count in the box via `agent/count_dig` |
| `build` | building count rose and the new building id exists |
| `queue_job` | workshop job id appears in the job list |
| `stockpile` | new stockpile id + type flags |
| `labor` | number of dwarves whose labor changed |
| `discard_job` | releases the items the stale job held |
| `deconstruct` | `dfhack.buildings.deconstruct` result |

Jobs are queued **without the UI** (`agent/queue_job.lua`). The important,
non-obvious step is that a workshop job must also be inserted into
`building.jobs`; `linkIntoWorld` alone leaves it never dispatched.

### 3. Tasks (`dfkit/tasks.py`)

A task is an ordered plan with honest blocking reasons:

- `brew`: still → brewable plant → empty barrel → queue → verify a **new drink
  stack** (total drink is unreliable because dwarves drink concurrently).
- `cook`: kitchen → `PrepareMeal`.
- `still` / `carpenter` / `kitchen`: build if missing (`find_area`).
- `food_stockpile`, `autolabor`.

Dry runs return the plan only, so an agent can inspect intent before acting.

### 4. Semantic menus (`dfkit/ui.py`)

Some systems (military, trade, hospital, designations) have no API. Instead of
hard-coded key sequences, the current screen is parsed into
`{key, label}` options:

```
$ dfkit menu
b: Building   r: Reports
d: Designations   o: Set Order
$ dfkit menu "designations"      # presses 'd'
```

Both DF label styles are handled: `b: Building` and `Brew drink from plant (b)`.

### 5. Goals and planner (`dfkit/goals.py`)

Goals are persistent conditions with a task attached:

```
dfkit goal add plant_supply "brewable_plants >= 8" gather --priority 7
dfkit goal add brew_drink   "drink >= 40"          brew   --priority 6
dfkit goal add cook_food    "food >= 40"           cook   --priority 4
dfkit goal list / check / done <id>
```

The planner advances one unsatisfied goal per tick: highest priority first,
skipping goals whose last attempt failed (3 minute backoff, so one impossible
goal cannot starve the rest). Expressions are evaluated over live variables:
`drink`, `food`, `population`, `idlers`, `threats`, `brewable_plants`,
`empty_barrels`, `plants`, `stockpiles`, plus any inventory count in lower case.

### 6. Event stream (`dfkit/events.py`, `agent/watch.lua`)

`dfkit watch` registers DFHack EventManager handlers that append incidents to
`df_linux/dfkit-events.jsonl`: job completion, unit death, reports, invasions,
hostile spawns. The daemon drains the file by byte offset (stored in `meta`),
journals each event, and pauses the game on an invasion or hostile spawn
before any task runs.

### 7. Daemon (`dfkit/daemon.py`)

One policy pass: refresh the model; if threats exist, pause and journal; else
run tasks whose preconditions trip (drink < 20, food < 15, many idlers). Every
decision and result is appended to the `journal` table.

## Verified end-to-end

- Goal loop: `gather` → `brew` → `cook` executed over three ticks, each
  verified (new drink stack, new meal job); blocked goals report their exact
  precondition instead of retrying blindly.
- `dfkit task brew --wait 40` → **ok, new drink stack 1760**: the full
  still → plants → barrel → brew → verify chain now succeeds.
- Plant supply: `getplants -a -s -n 4` designated 64 wild plants, 46 gather
  jobs, plants appeared in stock.
- Farm plot: construction + crop assignment work (`plant_id` = plant raw id,
  verified with radish = 65), but **surface plots reject cave crops** (plump
  helmet) — brewing needs a cave farm or gathered plants.


- `dfkit state` — full fortress summary from the model.
- `dfkit build`/`queue_job` — carpenter job produced a bed (item count 0 → 1).
- `dfkit menu` + `select` — opened the designations menu by label.
- `discard_job` — released a plant held by stale jobs.
- `brew` precondition chain — correctly blocked on "no empty barrel" and
  "no brewable plants"; empty-barrel count fixed by making a barrel.

## Known gaps (honest)

- **Custom reactions** (`BREW_DRINK_FROM_PLANT`) execute only when a real
  plant and an empty barrel exist; plants conjured with `modtools/create-item`
  are rejected as reagents. Real supply = farm plot or Gather Plants.
- Farm plots build and accept crops, but no `PlantSeeds` job is scheduled even
  with `plant_id` set and `autofarm` enabled. Gathering wild plants is the
  working supply path; an underground plot needs a code dig to understand.
- The event stream is registered and `job_completed` events were observed, but
  report/invasion capture and the threat branch still need a live incident.
- No goal persistence yet: the daemon's policy is a fixed rule list.
- Military, trade, hospital, justice: only via `ui` + cursor, not wrapped.
- The world model is polled, not event-driven. DFHack's EventManager
  (`onJobCompleted`, `onUnitDeath`, `onReport`) is the next step for true
  reaction to incidents.

## Next steps

1. Farm-plot action + season crop assignment (real plant supply).
2. Event-driven daemon via `EventManager` (siege, death, job cancel).
3. Goals file with priorities, so an agent can say "get to 100 drink" and the
   daemon keeps working toward it across restarts.
4. Wrap military and trade through `ui`: parse the screen, act on labels.
