"""Compliance engine: turns stored obligations + employee documents into dated, scored items."""
import json
from collections import defaultdict
from datetime import date

from db import add_months, as_of

SOON_WEIGHT = 0.35          # a due-soon item counts as 35% of an overdue one in the score
EMP_SHARE = 0.4             # employee documents carry 40% of the score so they cannot drown licences/filings
HORIZON_DAYS = 30           # "exposure next 30 days"


def _status(days_left: int, lead_days: int) -> str:
    if days_left < 0:
        return "overdue"
    if days_left <= lead_days:
        return "soon"
    return "ok"


def _tpl(row) -> dict:
    return dict(
        code=row["code"], title=row["title"], authority=row["authority"], category=row["category"],
        severity=row["severity"], penalty_sar=row["penalty_sar"], penalty_note=row["penalty_note"],
        fix_steps=json.loads(row["fix_steps"]), evidence=row["evidence"], vip_code=row["vip_code"],
        source_url=row["source_url"], verified=bool(row["verified"]), lead_days=row["lead_days"],
        recurrence_months=row["recurrence_months"], scope=row["scope"])


def load_items(c, org_id: int, branch_id: int | None = None) -> list[dict]:
    today = as_of()
    tpl = {r["code"]: _tpl(r) for r in c.execute("SELECT * FROM template")}
    vip = {r["code"]: r["name"] for r in c.execute("SELECT code,name FROM vip_service")}
    branches = {r["id"]: r["name"] for r in c.execute("SELECT id,name FROM branch WHERE org_id=?", (org_id,))}
    items: list[dict] = []

    q = "SELECT * FROM instance WHERE org_id=?" + (" AND branch_id=?" if branch_id else "") + " ORDER BY id"
    for r in c.execute(q, (org_id, branch_id) if branch_id else (org_id,)):
        t = tpl[r["template_code"]]
        left = (date.fromisoformat(r["due_date"]) - today).days
        items.append(dict(
            id=f"o-{r['id']}", kind="obligation", branch_id=r["branch_id"], branch_name=branches[r["branch_id"]],
            due_date=r["due_date"], last_done=r["last_done"], days_left=left, status=_status(left, t["lead_days"]),
            evidence_note=r["evidence_note"], vip_name=vip.get(t["vip_code"]), employee=None, **_public(t)))

    q = ("SELECT d.id, d.template_code, d.expiry, e.id AS eid, e.name, e.role, e.branch_id FROM emp_doc d "
         "JOIN employee e ON e.id=d.employee_id WHERE d.org_id=?" + (" AND e.branch_id=?" if branch_id else "") + " ORDER BY d.id")
    for r in c.execute(q, (org_id, branch_id) if branch_id else (org_id,)):
        t = tpl[r["template_code"]]
        left = (date.fromisoformat(r["expiry"]) - today).days
        items.append(dict(
            id=f"e-{r['id']}", kind="employee_doc", branch_id=r["branch_id"], branch_name=branches[r["branch_id"]],
            due_date=r["expiry"], last_done=None, days_left=left, status=_status(left, t["lead_days"]),
            evidence_note="", vip_name=vip.get(t["vip_code"]),
            employee=dict(id=r["eid"], name=r["name"], role=r["role"]), **_public(t)))
    return items


def _public(t: dict) -> dict:
    return dict(code=t["code"], title=t["title"], authority=t["authority"], category=t["category"],
                severity=t["severity"], penalty_sar=t["penalty_sar"], penalty_note=t["penalty_note"],
                fix_steps=t["fix_steps"], evidence=t["evidence"], vip_code=t["vip_code"],
                source_url=t["source_url"], verified=t["verified"], lead_days=t["lead_days"],
                recurrence_months=t["recurrence_months"])


def _loss(items: list[dict]) -> tuple[float, float]:
    total = sum(i["severity"] for i in items)
    loss = sum(i["severity"] * (1.0 if i["status"] == "overdue" else SOON_WEIGHT if i["status"] == "soon" else 0.0) for i in items)
    return loss, total


def score(items: list[dict]) -> int:
    obl = [i for i in items if i["kind"] == "obligation"]
    emp = [i for i in items if i["kind"] == "employee_doc"]
    parts = []
    for group, share in ((obl, 1 - EMP_SHARE), (emp, EMP_SHARE)):
        if group:
            loss, total = _loss(group)
            parts.append((100 * (1 - loss / total), share))
    if not parts:
        return 100
    w = sum(s for _, s in parts)
    return round(sum(v * s for v, s in parts) / w)


def band(s: int) -> str:
    return "good" if s >= 85 else "watch" if s >= 65 else "risk"


def money_at_risk(items: list[dict]) -> int:
    return sum(i["penalty_sar"] for i in items if i["status"] == "overdue")


def exposure_30(items: list[dict]) -> int:
    return sum(i["penalty_sar"] for i in items if 0 <= i["days_left"] <= HORIZON_DAYS)


def counts(items: list[dict]) -> dict:
    return dict(overdue=sum(i["status"] == "overdue" for i in items),
                soon=sum(i["status"] == "soon" for i in items),
                ok=sum(i["status"] == "ok" for i in items), total=len(items))


def priority(i: dict):
    return ({"overdue": 0, "soon": 1, "ok": 2}[i["status"]], -i["severity"], i["days_left"])


def urgent(items: list[dict], limit: int = 10) -> list[dict]:
    """Obligations individually; employee documents grouped per branch + document type."""
    out: list[dict] = []
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for i in items:
        if i["status"] == "ok":
            continue
        if i["kind"] == "obligation":
            out.append(i)
        else:
            groups[(i["branch_id"], i["code"], i["status"])].append(i)
    for (_, _, _), g in groups.items():
        first = min(g, key=lambda x: x["days_left"])
        out.append(dict(first, id=f"g-{first['branch_id']}-{first['code']}-{first['status']}", kind="group",
                        count=len(g), employee=None, penalty_sar=sum(x["penalty_sar"] for x in g),
                        days_left=first["days_left"]))
    out.sort(key=priority)
    return out[:limit]


def by_authority(items: list[dict]) -> list[dict]:
    agg: dict[str, dict] = {}
    for i in items:
        a = agg.setdefault(i["authority"], dict(authority=i["authority"], overdue=0, soon=0, ok=0))
        a[i["status"]] += 1
    rows = list(agg.values())
    rows.sort(key=lambda r: (-r["overdue"], -r["soon"], r["authority"]))
    return rows


def next_due(old_due: date, done: date, recurrence_months: int) -> date:
    base = old_due if done <= old_due else done
    return add_months(base, recurrence_months)
