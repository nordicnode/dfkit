"""Semantic menu driver: turn a DF screen into options an agent can pick.

DF menus are just text with `key: Label` pairs. Parsing that removes the need
to hard-code key sequences for every screen.
"""
import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dfagent import screen_rows  # noqa: E402


class Menu:
    def __init__(self, rows):
        self.rows = rows

    def options(self):
        found = []
        for row in self.rows:
            # "b: Building" and "Brew drink from plant    (b)" are both menus.
            for cell in re.split(r"[█│|]", row):
                cell = cell.strip()
                if not cell:
                    continue
                m = re.match(r"^([A-Za-z0-9]{1,6}):\s+(.+)$", cell)
                if m:
                    key, label = m.group(1), m.group(2).strip()
                else:
                    m = re.match(r"^(.+?)\s*\(([A-Za-z0-9]{1,4})\)$", cell)
                    if not m:
                        m = re.match(r"^([A-Za-z0-9]):\s*(.+)$", cell)
                    if not m:
                        continue
                    label, key = m.group(2).strip(), m.group(1)
                if label.isdigit() or len(label) < 2:
                    continue
                entry = {"key": key, "label": label}
                if entry not in found:
                    found.append(entry)
        return found

    def find(self, text):
        text = text.lower()
        for entry in self.options():
            if text in entry["label"].lower():
                return entry
        return None

    def text(self):
        return "\n".join(self.rows)


def read_menu(client):
    return Menu(screen_rows(client.screen()))


def press(client, *keys):
    syms = []
    from dfagent import KEYS
    for key in keys:
        if key not in KEYS:
            raise ValueError(f"unknown key {key!r}")
        syms.append(KEYS[key])
    client.send_keys(syms)


def choose(client, text, dry_run=False):
    menu = read_menu(client)
    entry = menu.find(text)
    if not entry:
        return {"ok": False, "error": f"no menu option matching {text!r}",
                "options": menu.options()[:20]}
    if not dry_run:
        press(client, entry["key"] if len(entry["key"]) == 1 else entry["key"])
    return {"ok": True, "chosen": entry}
