"""Who is responsible: a derived roster per organisation plus explicit assignments of items to people.

Roster (identical to the browser port in static/demo-api.js): the general manager, the HR manager and one manager per
branch. Default owner: branch obligations -> that branch's manager; employee documents -> the HR manager.
Assignments are keyed per organisation by item key: 'o-<id>' for obligations, 'g-<branch>-<code>' for employee documents.
"""
import re
from datetime import date

from library import DEMO_STAFF


def roster(c, org_id: int) -> list[dict]:
    org = c.execute("SELECT name FROM org WHERE id=?", (org_id,)).fetchone()
    named = DEMO_STAFF.get(org["name"]) if org else None
    out = [dict(id="gm", name=named["gm"] if named else "المدير العام", role="المدير العام / المالك", branch_id=None),
           dict(id="hr", name=named["hr"] if named else "مسؤول الموارد البشرية", role="مدير الموارد البشرية", branch_id=None)]
    for k, b in enumerate(c.execute("SELECT id,name FROM branch WHERE org_id=? ORDER BY id", (org_id,))):
        nm = named["branches"][k] if named and k < len(named["branches"]) else f"مدير {b['name']}"
        out.append(dict(id=f"b{b['id']}", name=nm, role=f"مدير {b['name']}" if named else "مدير الفرع", branch_id=b["id"]))
    return out


def item_key(item: dict) -> str:
    return item["id"] if item["kind"] == "obligation" else f"g-{item['branch_id']}-{item['code']}"


def decorate(c, org_id: int, items: list[dict]) -> None:
    people = {p["id"]: p for p in roster(c, org_id)}
    given = {r["key"]: r for r in c.execute("SELECT key, owner_id, due FROM assignment WHERE org_id=?", (org_id,))}
    for i in items:
        a = given.get(item_key(i))
        oid = a["owner_id"] if a and a["owner_id"] in people else ("hr" if i["kind"] == "employee_doc" else f"b{i['branch_id']}")
        p = people.get(oid) or people["hr"]
        i["owner"] = dict(id=p["id"], name=p["name"], role=p["role"])
        i["internal_due"] = a["due"] if a else None
        i["assigned"] = bool(a)


_KEY = re.compile(r"^(o-\d+|g-\d+-.+?)(?:-(?:overdue|soon|ok))?$")


def normalize_key(item_id: str) -> str | None:
    """'o-12' stays; 'g-1-EMP-IQAMA-overdue' -> 'g-1-EMP-IQAMA'; anything else is invalid."""
    if re.fullmatch(r"o-\d+", item_id):
        return item_id
    m = re.fullmatch(r"(g-\d+-.+?)(?:-(?:overdue|soon|ok))?", item_id)
    return m.group(1) if m and m.group(1).startswith("g-") else None
