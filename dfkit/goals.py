"""Goals and the planner.

A goal is a persistent condition ("drink >= 60") plus the task that advances
it. The planner is deliberately simple: pick the highest-priority unsatisfied
goal, run its task, record what happened. Simple enough to audit, enough to
play the game unattended.
"""
import time

from . import tasks

# Names exposed to goal expressions.
GOAL_VARS = (
    "drink", "food", "population", "dwarves", "idlers", "threats",
    "brewable_plants", "empty_barrels", "plants", "stockpiles",
)


def ensure_tables(model):
    model.db.execute(
        "CREATE TABLE IF NOT EXISTS goals ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, expression TEXT,"
        " task TEXT, priority INTEGER DEFAULT 5, status TEXT DEFAULT 'active',"
        " created REAL, last_at REAL, last_error TEXT)")
    model.db.execute(
        "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
    model.db.commit()


def add(model, name, expression, task, priority=5):
    ensure_tables(model)
    if task not in tasks.TASKS:
        raise ValueError(f"unknown task {task!r}; have {', '.join(tasks.TASKS)}")
    model.db.execute(
        "INSERT INTO goals (name, expression, task, priority, created)"
        " VALUES (?, ?, ?, ?, ?)", (name, expression, task, priority, time.time()))
    model.db.commit()
    return model.db.execute("SELECT last_insert_rowid()").fetchone()[0]


def all_goals(model, active_only=True):
    ensure_tables(model)
    sql = "SELECT id, name, expression, task, priority, status, last_at, last_error FROM goals"
    if active_only:
        sql += " WHERE status = 'active'"
    sql += " ORDER BY priority DESC, id ASC"
    return [dict(zip(("id", "name", "expression", "task", "priority", "status",
                      "last_at", "last_error"), row)) for row in model.db.execute(sql)]


def set_status(model, goal_id, status, error=None):
    ensure_tables(model)
    model.db.execute("UPDATE goals SET status=?, last_error=? WHERE id=?",
                     (status, error, goal_id))
    model.db.commit()


def variables(model):
    summary = model.summary()
    ready = model.ready()
    inv = {k.lower(): v for k, v in model.inventory.get("counts", {}).items()}
    out = {k: summary.get(k) for k in GOAL_VARS}
    out.update(ready)
    out.update(inv)
    out["stockpiles"] = len(model.stockpiles())
    return out


def satisfied(model, goal):
    """Evaluate a goal expression. Unknown names are an error the agent sees."""
    vars_ = variables(model)
    try:
        return bool(eval(goal["expression"], {"__builtins__": {}}, vars_))
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"goal {goal['name']!r} expression {goal['expression']!r}: {exc}")


def plan(model, dry_run=False, cooldown=20, wait=0):
    """Advance the highest-priority unsatisfied goal. Returns task results."""
    results = []
    for goal in all_goals(model):
        try:
            done = satisfied(model, goal)
        except ValueError as exc:
            results.append({"goal": goal["name"], "ok": False, "reason": str(exc)})
            set_status(model, goal["id"], "broken", str(exc))
            continue
        if done:
            continue
        # Blocked goals back off harder than successful ones, otherwise one
        # impossible goal starves every other goal forever.
        backoff = 180 if goal["last_error"] else cooldown
        if goal["last_at"] and time.time() - goal["last_at"] < backoff:
            continue
        fn = tasks.TASKS[goal["task"]]
        kwargs = {}
        if "wait" in fn.__code__.co_varnames:
            kwargs["wait"] = wait
        try:
            result = fn(model, dry_run=dry_run, **kwargs).to_dict()
        except Exception as exc:  # noqa: BLE001
            result = {"task": goal["task"], "ok": False, "reason": str(exc)}
        result["goal"] = {"id": goal["id"], "name": goal["name"],
                          "expression": goal["expression"]}
        results.append(result)
        model.db.execute(
            "UPDATE goals SET last_at=?, last_error=? WHERE id=?",
            (time.time(), None if result.get("ok") else result.get("reason"),
             goal["id"]))
        model.db.commit()
        if not dry_run:
            break  # one goal per tick: the world changed, re-plan next tick
    return results
