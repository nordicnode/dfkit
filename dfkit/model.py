"""World model: typed snapshots of the fortress, persisted for agents.

Every read goes through the DFHack RPC and lands in one dict, so actions and
tasks share a single consistent view instead of re-querying ad hoc.
"""
import json
import os
import sqlite3
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_DB = os.path.join(ROOT, "world.db")

SHAPES = {
    "empty": 0, "floor": 1, "boulder": 2, "pebbles": 3, "wall": 4,
    "fortification": 5, "stair_up": 6, "stair_down": 7, "stair_updown": 8,
    "ramp": 9, "ramp_top": 10, "tree": 13, "sapling": 14, "shrub": 15,
}


class WorldModel:
    def __init__(self, client, db_path=DEFAULT_DB):
        self.client = client
        self.db_path = db_path
        self.state = {}
        self.db = None
        self._connect()

    def _connect(self):
        self.db = sqlite3.connect(self.db_path)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS snapshots ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL, status TEXT,"
            " buildings TEXT, jobs TEXT, inventory TEXT)")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS journal ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL, kind TEXT,"
            " payload TEXT)")
        self.db.commit()

    def meta_get(self, key, default=None):
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def meta_set(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                        (key, str(value)))
        self.db.commit()

    def close(self):
        if self.db:
            self.db.close()
            self.db = None

    # -- reads ----------------------------------------------------------
    def _call(self, script, *args):
        ok, text = self.client.run_command(script, *[str(a) for a in args])
        if not ok:
            raise RuntimeError(f"{script} failed: {text}")
        return json.loads(text) if text and text.strip() else {}

    def snapshot(self, with_inventory=True):
        status = self._call("agent/status")
        buildings = self._call("agent/buildings")
        jobs = self._call("agent/jobs", 200)
        inventory = self._call("agent/inventory") if with_inventory else {}
        reports = [r.text.strip() for r in self.client.reports()] if self.client else []
        self.state = {
            "at": time.time(),
            "status": status,
            "buildings": buildings,
            "jobs": jobs,
            "inventory": inventory,
            "reports": reports[-20:],
        }
        self.db.execute(
            "INSERT INTO snapshots (at, status, buildings, jobs, inventory)"
            " VALUES (?, ?, ?, ?, ?)",
            (self.state["at"], json.dumps(status), json.dumps(buildings),
             json.dumps(jobs), json.dumps(inventory)))
        self.db.commit()
        return self.state

    # -- convenience views ---------------------------------------------
    @property
    def status(self):
        return self.state.get("status", {})

    @property
    def buildings(self):
        return self.state.get("buildings", {})

    @property
    def inventory(self):
        return self.state.get("inventory", {})

    @property
    def jobs(self):
        return self.state.get("jobs", {})

    def workshop(self, kind):
        for entry in self.buildings.get("workshop_list", []):
            if entry["type"] == kind:
                return entry
        return None

    def workshop_ids(self, kind):
        return [e["id"] for e in self.buildings.get("workshop_list", [])
                if e["type"] == kind]

    def stockpiles(self):
        return self.buildings.get("stockpiles", [])

    def item_count(self, name):
        return self.inventory.get("counts", {}).get(name, 0)

    def has_plant_for_brew(self):
        return self.item_count("PLANT") > 0

    def ready(self):
        """Production preconditions that tasks check before acting."""
        return self._call("agent/ready")

    def recent_cancels(self, limit=6):
        return [r for r in self.state.get("reports", []) if "cancels" in r][-limit:]

    def summary(self):
        s = self.status
        return {
            "viewscreen": s.get("viewscreen"),
            "paused": s.get("paused"),
            "population": s.get("population"),
            "idlers": s.get("idlers"),
            "food": s.get("food"),
            "drink": s.get("drink"),
            "threats": s.get("threats"),
            "workshops": self.buildings.get("workshops", {}),
            "jobs": self.jobs.get("counts", {}),
            "stockpiles": len(self.stockpiles()),
            "manager": self.buildings.get("manager"),
            "cancels": self.recent_cancels(),
        }

    # -- spatial queries ------------------------------------------------
    def _tile_shapes(self, x0, x1, y0, y1, z):
        types = self.client.simple("GetTiletypeList").tiletype_list
        shape_of = {t.id: t.shape for t in types}
        self.client.simple("ResetMapHashes")
        blocks = {}
        for b in self.client.blocks(x0 // 16, x1 // 16 + 1, y0 // 16, y1 // 16 + 1,
                                     z, z + 1, blocks_needed=100000).map_blocks:
            blocks[(b.map_x // 16, b.map_y // 16, b.map_z)] = list(b.tiles)
        return blocks, shape_of

    def find_area(self, width, height, z=None, near=None, radius=40):
        """Find a free w*h rectangle of floor with no building on it."""
        status = self.status
        if z is None:
            z = near[2] if near else (status.get("year") and 178)
        anchor = near or self._citizen_anchor() or (96, 96, z)
        ax, ay = int(anchor[0]), int(anchor[1])
        x0, x1 = max(0, ax - radius), min(191, ax + radius)
        y0, y1 = max(0, ay - radius), min(191, ay + radius)
        blocks, shape = self._tile_shapes(x0, x1, y0, y1, z)
        occupied = set()
        for entry in self.buildings.get("workshop_list", []):
            cx, cy, _ = entry["pos"]
            for dx in range(-1, 2):
                for dy in range(-1, 2):
                    occupied.add((cx + dx, cy + dy))
        for sp in self.stockpiles():
            sx, sy, _ = sp["pos"]
            for dx in range(sp["width"]):
                for dy in range(sp["height"]):
                    occupied.add((sx + dx, sy + dy))

        def ok(x, y):
            tiles = blocks.get((x // 16, y // 16, z))
            if not tiles:
                return False
            t = tiles[(x % 16) * 16 + (y % 16)]
            return shape.get(t) == 1 and (x, y) not in occupied

        for y in range(y0, y1 - height + 1):
            for x in range(x0, x1 - width + 1):
                if all(ok(x + dx, y + dy) for dx in range(width) for dy in range(height)):
                    return (x, y, z)
        return None

    def _citizen_anchor(self):
        for c in self.status.get("citizens", []):
            return tuple(c["pos"])
        return None
