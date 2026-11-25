"""Event stream: incidents recorded by agent/watch.lua, drained by the daemon.

A byte offset is kept in the database so no event is handled twice and none is
lost between daemon runs.
"""
import json
import os

DF_EVENTS = os.environ.get(
    "DFKIT_EVENTS",
    os.path.expanduser("~/Games/df-0.47.05/df_linux/dfkit-events.jsonl"))


def drain(model):
    """Return new events since the last drain."""
    if not os.path.exists(DF_EVENTS):
        return []
    offset = int(model.meta_get("events_offset", "0"))
    size = os.path.getsize(DF_EVENTS)
    if size < offset:          # file was truncated; start over
        offset = 0
    events = []
    with open(DF_EVENTS, "r", encoding="utf-8", errors="replace") as fh:
        fh.seek(offset)
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except ValueError:
                continue
        offset = fh.tell()
    model.meta_set("events_offset", str(offset))
    for ev in events:
        model.db.execute(
            "INSERT INTO journal (at, kind, payload) VALUES (?, ?, ?)",
            (model.state.get("at", 0) or 0, "event:" + ev.get("kind", "?"),
             json.dumps(ev)))
    model.db.commit()
    return events


def summarize(events):
    """Collapse a batch into the few facts a policy actually needs."""
    out = {"deaths": [], "hostiles": [], "invasion": False,
           "alerts": [], "jobs_done": {}}
    for ev in events:
        kind = ev.get("kind")
        if kind == "unit_death":
            out["deaths"].append(ev)
        elif kind in ("hostile_spawn", "invasion"):
            out["hostiles"].append(ev)
            out["invasion"] = out["invasion"] or kind == "invasion"
        elif kind == "report":
            text = ev.get("text", "")
            if "cancels" in text:
                out["alerts"].append(text)
        elif kind == "job_completed":
            key = ev.get("job_type", "?")
            out["jobs_done"][key] = out["jobs_done"].get(key, 0) + 1
    return out
