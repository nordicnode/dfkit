"""Composed tasks. A task is an ordered plan of actions with verification.

Each task explains itself (plan) and stops at the first failure, returning the
blocking reason instead of silently doing nothing.
"""
import time

from . import actions


class TaskResult:
    def __init__(self, name, ok, plan, steps=None, reason=""):
        self.name = name
        self.ok = ok
        self.plan = plan
        self.steps = steps or []
        self.reason = reason

    def to_dict(self):
        return {"task": self.name, "ok": self.ok, "plan": self.plan,
                "steps": self.steps, "reason": self.reason}


def _run(name, plan, dry_run):
    """plan: list of (label, callable). Stops at the first failed action."""
    if dry_run:
        return TaskResult(name, True, [label for label, _ in plan], [], "dry run")
    results = []
    for label, fn in plan:
        try:
            res = fn()
        except Exception as exc:  # noqa: BLE001 - report, do not crash the daemon
            results.append({"step": label, "ok": False, "detail": str(exc)})
            return TaskResult(name, False, [l for l, _ in plan], results, f"{label}: {exc}")
        entry = res.to_dict() if hasattr(res, "to_dict") else {"ok": True, "detail": str(res)}
        entry["step"] = label
        results.append(entry)
        if not entry.get("ok"):
            return TaskResult(name, False, [l for l, _ in plan], results,
                              f"{label}: {entry.get('detail')}")
    return TaskResult(name, True, [l for l, _ in plan], results, "")


# -- building blocks ----------------------------------------------------
def ensure_still(model, dry_run=False):
    plan = []
    if not model.workshop("still"):
        area = model.find_area(3, 3)
        if not area:
            return TaskResult("still", False, ["build still"], [],
                              "no free 3x3 floor area near the fort")
        plan.append((f"build still at {area}",
                     lambda a=area: actions.build(model, "still", a)))
    return _run("still", plan or [("still exists", lambda: actions.ActionResult(
        True, "still", "already built"))], dry_run)


def ensure_carpenter(model, dry_run=False):
    plan = []
    if not model.workshop("carpenter"):
        area = model.find_area(3, 3)
        if not area:
            return TaskResult("carpenter", False, ["build carpenter"], [],
                              "no free 3x3 floor area near the fort")
        plan.append((f"build carpenter at {area}",
                     lambda a=area: actions.build(model, "carpenter", a)))
    return _run("carpenter", plan or [("carpenter exists", lambda: actions.ActionResult(
        True, "carpenter", "already built"))], dry_run)


def ensure_kitchen(model, dry_run=False):
    plan = []
    if not model.workshop("kitchen"):
        area = model.find_area(3, 3)
        if not area:
            return TaskResult("kitchen", False, ["build kitchen"], [],
                              "no free 3x3 floor area near the fort")
        plan.append((f"build kitchen at {area}",
                     lambda a=area: actions.build(model, "kitchen", a)))
    return _run("kitchen", plan or [("kitchen exists", lambda: actions.ActionResult(
        True, "kitchen", "already built"))], dry_run)


# -- goals --------------------------------------------------------------
def task_brew(model, dry_run=False, wait=0):
    """Ensure a still and queue one brewing reaction."""
    steps = []
    still = model.workshop("still")
    if not still:
        area = model.find_area(3, 3)
        if not area:
            return TaskResult("brew", False, [], [], "no free space for a still")
        steps.append((f"build still at {area}",
                      lambda a=area: actions.build(model, "still", a)))
        still = None

    ready = model.ready()
    if not ready.get("brewable_plants"):
        return TaskResult(
            "brew", False, [s[0] for s in steps], [],
            "no unrotten DRINK_MAT-producing plants; grow them on a farm plot "
            "or use a Gather Plants designation")
    if not ready.get("empty_barrels"):
        return TaskResult(
            "brew", False, [s[0] for s in steps], [],
            "no empty barrel/pot; brewing needs an empty food storage item "
            "(craft a barrel at a carpenter, or a pot at a kiln)")

    def queue():
        current = model.workshop("still")
        if not current:
            return actions.ActionResult(False, "queue brew", "still disappeared")
        return actions.queue_job(model, current["id"], "CustomReaction",
                                 "BREW_DRINK_FROM_PLANT")

    before_ids = set(actions.drink_ids(model)) if not dry_run else set()
    steps.append(("queue brew at still", queue))
    result = _run("brew", steps, dry_run)
    if not result.ok or dry_run or not wait:
        return result
    # Verification: a new drink stack must exist (dwarves drink concurrently,
    # so the total can fall while a brew succeeds).
    deadline = time.time() + wait
    while time.time() < deadline:
        time.sleep(2)
        new_ids = set(actions.drink_ids(model)) - before_ids
        if new_ids:
            result.steps.append({"step": "verify brew", "ok": True,
                                 "detail": f"new drink stacks: {sorted(new_ids)[:4]}"})
            return result
    result.ok = False
    result.reason = "brew job queued but no new drink stack appeared in time"
    result.steps.append({"step": "verify brew", "ok": False,
                         "detail": "no new drink stack"})
    return result


def task_cook(model, dry_run=False):
    steps = []
    if not model.workshop("kitchen"):
        area = model.find_area(3, 3)
        if not area:
            return TaskResult("cook", False, [], [], "no free space for a kitchen")
        steps.append((f"build kitchen at {area}",
                      lambda a=area: actions.build(model, "kitchen", a)))

    def queue():
        kitchen = model.workshop("kitchen")
        if not kitchen:
            return actions.ActionResult(False, "queue cook", "no kitchen")
        return actions.queue_job(model, kitchen["id"], "PrepareMeal")

    steps.append(("queue PrepareMeal", queue))
    return _run("cook", steps, dry_run)


def task_gather(model, dry_run=False):
    """Top up the plant supply from wild shrubs, then brew if possible."""
    ready = model.ready()
    steps = []
    if ready.get("brewable_plants", 0) < 4:
        steps.append(("designate wild shrubs",
                      lambda: actions.gather(model, n=4)))
    return _run("gather", steps or [("plants available", lambda: actions.ActionResult(
        True, "gather", f"{ready.get('brewable_plants', 0)} brewable plants"))],
        dry_run)


def task_autolabor(model, dry_run=False):
    return _run("autolabor", [("enable DFHack autolabor",
                               lambda: actions.dfhack_command(model, "autolabor", 1))],
                dry_run)


def task_food_stockpile(model, dry_run=False, template=None):
    if model.stockpiles():
        return TaskResult("food_stockpile", True, [], [],
                          f"already have {len(model.stockpiles())} stockpile(s)")
    area = model.find_area(3, 3)
    if not area:
        return TaskResult("food_stockpile", False, [], [], "no free 3x3 floor area")
    return _run("food_stockpile", [
        (f"create food stockpile at {area}",
         lambda a=area: actions.stockpile(model, (a[0], a[1], a[2], a[0] + 2, a[1] + 2, a[2]),
                                          ["food"], template)),
    ], dry_run)


TASKS = {
    "still": ensure_still,
    "carpenter": ensure_carpenter,
    "kitchen": ensure_kitchen,
    "gather": task_gather,
    "brew": task_brew,
    "cook": task_cook,
    "autolabor": task_autolabor,
    "food_stockpile": task_food_stockpile,
}
