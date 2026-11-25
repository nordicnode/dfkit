#!/usr/bin/env python3
"""dfagent - observe and control a running Dwarf Fortress 0.47.05 via DFHack.

Examples:
    dfagent observe                 # compact JSON snapshot for an agent loop
    dfagent screen                  # the game screen as text
    dfagent units                   # every unit as JSON
    dfagent unit 42                 # one unit
    dfagent map                     # fortress map info
    dfagent reports                 # announcements / combat reports
    dfagent pause on|off|toggle
    dfagent dig 100 100 150 ...     # designate tiles
    dfagent cmd dig -- 100 100 150  # any DFHack command
    dfagent lua "print(df.global.cur_year)"

All data goes to stdout. Exit code 0 on success, 1 on RPC/connection errors.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from google.protobuf import json_format  # noqa: E402

import dfhack_client as rpc  # noqa: E402

# CP437 upper half, used by DF's text mode.
_CP437_HIGH = (
    "ÇüéâäàåçêëèïîìÄÅÉæÆôöòûùÿÖÜ¢£¥₧ƒáíóúñÑªº¿⌐¬½¼¡«»"
    "░▒▓│┤╡╢╖╕╣║╗╝╜╛┐└┴┬├─┼╞╟╚╔╩╦╠═╬╧╨╤╥╙╘╒╓╫╪┘┌█▄▌▐▀"
    "αßΓπΣσµτΦΘΩδ∞φε∩≡±≥≤⌠⌡÷≈°∙·√ⁿ²■\u00a0"
)
CP437 = [" "] * 32 + [chr(i) for i in range(32, 127)] + ["⌂"] + list(_CP437_HIGH)
assert len(CP437) == 256, len(CP437)

# SDL 1.2 keysyms used by DF's classic interface.
KEYS = {
    "enter": 13, "return": 13, "esc": 27, "escape": 27, "space": 32, "tab": 9,
    "backspace": 8, "up": 273, "down": 274, "right": 275, "left": 276,
    "home": 278, "end": 279, "pageup": 280, "pagedown": 281, "insert": 277,
    "delete": 127, "shift": 304, "ctrl": 306, "alt": 308,
    "plus": 43, "+": 43, "minus": 45, "equals": 61,
}
for _ch in "abcdefghijklmnopqrstuvwxyz0123456789-=[];',./\\` ":
    KEYS.setdefault(_ch, ord(_ch))

# Curated action vocabulary. Each entry is a goal an agent can pursue today
# using DFHack commands that ship with 0.47.05-r5.
RECIPES = [
    {"goal": "let time pass", "run": "dfagent pause off", "note": "space key fallback is built in"},
    {"goal": "stop time to think", "run": "dfagent pause on", "note": ""},
    {"goal": "dig an area", "run": "dfagent dig --box X0 Y0 Z0 X1 Y1 Z1 --mode dig", "note": "also channel/ramp/stair modes"},
    {"goal": "chop trees", "run": "dfagent cursor -x X -y Y -z Z; dfagent key d t", "note": "then enter, move the corner, enter"},
    {"goal": "gather plants", "run": "dfagent lua \"local u=df.global.world.units.active[0]\"", "note": "use the d: Designations menu or Lua tile designations"},
    {"goal": "assign labors automatically", "run": "dfagent cmd autolabor 1", "note": "0 disables; autolabor-artisans adds specialties"},
    {"goal": "queue production", "run": "dfagent cmd help workorder", "note": "workorder add/import, then workflow for automation"},
    {"goal": "check stocks", "run": "dfagent cmd stocks", "note": "or dfagent status for food/drink counts"},
    {"goal": "place furniture/buildings", "run": "dfagent key b", "note": "building menu; quickfort can build from blueprints"},
    {"goal": "plan a layout", "run": "dfagent cmd help quickfort", "note": "blueprints/*.csv, gui/quickfort applies them"},
    {"goal": "trade", "run": "dfagent cmd autotrade", "note": "toggle automatic trade; depot UI for manual"},
    {"goal": "military", "run": "dfagent key m", "note": "squads/equipment menus; no stable non-UI API"},
    {"goal": "healthcare", "run": "dfagent cmd help assign-profile", "note": "or dfagent cmd full-heal for cheats"},
    {"goal": "tame animals", "run": "dfagent cmd tame", "note": ""},
    {"goal": "clear mess", "run": "dfagent cmd spotclean", "note": "also clean-smoke, clear-webs"},
    {"goal": "save", "run": "dfagent cmd quicksave", "note": "writes world.sav"},
    {"goal": "inspect a unit", "run": "dfagent unit ID", "note": ""},
    {"goal": "raw scripting", "run": "dfagent lua \"print(df.global.cur_year)\"", "note": "full df.* and dfhack.* API"},
    {"goal": "any DFHack command", "run": "dfagent cmd <command> [args]", "note": "dfagent commands --search NAME to discover"},
]

DIG_MODES = {
    "none": 0,
    "dig": 1,
    "default": 1,
    "stair": 2,
    "updown": 2,
    "channel": 3,
    "ramp": 4,
    "downstair": 5,
    "upstair": 6,
}


def die(message):
    print(message, file=sys.stderr)
    sys.exit(1)


def connect(args):
    try:
        return rpc.connect(port=args.port)
    except (OSError, rpc.RPCError) as exc:
        die(
            f"cannot reach DFHack RPC on 127.0.0.1:{args.port or rpc.DEFAULT_PORT}: {exc}\n"
            "Is Dwarf Fortress running? Start it with ~/Games/df-0.47.05/run.sh\n"
            "The launcher sets DFHACK_PORT=5001 (port 5000 is used by another program)."
        )


def to_dict(message):
    return json_format.MessageToDict(message, preserving_proto_field_name=True)


def emit(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def screen_rows(capture):
    width, height = capture.width, capture.height
    tiles = capture.tiles
    rows = []
    for y in range(height):
        row = []
        for x in range(width):
            # DF 0.47.05 stores the text buffer column-major: x * height + y
            index = x * height + y
            ch = tiles[index].character if index < len(tiles) else 32
            row.append(CP437[ch & 0xFF])
        rows.append("".join(row).rstrip())
    return rows


def unit_summary(unit):
    name = unit.name if unit.HasField("name") else f"unit {unit.id}"
    return {
        "id": unit.id,
        "name": name,
        "pos": [unit.pos_x, unit.pos_y, unit.pos_z],
        "profession_id": unit.profession_id,
        "race": [unit.race.mat_type, unit.race.mat_index] if unit.HasField("race") else None,
        "is_soldier": unit.is_soldier,
    }


# -- commands -----------------------------------------------------------
def install_profile(run_sh, name):
    """Swap data/init/init.txt for an agent-friendly version, keeping a backup."""
    game_dir = os.path.join(os.path.dirname(run_sh), "df_linux")
    init_dir = os.path.join(game_dir, "data", "init")
    live = os.path.join(init_dir, "init.txt")
    backup = os.path.join(init_dir, "init.txt.graphics")
    profile = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"init-{name}.txt")
    if not os.path.exists(profile):
        die(f"missing profile: {profile}")
    if not os.path.exists(backup):
        os.replace(live, backup)
    with open(profile, "rb") as src, open(live, "wb") as dst:
        dst.write(src.read())
    return live, backup


def restore_profile(run_sh):
    game_dir = os.path.join(os.path.dirname(run_sh), "df_linux")
    init_dir = os.path.join(game_dir, "data", "init")
    live = os.path.join(init_dir, "init.txt")
    backup = os.path.join(init_dir, "init.txt.graphics")
    if os.path.exists(backup):
        os.replace(backup, live)
        return True
    return False


def cmd_start(client, args):
    """Launch DF if it is not already reachable."""
    if args.ascii:
        install_profile(args.run_sh, "agent")
    if client is not None:
        emit({"started": False, "reason": "DFHack RPC already reachable"})
        return
    run_sh = args.run_sh
    if not os.access(run_sh, os.X_OK):
        die(f"launcher not executable: {run_sh}")
    env = dict(os.environ, DFHACK_PORT=str(args.port))
    subprocess.Popen([run_sh], cwd=os.path.dirname(run_sh), env=env,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    deadline = time.time() + 90
    while time.time() < deadline:
        try:
            probe = rpc.connect(port=args.port, timeout=1.0)
        except (OSError, rpc.RPCError):
            time.sleep(1.0)
            continue
        version = to_dict(probe.version())
        probe.close()
        emit({"started": True, "version": version})
        return
    die("DF did not open its RPC port within 90s; check df_linux/stderr.log")


def cmd_stop(client, args):
    try:
        client.run_command("die")
    except (rpc.RPCError, OSError):
        pass  # the connection dies with the game
    if restore_profile(args.run_sh):
        emit({"stopped": True, "profile_restored": True})
    else:
        emit({"stopped": True})


def cmd_version(client, args):
    emit(to_dict(client.version()))


def cmd_pause(client, args):
    current = client.paused()
    if args.state == "toggle":
        target = not current
    else:
        target = args.state == "on"
    if target != current:
        client.set_paused(target)
        time.sleep(0.2)
        # After a save is loaded DF re-asserts the pause flag; space always works.
        if client.paused() != target:
            client.send_keys([KEYS["space"]])
            time.sleep(0.2)
    emit({"paused_before": current, "paused": client.paused()})


def cmd_screen(client, args):
    capture = client.screen()
    if args.json:
        emit({
            "width": capture.width,
            "height": capture.height,
            "tiles": [
                {"char": CP437[t.character & 0xFF], "fg": t.foreground, "bg": t.background}
                for t in capture.tiles
            ],
        })
        return
    print("\n".join(screen_rows(capture)))


def cmd_units(client, args):
    units = client.units()
    if args.limit:
        units = units[: args.limit]
    if args.table:
        for unit in units:
            s = unit_summary(unit)
            print(f"{s['id']:>6}  {s['pos']}  {s['name']}")
        return
    emit([to_dict(u) for u in units])


def cmd_unit(client, args):
    for unit in client.units():
        if unit.id == args.id:
            emit(to_dict(unit))
            return
    die(f"no unit with id {args.id} (fortress loaded?)")


def cmd_map(client, args):
    emit(to_dict(client.map_info()))


def fetch_blocks(client, x0, x1, y0, y1, z0, z1):
    """Get every map block covering a tile box.

    RemoteFortressReader takes *block* coordinates for x/y and treats max_z as
    exclusive. Tile data inside a block is stored column-major (x * 16 + y).
    """
    x0, x1 = sorted((x0, x1))
    y0, y1 = sorted((y0, y1))
    z0, z1 = sorted((z0, z1))
    client.simple("ResetMapHashes")
    return client.blocks(x0 // 16, x1 // 16 + 1, y0 // 16, y1 // 16 + 1,
                         z0, z1 + 1, blocks_needed=100000).map_blocks


def block_tile(tiles, x, y):
    index = (x % 16) * 16 + (y % 16)
    return tiles[index] if index < len(tiles) else None


def cmd_blocks(client, args):
    out = []
    for block in fetch_blocks(client, args.x0, args.x1, args.y0, args.y1, args.z0, args.z1):
        tiles = list(block.tiles)
        out.append({
            "map": [block.map_x, block.map_y, block.map_z],
            "tiles": tiles,
            "hidden": [bool(v) for v in block.hidden],
            "water": list(block.water),
            "magma": list(block.magma),
            "dig": list(block.tile_dig_designation),
        })
    emit({"map_x": block_list.map_x, "map_y": block_list.map_y, "blocks": out})


SHAPES = {
    "empty": 0, "floor": 1, "boulder": 2, "pebbles": 3, "wall": 4,
    "fortification": 5, "stair_up": 6, "stair_down": 7, "stair_updown": 8,
    "ramp": 9, "ramp_top": 10, "tree": 13, "sapling": 14, "shrub": 15,
}


def cmd_scan(client, args):
    shape = SHAPES[args.shape]
    types = client.simple("GetTiletypeList").tiletype_list
    shape_of = {t.id: t.shape for t in types}
    name_of = {t.id: (t.caption or t.name or str(t.id)) for t in types}

    x0, x1 = sorted((args.x0, args.x1))
    y0, y1 = sorted((args.y0, args.y1))
    z0, z1 = sorted((args.z0, args.z1))
    blocks = {}
    for block in fetch_blocks(client, x0, x1, y0, y1, z0, z1):
        blocks[(block.map_x // 16, block.map_y // 16, block.map_z)] = list(block.tiles)

    found = []
    for z in range(z0, z1 + 1):
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                tiles = blocks.get((x // 16, y // 16, z))
                if tiles is None:
                    continue
                tile_id = block_tile(tiles, x, y)
                if tile_id is None:
                    continue
                if shape_of.get(tile_id) == shape:
                    found.append([x, y, z])
                    if len(found) >= args.limit:
                        break
            if len(found) >= args.limit:
                break
        if len(found) >= args.limit:
            break
    emit({"shape": args.shape, "count": len(found), "tiles": found})


def cmd_items(client, args):
    material_list = client.items()
    emit(to_dict(material_list))


def cmd_reports(client, args):
    reports = client.reports()
    if args.limit:
        reports = reports[-args.limit:]
    emit([to_dict(r) for r in reports])


def cmd_observe(client, args):
    snapshot = {
        "version": to_dict(client.version()),
        "paused": client.paused(),
    }
    try:
        snapshot["map"] = to_dict(client.map_info())
    except rpc.RPCError as exc:
        snapshot["map"] = None
        snapshot["map_error"] = str(exc)
    try:
        snapshot["units"] = [unit_summary(u) for u in client.units()]
    except rpc.RPCError:
        snapshot["units"] = []
    try:
        snapshot["reports"] = [to_dict(r) for r in client.reports()][-10:]
    except rpc.RPCError:
        snapshot["reports"] = []
    if args.screen:
        snapshot["screen"] = screen_rows(client.screen())
    emit(snapshot)


def cmd_dig(client, args):
    if args.box:
        if len(args.coords) != 6:
            die("--box needs x0 y0 z0 x1 y1 z1")
        x0, y0, z0, x1, y1, z1 = args.coords
        points = [(x, y, z)
                  for z in range(min(z0, z1), max(z0, z1) + 1)
                  for x in range(min(x0, x1), max(x0, x1) + 1)
                  for y in range(min(y0, y1), max(y0, y1) + 1)]
        if len(points) > 2000:
            die(f"refusing to designate {len(points)} tiles at once (limit 2000)")
    else:
        if len(args.coords) % 3:
            die("coordinates must be x y z triplets")
        points = list(zip(args.coords[0::3], args.coords[1::3], args.coords[2::3]))
    mode = DIG_MODES[args.mode]
    client.dig(points, designation=mode)
    emit({"designated": len(points), "mode": args.mode})


def cmd_where(client, args):
    status = json.loads(client.run_command("agent/status")[1])
    hints = {
        "viewscreen_titlest": "title screen: up/down/enter (enter opens the save list)",
        "viewscreen_new_regionst": "world generation: arrows change settings, y starts, esc aborts",
        "viewscreen_choose_start_sitest": "embark map: arrows move, umkh resize, e embarks",
        "viewscreen_setupdwarfgamest": "embark setup: enter = Play Now",
        "viewscreen_dwarfmodest": "fortress: a announcements, b build, d designations, u units, m military",
        "viewscreen_textviewerst": "text screen: enter/esc to continue",
        "viewscreen_optionst": "options: esc returns to title",
    }
    keys = []
    try:
        for row in screen_rows(client.screen()):
            for token in re.split(r"\s{2,}", row):
                match = re.match(r"^([A-Za-z0-9]{1,4}):\s+(.+)$", token.strip())
                if match:
                    entry = {"key": match.group(1), "label": match.group(2).strip()}
                    if entry not in keys:
                        keys.append(entry)
    except rpc.RPCError:
        pass
    emit({
        "viewscreen": status["viewscreen"],
        "game_mode": status["game_mode"],
        "paused": status["paused"],
        "hint": hints.get(status["viewscreen"], "read the screen with dfagent screen"),
        "keys": keys[:24],
    })


def cmd_status(client, args):
    raw = client.run_command("agent/status")[1]
    emit(json.loads(raw))


def cmd_events(client, args):
    seen_reports = set()
    citizens = {}
    threats = {}
    last = {"paused": None, "viewscreen": None, "year": None}
    emitted = 0

    def out(event):
        nonlocal emitted
        event["at"] = time.strftime("%H:%M:%S")
        print(json.dumps(event, ensure_ascii=False), flush=True)
        emitted += 1

    while True:
        status = json.loads(client.run_command("agent/status")[1])
        if last["paused"] is None and args.skip_backlog:
            for r in client.reports():
                seen_reports.add(f"{r.id}:{r.year}:{r.time}:{r.text}")
        current_citizens = {c["id"]: c for c in status["citizens"]}
        current_threats = {t["id"]: t for t in status["threat_list"]}

        if last["paused"] is None:
            out({"event": "state", "viewscreen": status["viewscreen"],
                 "paused": status["paused"], "year": status["year"],
                 "population": status["population"], "idlers": status["idlers"],
                 "food": status["food"], "drink": status["drink"],
                 "threats": status["threats"]})
        else:
            if status["viewscreen"] != last["viewscreen"]:
                out({"event": "mode", "viewscreen": status["viewscreen"]})
            if status["paused"] != last["paused"]:
                out({"event": "pause", "paused": status["paused"]})
            if status["year"] != last["year"]:
                out({"event": "year", "year": status["year"]})
            for uid, c in current_citizens.items():
                if uid not in citizens:
                    out({"event": "citizen_new", "id": uid, "name": c["name"], "pos": c["pos"]})
            for uid, c in citizens.items():
                if uid not in current_citizens:
                    out({"event": "citizen_gone", "id": uid, "name": c["name"], "pos": c["pos"]})
            for tid, t in current_threats.items():
                if tid not in threats:
                    out({"event": "threat", "id": tid, "name": t["name"], "pos": t["pos"]})

        try:
            reports = client.reports()
        except rpc.RPCError:
            reports = []
        for report in reports:
            key = f"{report.id}:{report.year}:{report.time}:{report.text}"
            if key in seen_reports:
                continue
            seen_reports.add(key)
            out({"event": "report", "text": report.text.strip(),
                 "pos": [report.pos.x, report.pos.y, report.pos.z],
                 "announcement": report.announcement, "repeat": report.repeat_count})
        if len(seen_reports) > 2000:
            seen_reports = set(list(seen_reports)[-500:])

        citizens, threats = current_citizens, current_threats
        last = {"paused": status["paused"], "viewscreen": status["viewscreen"],
                "year": status["year"]}

        if args.limit and emitted >= args.limit:
            return
        if not args.follow:
            return
        time.sleep(args.interval)


def cmd_commands(client, args):
    ok, text = client.run_command("ls")
    if not ok:
        die(text or "could not list commands")
    entries = []
    plugin = "builtin"
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped in ("builtin:", "plugins:"):
            if stripped == "plugins:":
                plugin = "plugins"
            continue
        if stripped.endswith(":") and " - " not in stripped:
            plugin = stripped[:-1]
            continue
        m = re.match(r"^(\S+)\s+-\s+(.*)$", stripped)
        if not m:
            continue
        names, description = m.group(1), m.group(2)
        entries.append({"name": names.split("|")[0], "aliases": names.split("|")[1:],
                        "description": description, "plugin": plugin})
    if args.search:
        pattern = re.compile(args.search, re.I)
        entries = [e for e in entries if pattern.search(e["name"]) or pattern.search(e["description"])]
    if args.json:
        emit(entries)
        return
    for e in entries:
        print(f"{e['name']:<28} {e['description']}")


def cmd_recipes(client, args):
    if args.json:
        emit(RECIPES)
        return
    for r in RECIPES:
        print(f"{r['goal']}\n    {r['run']}" + (f"\n    ({r['note']})" if r['note'] else ""))


def cmd_cursor(client, args):
    if args.x is None and args.y is None and args.z is None:
        result = json.loads(client.run_command("agent/cursor")[1])
        emit(result)
        return
    code = ("local c=df.global.cursor; c.x=%s; c.y=%s; c.z=%s; "
            "print(require('json').encode({x=c.x,y=c.y,z=c.z}))"
            % (args.x, args.y, args.z))
    ok, text = client.run_lua(code)
    if not ok:
        die(text)
    emit(json.loads(text))


def cmd_key(client, args):
    syms = []
    for name in args.keys:
        key = name.lower()
        if key not in KEYS:
            die(f"unknown key {name!r}; use a letter, digit or one of: " +
                ", ".join(sorted(k for k in KEYS if len(k) > 1)))
        syms.append(KEYS[key])
    client.send_keys(syms, delay=args.delay)
    emit({"sent": args.keys})


def cmd_undesignate(client, args):
    if len(args.coords) != 6:
        die("usage: undesignate X0 Y0 Z0 X1 Y1 Z1")
    ok, text = client.run_command("agent/undesignate",
                                  *[str(v) for v in args.coords])
    print(text.strip())
    if not ok:
        sys.exit(1)


def cmd_jobs(client, args):
    emit(json.loads(client.run_command("agent/jobs", str(args.limit))[1]))


def cmd_diagnose(client, args):
    status = json.loads(client.run_command("agent/status")[1])
    bld = json.loads(client.run_command("agent/buildings")[1])
    jobs = json.loads(client.run_command("agent/jobs", "80")[1])
    reports = [r.text.strip() for r in client.reports()]

    findings = []
    if status["paused"]:
        findings.append("game is paused; time is not passing (dfagent pause off)")
    if status["population"] == 0:
        findings.append("no citizens on the map")
    if status["food"] < 10:
        findings.append(f"food is low ({status['food']})")
    if status["drink"] < 10:
        findings.append(f"drink is low ({status['drink']})")
    workshops = bld.get("workshops") if isinstance(bld.get("workshops"), dict) else {}
    if not workshops:
        findings.append("no workshops exist; nothing can be produced")
    if not bld["manager"]:
        findings.append("no manager assigned; work orders will not be processed")
    if status["jobs"] == 0 and status["population"] > 0:
        findings.append("job queue is empty; designate work or queue orders")
    if status["jobs"] > 0 and status["idlers"] == status["dwarves"]:
        findings.append("everyone is idle while jobs are queued; check labors (autolabor)")
    stuck = [j for j in jobs["jobs"] if not j.get("worker") and (j.get("wait") or 0) > 0]
    if stuck:
        findings.append(
            f"{len(stuck)} job(s) are waiting without a worker "
            f"(material or path problem): " + ", ".join(sorted({j['type'] for j in stuck})))
    if status["food"] < 10 and not workshops.get("kitchen"):
        findings.append("no kitchen: food cannot be cooked")
    if status["drink"] < 10 and not workshops.get("still"):
        findings.append("no still: brewing needs one")
    cancels = [r for r in reports if "cancels" in r]
    for text in cancels[-6:]:
        findings.append("recent cancellation: " + text)

    emit({
        "paused": status["paused"],
        "population": status["population"],
        "food": status["food"],
        "drink": status["drink"],
        "jobs": jobs["counts"],
        "workshops": workshops,
        "manager": bld["manager"],
        "findings": findings,
    })


def cmd_buildings(client, args):
    emit(json.loads(client.run_command("agent/buildings")[1]))


def cmd_stockpile(client, args):
    if len(args.coords) != 6:
        die("usage: stockpile X0 Y0 Z0 X1 Y1 Z1 --type food [--type ...]")
    extra = list(args.types)
    if args.template:
        extra.append(f"template={args.template}")
    ok, text = client.run_command("agent/stockpile", *[str(v) for v in args.coords], *extra)
    print(text.strip())
    if not ok:
        sys.exit(1)


def cmd_build(client, args):
    ok, text = client.run_command("agent/build", args.building,
                                  str(args.x), str(args.y), str(args.z))
    print(text.strip())
    if not ok:
        sys.exit(1)


def cmd_order(client, args):
    if args.reaction:
        ok, text = client.run_command("agent/order", "CustomReaction",
                                      str(args.amount), args.job)
    else:
        ok, text = client.run_command("agent/order", args.job, str(args.amount))
    if text:
        print(text.strip())
    if not ok:
        sys.exit(1)


def _set_pause(client, target):
    if client.paused() == target:
        return
    client.set_paused(target)
    time.sleep(0.2)
    if client.paused() != target:
        client.send_keys([KEYS["space"]])
        time.sleep(0.2)


def _alerts(args, state, rule, message, cooldown=300):
    now = time.time()
    if now - state["alerted"].get(rule, 0) < cooldown:
        return
    state["alerted"][rule] = now
    print(json.dumps({"event": "alert", "rule": rule, "message": message,
                      "at": time.strftime("%H:%M:%S")}, ensure_ascii=False), flush=True)


def cmd_supervise(client, args):
    state = {"acted": {}, "alerted": {}, "autolabor": None, "saved": time.time(),
             "citizens": None}

    def act(rule, label, fn, cooldown=120):
        now = time.time()
        if now - state["acted"].get(rule, 0) < cooldown:
            return
        state["acted"][rule] = now
        if args.dry_run:
            print(json.dumps({"event": "propose", "rule": rule, "action": label,
                              "at": time.strftime("%H:%M:%S")}), flush=True)
            return
        try:
            fn()
            print(json.dumps({"event": "action", "rule": rule, "action": label,
                              "at": time.strftime("%H:%M:%S")}), flush=True)
        except rpc.RPCError as exc:
            print(json.dumps({"event": "error", "rule": rule, "error": str(exc)}), flush=True)

    while True:
        status = json.loads(client.run_command("agent/status")[1])
        bld = json.loads(client.run_command("agent/buildings")[1])
        # Lua's json.encode renders empty tables as [], so normalise
        workshops = bld.get("workshops") or {}
        workshops = workshops if isinstance(workshops, dict) else {}
        furnaces = bld.get("furnaces") or {}
        furnaces = furnaces if isinstance(furnaces, dict) else {}
        current = {c["id"]: c for c in status["citizens"]}

        if args.once:
            pass  # one evaluation, then exit

        # threats: freeze time and tell the operator
        if status["threats"] > 0:
            if not status["paused"]:
                act("threat", "pause", lambda: _set_pause(client, True), cooldown=30)
            _alerts(args, state, "threat",
                    f"{status['threats']} hostile unit(s): " +
                    ", ".join(t["name"] for t in status["threat_list"][:5]), cooldown=60)

        # food
        if status["population"] > 0 and status["food"] < args.food_min:
            if bld["manager"] and workshops.get("kitchen"):
                act("food", "workorder PrepareMeal 10",
                    lambda: client.run_command("workorder", "PrepareMeal", "10"), cooldown=300)
            else:
                reason = []
                if not bld["manager"]:
                    reason.append("no manager (n menu)")
                if not workshops.get("kitchen"):
                    reason.append("no kitchen (b menu)")
                _alerts(args, state, "food_low",
                        f"food={status['food']} for {status['population']} dwarves; " +
                        ", ".join(reason), cooldown=300)

        # drink — brewing is a reaction at a still
        if status["population"] > 0 and status["drink"] < args.drink_min:
            if bld["manager"] and workshops.get("still"):
                act("drink", "brewing work order",
                    lambda: client.run_command("workorder", json.dumps({
                        "job": "CustomReaction", "reaction": "BREW_DRINK_FROM_PLANT",
                        "amount_total": 10})), cooldown=300)
            else:
                reason = []
                if not bld["manager"]:
                    reason.append("no manager")
                if not workshops.get("still"):
                    reason.append("no still (b menu)")
                _alerts(args, state, "drink_low",
                        f"drink={status['drink']}; " + ", ".join(reason), cooldown=300)

        # migrants need beds
        if state["citizens"] is not None:
            for uid, c in current.items():
                if uid not in state["citizens"]:
                    print(json.dumps({"event": "new_citizen", "id": uid, "name": c["name"],
                                      "at": time.strftime("%H:%M:%S")}, ensure_ascii=False),
                          flush=True)
                    if bld["manager"]:
                        act("beds_" + str(uid), "workorder ConstructBed 1",
                            lambda: client.run_command("workorder", "ConstructBed", "1"), cooldown=60)
        state["citizens"] = current

        # idle dwarves with a job queue usually means missing labors
        if (status["jobs"] > 0 and status["dwarves"] > 0
                and status["idlers"] >= max(2, int(status["dwarves"] * 0.6))
                and state["autolabor"] is not True):
            act("idle", "autolabor 1", lambda: _enable_autolabor(client, state), cooldown=600)

        if status["wounded"] > 0:
            _alerts(args, state, "wounded",
                    f"{status['wounded']} dwarf(s) need care; build a hospital (i menu)", cooldown=600)

        # autosave
        if args.autosave and time.time() - state["saved"] >= args.autosave:
            act("autosave", "quicksave", lambda: client.run_command("quicksave"), cooldown=30)
            state["saved"] = time.time()

        if args.once:
            return
        time.sleep(args.interval)


def _enable_autolabor(client, state):
    ok, text = client.run_command("autolabor", "1")
    if ok:
        state["autolabor"] = True
    else:
        raise rpc.RPCError(text or "autolabor failed")


def cmd_cmd(client, args):
    if not args.argv:
        die("usage: dfagent cmd <dfhack command> [args...]")
    ok, text = client.run_command(args.argv[0], *args.argv[1:])
    print(text, end="" if text.endswith("\n") or not text else "\n")
    if not ok:
        sys.exit(1)


def cmd_lua(client, args):
    code = " ".join(args.code)
    ok, text = client.run_lua(code)
    print(text, end="" if text.endswith("\n") or not text else "\n")
    if not ok:
        sys.exit(1)


# -- parser -------------------------------------------------------------
def build_parser():
    parser = argparse.ArgumentParser(prog="dfagent", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=int(os.environ.get("DFHACK_PORT", rpc.DEFAULT_PORT)))
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("version", help="DFHack and DF versions").set_defaults(func=cmd_version)

    default_run_sh = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "run.sh")
    p = sub.add_parser("start", help="launch DF and wait for the RPC port")
    p.add_argument("--run-sh", default=default_run_sh)
    p.add_argument("--ascii", action="store_true",
                   help="use the vanilla curses tileset so screen text is readable")
    p.set_defaults(func=cmd_start)

    p = sub.add_parser("stop", help="close DF and restore the graphics profile")
    p.add_argument("--run-sh", default=default_run_sh)
    p.set_defaults(func=cmd_stop)

    p = sub.add_parser("observe", help="one JSON snapshot for an agent loop")
    p.add_argument("--screen", action="store_true", help="include the rendered screen")
    p.set_defaults(func=cmd_observe)

    p = sub.add_parser("screen", help="dump the game screen as text")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_screen)

    p = sub.add_parser("units", help="list units")
    p.add_argument("--table", action="store_true", help="plain table instead of JSON")
    p.add_argument("--limit", type=int, default=0)
    p.set_defaults(func=cmd_units)

    p = sub.add_parser("unit", help="show one unit by id")
    p.add_argument("id", type=int)
    p.set_defaults(func=cmd_unit)

    sub.add_parser("map", help="fortress map info").set_defaults(func=cmd_map)

    sub.add_parser("buildings", help="workshops, furnaces, beds, manager, orders").set_defaults(func=cmd_buildings)

    p = sub.add_parser("jobs", help="list queued jobs (type, position, worker)")
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(func=cmd_jobs)

    sub.add_parser("diagnose", help="explain why the fort is or is not progressing").set_defaults(func=cmd_diagnose)

    p = sub.add_parser("undesignate", help="clear dig/chop designations in a box")
    p.add_argument("coords", type=int, nargs=6, metavar=("X0", "Y0", "Z0", "X1", "Y1", "Z1"))
    p.set_defaults(func=cmd_undesignate)

    p = sub.add_parser("stockpile", help="create a stockpile with categories")
    p.add_argument("coords", type=int, nargs=6, metavar=("X0", "Y0", "Z0", "X1", "Y1", "Z1"))
    p.add_argument("--type", dest="types", action="append", required=True,
                   help="food, wood, stone, furniture, gems, cloth ... (repeatable)")
    p.add_argument("--template", type=int, default=None,
                   help="stockpile id to copy category settings from")
    p.set_defaults(func=cmd_stockpile)

    p = sub.add_parser("build", help="place a building without the UI")
    p.add_argument("building", help="carpenter, mason, still, kitchen, bed, door ...")
    p.add_argument("-x", type=int, required=True)
    p.add_argument("-y", type=int, required=True)
    p.add_argument("-z", type=int, required=True)
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("order", help="queue a manager work order")
    p.add_argument("job", help="job type, e.g. PrepareMeal or ConstructBed")
    p.add_argument("amount", type=int, nargs="?", default=1)
    p.add_argument("--reaction", action="store_true", help="job is a reaction name")
    p.set_defaults(func=cmd_order)

    p = sub.add_parser("supervise", help="policy loop: watch and react to incidents")
    p.add_argument("--interval", type=float, default=3.0)
    p.add_argument("--once", action="store_true", help="evaluate rules once and exit")
    p.add_argument("--dry-run", action="store_true", help="report intended actions only")
    p.add_argument("--food-min", type=int, default=10)
    p.add_argument("--drink-min", type=int, default=10)
    p.add_argument("--autosave", type=int, default=300, help="seconds between quicksaves, 0 disables")
    p.set_defaults(func=cmd_supervise)

    p = sub.add_parser("scan", help="find tiles of a given shape (wall, floor, tree ...)")
    for name in ("x0", "x1", "y0", "y1", "z0", "z1"):
        p.add_argument("--" + name, type=int, required=True)
    p.add_argument("--shape", choices=sorted(SHAPES), default="wall")
    p.add_argument("--blocks", type=int, default=1)
    p.add_argument("--limit", type=int, default=2000)
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("blocks", help="raw map blocks for a region")
    for name in ("x0", "x1", "y0", "y1", "z0", "z1"):
        p.add_argument("--" + name, type=int, required=True)
    p.add_argument("--blocks", type=int, default=1)
    p.set_defaults(func=cmd_blocks)

    sub.add_parser("items", help="item/material list").set_defaults(func=cmd_items)

    p = sub.add_parser("reports", help="announcements and combat reports")
    p.add_argument("--limit", type=int, default=0)
    p.set_defaults(func=cmd_reports)

    p = sub.add_parser("pause", help="pause or resume the game")
    p.add_argument("state", choices=["on", "off", "toggle"])
    p.set_defaults(func=cmd_pause)

    p = sub.add_parser("dig", help="designate tiles: x y z [x y z ...] or --box")
    p.add_argument("coords", type=int, nargs="+")
    p.add_argument("--box", action="store_true", help="coords are x0 y0 z0 x1 y1 z1")
    p.add_argument("--mode", choices=sorted(DIG_MODES), default="dig")
    p.set_defaults(func=cmd_dig)

    sub.add_parser("where", help="current mode, menu and key hint").set_defaults(func=cmd_where)
    sub.add_parser("status", help="fortress status: population, idlers, food, threats").set_defaults(func=cmd_status)
    p = sub.add_parser("recipes", help="curated action cookbook")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_recipes)

    p = sub.add_parser("events", help="stream game events as JSON lines")
    p.add_argument("--follow", action="store_true", help="keep watching")
    p.add_argument("--interval", type=float, default=1.0)
    p.add_argument("--limit", type=int, default=0, help="stop after N events")
    p.add_argument("--skip-backlog", action="store_true",
                   help="do not replay reports that already existed at start")
    p.set_defaults(func=cmd_events)

    p = sub.add_parser("commands", help="search the DFHack command index")
    p.add_argument("--search", default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_commands)

    p = sub.add_parser("cursor", help="get or set the map cursor")
    p.add_argument("-x", type=int, default=None)
    p.add_argument("-y", type=int, default=None)
    p.add_argument("-z", type=int, default=None)
    p.set_defaults(func=cmd_cursor)

    p = sub.add_parser("key", help="send key presses (enter, esc, up, down, e, 1 ...)")
    p.add_argument("keys", nargs="+")
    p.add_argument("--delay", type=float, default=0.08, help="seconds between keys")
    p.set_defaults(func=cmd_key)

    p = sub.add_parser("cmd", help="run any DFHack console command")
    p.add_argument("argv", nargs=argparse.REMAINDER)
    p.set_defaults(func=cmd_cmd)

    p = sub.add_parser("lua", help="evaluate Lua inside DFHack")
    p.add_argument("code", nargs=argparse.REMAINDER)
    p.set_defaults(func=cmd_lua)
    return parser


def main():
    args = build_parser().parse_args()
    if args.command == "start":
        try:
            client = rpc.connect(port=args.port, timeout=2.0)
        except (OSError, rpc.RPCError):
            client = None
        cmd_start(client, args)
        if client is not None:
            client.close()
        return
    client = connect(args)
    try:
        args.func(client, args)
    except rpc.RPCError as exc:
        die(f"DFHack error: {exc} {exc.text}".strip())
    finally:
        client.close()


if __name__ == "__main__":
    main()
