"""dfkit - an agent-facing layer over DFHack.

    dfkit state                 one-screen fortress summary
    dfkit snapshot              refresh and persist the world model
    dfkit actions               list typed actions
    dfkit plan <task>           show the plan without doing it
    dfkit task <task> [--wait N] run a composed task
    dfkit menu                  semantic options on the current screen
    dfkit select <text>         choose a menu option by label
    dfkit run [--once]          daemon policy loop
    dfkit journal [N]           recent journal entries
"""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
AGENT = os.path.dirname(HERE)
sys.path.insert(0, AGENT)

import dfhack_client as rpc  # noqa: E402

from dfkit import actions, daemon, goals, tasks, ui  # noqa: E402
from dfkit.model import WorldModel  # noqa: E402


def connect(args):
    return rpc.connect(port=args.port)


def print_json(obj):
    print(json.dumps(obj, indent=2, default=str))


def cmd_state(model, args):
    model.snapshot()
    print_json(model.summary())


def cmd_snapshot(model, args):
    state = model.snapshot()
    print_json({"at": state["at"], "viewscreen": state["status"].get("viewscreen"),
                "inventory": state["inventory"].get("counts", {})})


def cmd_actions(model, args):
    for name, (_, doc) in actions.ACTIONS.items():
        print(f"{name:12s} {doc}")
    print()
    for name, fn in tasks.TASKS.items():
        print(f"task: {name:12s} {fn.__doc__ or ''}")


def cmd_plan(model, args):
    fn = tasks.TASKS.get(args.task)
    if not fn:
        print(f"unknown task {args.task}; have: {', '.join(tasks.TASKS)}")
        return 1
    model.snapshot()
    result = fn(model, dry_run=True)
    print_json(result.to_dict())


def cmd_task(model, args):
    fn = tasks.TASKS.get(args.task)
    if not fn:
        print(f"unknown task {args.task}; have: {', '.join(tasks.TASKS)}")
        return 1
    model.snapshot()
    kwargs = {}
    if "wait" in fn.__code__.co_varnames:
        kwargs["wait"] = args.wait
    result = fn(model, dry_run=args.dry_run, **kwargs)
    print_json(result.to_dict())
    return 0 if result.ok else 2


def cmd_menu(model, args):
    menu = ui.read_menu(model.client)
    print_json({"options": menu.options()})
    if args.text:
        print_json(ui.choose(model.client, args.text, dry_run=args.dry_run))


def cmd_run(model, args):
    model.snapshot()
    ticks = 1 if args.once else args.ticks
    for i in range(ticks):
        out = daemon.tick(model, dry_run=args.dry_run, wait=args.wait)
        print_json({"tick": i + 1, "results": out})
        if not args.once and i < ticks - 1:
            time.sleep(args.interval)


def cmd_goal(model, args):
    if args.action == "add":
        gid = goals.add(model, args.name, args.expression, args.task,
                        priority=args.priority)
        print_json({"added": gid, "name": args.name, "expression": args.expression,
                    "task": args.task})
    elif args.action == "list":
        print_json({"goals": goals.all_goals(model, active_only=False)})
    elif args.action == "done":
        goals.set_status(model, args.name, "done")
        print_json({"done": args.name})
    elif args.action == "rm":
        goals.set_status(model, args.name, "removed")
        print_json({"removed": args.name})
    elif args.action == "check":
        for goal in goals.all_goals(model):
            try:
                print(goal["name"], "satisfied" if goals.satisfied(model, goal)
                      else "unsatisfied", "|", goal["expression"])
            except ValueError as exc:
                print(goal["name"], "BROKEN", exc)


def cmd_watch(model, args):
    ok, text = model.client.run_command("agent/watch")
    print_json({"started": ok, "detail": text.strip()})


def cmd_events(model, args):
    rows = model.db.execute(
        "SELECT at, kind, payload FROM journal WHERE kind LIKE 'event:%'"
        " ORDER BY id DESC LIMIT ?", (args.limit,)).fetchall()
    for at, kind, payload in rows:
        print(time.strftime("%H:%M:%S", time.localtime(at)), kind[6:], payload[:200])


def cmd_journal(model, args):
    rows = model.db.execute(
        "SELECT at, kind, payload FROM journal ORDER BY id DESC LIMIT ?",
        (args.limit,)).fetchall()
    for at, kind, payload in rows:
        print(time.strftime("%H:%M:%S", time.localtime(at)), kind, payload[:300])


def main(argv=None):
    parser = argparse.ArgumentParser(prog="dfkit", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=5001)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("state")
    sub.add_parser("snapshot")
    sub.add_parser("actions")
    p = sub.add_parser("plan"); p.add_argument("task")
    p = sub.add_parser("task")
    p.add_argument("task")
    p.add_argument("--wait", type=int, default=0)
    p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("menu"); p.add_argument("text", nargs="?")
    p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("run")
    p.add_argument("--once", action="store_true")
    p.add_argument("--ticks", type=int, default=60)
    p.add_argument("--interval", type=float, default=10.0)
    p.add_argument("--wait", type=int, default=0)
    p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("journal"); p.add_argument("limit", type=int, nargs="?", default=20)
    p = sub.add_parser("events"); p.add_argument("limit", type=int, nargs="?", default=20)
    sub.add_parser("watch")
    p = sub.add_parser("goal")
    p.add_argument("action", choices=["add", "list", "done", "rm", "check"])
    p.add_argument("name", nargs="?")
    p.add_argument("expression", nargs="?")
    p.add_argument("task", nargs="?")
    p.add_argument("--priority", type=int, default=5)

    args = parser.parse_args(argv)
    if args.command == "actions":
        cmd_actions(None, args)
        return 0
    try:
        client = connect(args)
    except OSError as exc:
        print(f"cannot reach DFHack RPC on 127.0.0.1:{args.port} ({exc})",
              file=sys.stderr)
        return 3
    model = WorldModel(client)
    handler = {
        "state": cmd_state, "snapshot": cmd_snapshot, "actions": cmd_actions,
        "plan": cmd_plan, "task": cmd_task, "menu": cmd_menu,
        "run": cmd_run, "journal": cmd_journal, "events": cmd_events,
        "watch": cmd_watch, "goal": cmd_goal,
    }[args.command]
    try:
        return handler(model, args) or 0
    finally:
        model.close()


if __name__ == "__main__":
    sys.exit(main())
