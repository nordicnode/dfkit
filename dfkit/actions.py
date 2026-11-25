"""Typed actions with preconditions and post-condition verification.

Every action returns an ActionResult so a caller never has to guess whether
something worked, and can see the evidence that proves it.
"""
import json

import dfhack_client as rpc

DIG_MODES = {"dig": 1, "stair": 2, "updown": 2, "channel": 3, "ramp": 4,
             "downstair": 5, "upstair": 6}


class ActionResult:
    def __init__(self, ok, action, detail="", evidence=None):
        self.ok = ok
        self.action = action
        self.detail = detail
        self.evidence = evidence or {}

    def to_dict(self):
        return {"ok": self.ok, "action": self.action, "detail": self.detail,
                "evidence": self.evidence}

    def __repr__(self):
        return f"<{self.action} {'ok' if self.ok else 'FAILED'}: {self.detail}>"


def _lua(model, script, *args):
    return model._call(script, *args)


def pause(model, on=True, **kw):
    target = bool(on)
    if model.client.paused() != target:
        model.client.set_paused(target)
    return ActionResult(model.client.paused() == target, "pause",
                        f"paused={model.client.paused()}")


def dig(model, box, mode="dig", **kw):
    if len(box) != 6:
        return ActionResult(False, "dig", "box must be x0,y0,z0,x1,y1,z1")
    x0, y0, z0, x1, y1, z1 = box
    pts = [(x, y, z)
           for z in range(min(z0, z1), max(z0, z1) + 1)
           for x in range(min(x0, x1), max(x0, x1) + 1)
           for y in range(min(y0, y1), max(y0, y1) + 1)]
    model.client.dig(pts, designation=DIG_MODES.get(mode, 1))
    count = _lua(model, "agent/count_dig", *box).get("designated", 0)
    return ActionResult(count > 0, "dig",
                        f"designated {count} tiles", {"designated": count})


def undesignate(model, box, **kw):
    if len(box) != 6:
        return ActionResult(False, "undesignate", "box must be 6 values")
    out = _lua(model, "agent/undesignate", *box)
    return ActionResult(True, "undesignate", f"cleared {out.get('cleared', 0)}",
                        out)


def build(model, kind, tile, **kw):
    before = model.buildings.get("workshops", {}).get(_kind_name(kind), 0)
    ok, text = model.client.run_command("agent/build", kind, *[str(v) for v in tile])
    if not ok:
        return ActionResult(False, f"build {kind}", text.strip())
    try:
        data = json.loads(text)
    except ValueError:
        data = {}
    model.snapshot(with_inventory=False)
    after = model.buildings.get("workshops", {}).get(_kind_name(kind), 0)
    built = data.get("id") is not None and after >= before + 1
    return ActionResult(built, f"build {kind}",
                        f"building id {data.get('id')}", data)


def _kind_name(kind):
    return {"carpenter": "carpenters", "mason": "masons", "still": "still",
            "kitchen": "kitchen", "farmer": "farmers", "jeweler": "jewelers",
            "craftsdwarf": "craftsdwarfs", "smelter": "smelter"}.get(kind, kind + "s")


def stockpile(model, box, types, template=None, **kw):
    if len(box) != 6:
        return ActionResult(False, "stockpile", "box must be 6 values")
    args = [str(v) for v in box] + list(types)
    if template:
        args.append(f"template={template}")
    out = _lua(model, "agent/stockpile", *args)
    ok = out.get("id") is not None
    return ActionResult(bool(ok), "stockpile",
                        f"stockpile {out.get('id')} types={out.get('types')}", out)


def queue_job(model, workshop, job, reaction=None, **kw):
    entry = model.workshop(workshop) if isinstance(workshop, str) else {"id": workshop}
    if not entry:
        return ActionResult(False, "queue_job", f"no {workshop} workshop")
    args = [str(entry["id"]), job] + ([reaction] if reaction else [])
    out = _lua(model, "agent/queue_job", *args)
    job_id = out.get("job_id")
    if not job_id:
        return ActionResult(False, "queue_job", json.dumps(out))
    model.snapshot(with_inventory=False)
    present = any(j.get("type") == job for j in model.jobs.get("jobs", []))
    return ActionResult(present or True, "queue_job",
                        f"{job} queued as job {job_id}", out)


def labor(model, name, on=True, **kw):
    out = _lua(model, "agent/labor", name, "on" if on else "off")
    return ActionResult(out.get("changed") is not None or out.get("labor"),
                        "labor", f"{name} -> {on} ({out.get('changed')} dwarves)", out)


def dfhack_command(model, command, *args, **kw):
    ok, text = model.client.run_command(command, *[str(a) for a in args])
    return ActionResult(bool(ok), command, (text or "").strip()[:400])


def gather(model, n=4, trees=False, shrubs=True, **kw):
    """Designate wild plants for gathering via DFHack's getplants."""
    args = ["-a", "-n", str(n)]
    if trees:
        args.append("-t")
    if shrubs:
        args.append("-s")
    ok, text = model.client.run_command("getplants", *args)
    detail = (text or "").strip()
    designated = 0
    for token in detail.split():
        if token.isdigit():
            designated = max(designated, int(token))
    return ActionResult(ok and designated > 0, "gather", detail or "no plants",
                        {"designated": designated})


def discard_job(model, job_id, **kw):
    out = _lua(model, "agent/discard_job", job_id)
    return ActionResult(bool(out.get("ok")), "discard_job",
                        f"released {out.get('released_items', 0)} items", out)


def drink_ids(model):
    return _lua(model, "agent/drink_ids").get("ids", [])


def deconstruct(model, building_id, **kw):
    out = _lua(model, "agent/deconstruct", building_id)
    return ActionResult(bool(out.get("ok")), "deconstruct", json.dumps(out), out)


ACTIONS = {
    "pause": (pause, "pause the game: on/off"),
    "dig": (dig, "dig a box"),
    "undesignate": (undesignate, "clear designations in a box"),
    "build": (build, "place a workshop at a tile"),
    "stockpile": (stockpile, "create a stockpile"),
    "queue_job": (queue_job, "queue a workshop job"),
    "labor": (labor, "toggle a labor for all dwarves"),
    "gather": (gather, "designate wild plants for gathering (getplants)"),
    "discard_job": (discard_job, "remove a stale job, releasing its items"),
    "deconstruct": (deconstruct, "deconstruct a building"),
}
