"""Compliance engine: turns stored obligations + employee documents into dated, scored items."""
import json
from collections import defaultdict
from datetime import date

import staff
from db import add_months, as_of
from library import CONSEQUENCES, DOMAIN_OVERRIDE

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
        source_url=row["source_url"], verified=bool(row["verified"]), verified_by=row["verified_by"],
        verified_on=row["verified_on"], lead_days=row["lead_days"],
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
    staff.decorate(c, org_id, items)
    return items


def _public(t: dict) -> dict:
    return dict(code=t["code"], title=t["title"], authority=t["authority"], category=t["category"],
                domain=DOMAIN_OVERRIDE.get(t["code"], t["category"]), consequence=CONSEQUENCES.get(t["code"], ""),
                severity=t["severity"], penalty_sar=t["penalty_sar"], penalty_note=t["penalty_note"],
                fix_steps=t["fix_steps"], evidence=t["evidence"], vip_code=t["vip_code"],
                source_url=t["source_url"], verified=t["verified"], verified_by=t["verified_by"],
                verified_on=t["verified_on"], lead_days=t["lead_days"],
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


def _grouped(items: list[dict]) -> list[tuple[dict, list[dict]]]:
    """Non-ok items as (display item, member items): obligations alone, employee documents per branch + document + status."""
    out: list[tuple[dict, list[dict]]] = []
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for i in items:
        if i["status"] == "ok":
            continue
        if i["kind"] == "obligation":
            out.append((i, [i]))
        else:
            groups[(i["branch_id"], i["code"], i["status"])].append(i)
    for g in groups.values():
        first = min(g, key=lambda x: x["days_left"])
        out.append((dict(first, id=f"g-{first['branch_id']}-{first['code']}-{first['status']}", kind="group", count=len(g),
                         employee=None, penalty_sar=sum(x["penalty_sar"] for x in g), days_left=first["days_left"]), g))
    return out


def _as_ok(items: list[dict], ids: set[str] | None) -> list[dict]:
    return [dict(i, status="ok") if (ids is None or i["id"] in ids) and i["status"] != "ok" else i for i in items]


def explain_score(items: list[dict], limit: int = 6) -> dict:
    """Why the score is what it is: the two weighted parts, the items that cost the most points (each driver's points are
    its exact share of the deduction, so they add up to 100 - score before rounding) and what fixing them would do."""
    groups = [(g, share, label, kind) for g, share, label, kind in (
        ([i for i in items if i["kind"] == "obligation"], 1 - EMP_SHARE, "التزامات وتراخيص", "obligation"),
        ([i for i in items if i["kind"] == "employee_doc"], EMP_SHARE, "وثائق الموظفين", "employee_doc")) if g]
    w = sum(s for _, s, _, _ in groups)
    parts, totals = [], {}
    for g, share, label, kind in groups:
        loss, total = _loss(g)
        totals[kind] = (total, share / w)
        parts.append(dict(label=label, kind=kind, weight=round(100 * share / w), score=round(100 * (1 - loss / total)),
                          count=len(g), overdue=sum(i["status"] == "overdue" for i in g), soon=sum(i["status"] == "soon" for i in g)))
    drivers = []
    for shown, members in _grouped(items):
        total, nshare = totals[members[0]["kind"]]
        pts = sum(nshare * 100 * (m["severity"] * (1.0 if m["status"] == "overdue" else SOON_WEIGHT)) / total for m in members)
        drivers.append((pts, shown, members))
    drivers.sort(key=lambda d: (-d[0], priority(d[1])))
    s = score(items)
    top = drivers[:limit]
    top3_ids = {m["id"] for _, _, ms in drivers[:3] for m in ms}
    return dict(
        score=s, band=band(s), soon_weight=SOON_WEIGHT, parts=parts,
        drivers=[dict(id=d["id"], kind=d["kind"], title=d["title"], count=d.get("count", 1), branch_id=d["branch_id"],
                      branch_name=d["branch_name"], status=d["status"], days_left=d["days_left"], penalty_sar=d["penalty_sar"],
                      vip_code=d["vip_code"], points=round(p * 10) / 10) for p, d, _ in top],
        other_points=round(sum(p for p, _, _ in drivers[limit:]) * 10) / 10,
        scenarios=dict(fix_top3=score(_as_ok(items, top3_ids)), fix_overdue=score([dict(i, status="ok") if i["status"] == "overdue" else i for i in items])))


def next_due(old_due: date, done: date, recurrence_months: int) -> date:
    base = old_due if done <= old_due else done
    return add_months(base, recurrence_months)
