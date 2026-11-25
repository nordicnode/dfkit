"""Daemon tick: one pass of observation, decisions and actions.

The daemon never invents actions: it chooses from the task registry, records
every step in the journal, and stops when a precondition is missing.
"""
import json
import time

from . import actions
from . import events as event_stream
from . import goals as goal_store
from . import tasks


def record(model, kind, payload):
    model.db.execute("INSERT INTO journal (at, kind, payload) VALUES (?, ?, ?)",
                     (time.time(), kind, json.dumps(payload)))
    model.db.commit()


def tick(model, dry_run=False, wait=0):
    """Run one policy pass: drain events, handle threats, advance a goal."""
    model.snapshot()
    out = []

    fresh = event_stream.drain(model)
    if fresh:
        summary = event_stream.summarize(fresh)
        record(model, "events", summary)
        if summary["invasion"] or summary["hostiles"]:
            res = actions.pause(model, True)
            out.append({"events": summary, "paused": res.to_dict()})
            return out
        if summary["alerts"]:
            out.append({"events": summary})

    status = model.status

    if goal_store.all_goals(model):
        results = goal_store.plan(model, dry_run=dry_run, wait=wait)
        for result in results:
            record(model, "task", result)
        return out + results

    if status.get("threats", 0) > 0 and not status.get("paused"):
        res = actions.pause(model, True)
        out.append(res.to_dict())
        record(model, "threat", {"threats": status.get("threats"),
                                 "list": status.get("threat_list", [])})
        return out

    if status.get("population", 0) == 0:
        return out

    goals = []
    if status.get("drink", 0) < 20 and model.has_plant_for_brew():
        goals.append(("brew", lambda: tasks.task_brew(model, dry_run, wait=wait)))
    if status.get("food", 0) < 15:
        goals.append(("cook", lambda: tasks.task_cook(model, dry_run)))
    if (status.get("jobs", 0) > 0 and status.get("dwarves", 0) > 0
            and status.get("idlers", 0) >= max(2, int(status["dwarves"] * 0.7))):
        goals.append(("autolabor", lambda: tasks.task_autolabor(model, dry_run)))

    for name, fn in goals:
        try:
            result = fn()
        except Exception as exc:  # noqa: BLE001
            record(model, "error", {"task": name, "error": str(exc)})
            out.append({"task": name, "ok": False, "reason": str(exc)})
            continue
        payload = result.to_dict()
        out.append(payload)
        record(model, "task", payload)
    return out
