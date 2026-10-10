import json
import re
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

import admin
import alerts
import db
import engine
import importer
import staff

@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init()
    yield


app = FastAPI(title="امتثال API", version="0.2", lifespan=lifespan)
app.include_router(admin.router)
STATIC = Path(__file__).parent / "static"


def _log(c, org_id: int, action: str, detail: str, amount: int = 0) -> None:
    c.execute("INSERT INTO audit(org_id,ts,action,detail,amount) VALUES(?,?,?,?,?)",
              (org_id, datetime.now(timezone.utc).isoformat(timespec="seconds"), action, detail, amount))


def _org(c, org_id: int):
    o = c.execute("SELECT * FROM org WHERE id=?", (org_id,)).fetchone()
    if not o:
        raise HTTPException(404, "المنشأة غير موجودة")
    return o


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health():
    return dict(ok=True, as_of=db.as_of().isoformat())


@app.get("/api/orgs")
def orgs():
    c = db.conn()
    rows = [dict(r) for r in c.execute("SELECT * FROM org ORDER BY id")]
    c.close()
    return dict(as_of=db.as_of().isoformat(), orgs=rows)


@app.get("/api/orgs/{org_id}/overview")
def overview(org_id: int):
    c = db.conn()
    org = _org(c, org_id)
    items = engine.load_items(c, org_id)
    branches = []
    for b in c.execute("SELECT * FROM branch WHERE org_id=? ORDER BY id", (org_id,)):
        bi = [i for i in items if i["branch_id"] == b["id"]]
        s = engine.score(bi)
        top = engine.urgent(bi, 3)
        branches.append(dict(
            id=b["id"], name=b["name"], city=b["city"], headcount=b["headcount"], score=s, band=engine.band(s),
            counts=engine.counts(bi), money_at_risk=engine.money_at_risk(bi),
            top_issues=[dict(title=(f"{t['count']} × {t['title']}" if t["kind"] == "group" else t["title"]),
                             status=t["status"], days_left=t["days_left"]) for t in top]))
    s = engine.score(items)
    out = dict(
        org=dict(org), as_of=db.as_of().isoformat(), score=s, band=engine.band(s), counts=engine.counts(items),
        money_at_risk=engine.money_at_risk(items), exposure_30=engine.exposure_30(items),
        branches=branches, urgent=engine.urgent(items, 10), by_authority=engine.by_authority(items))
    c.close()
    return out


@app.get("/api/branches/{branch_id}/items")
def branch_items(branch_id: int, status: str | None = None, kind: str | None = None):
    c = db.conn()
    b = c.execute("SELECT * FROM branch WHERE id=?", (branch_id,)).fetchone()
    if not b:
        raise HTTPException(404, "الفرع غير موجود")
    items = engine.load_items(c, b["org_id"], branch_id)
    c.close()
    if status:
        items = [i for i in items if i["status"] == status]
    if kind:
        items = [i for i in items if i["kind"] == kind]
    items.sort(key=engine.priority)
    s = engine.score([i for i in engine.load_items(db.conn(), b["org_id"], branch_id)])
    return dict(branch=dict(b), score=s, band=engine.band(s), items=items)


@app.get("/api/orgs/{org_id}/employee-docs")
def employee_docs(org_id: int, branch_id: int | None = None, status: str | None = None, code: str | None = None):
    c = db.conn()
    _org(c, org_id)
    items = [i for i in engine.load_items(c, org_id, branch_id) if i["kind"] == "employee_doc"]
    c.close()
    if status:
        items = [i for i in items if i["status"] == status]
    if code:
        items = [i for i in items if i["code"] == code]
    items.sort(key=engine.priority)
    return dict(total=len(items), items=items[:300])


class Complete(BaseModel):
    done_date: str | None = None
    new_expiry: str | None = None
    note: str = ""


@app.post("/api/items/{item_id}/complete")
def complete(item_id: str, body: Complete):
    kind, _, raw = item_id.partition("-")
    if kind not in ("o", "e") or not raw.isdigit():
        raise HTTPException(400, "معرّف غير صالح")
    c = db.conn()
    today = db.as_of()
    if kind == "o":
        r = c.execute("SELECT i.*, t.recurrence_months, t.title, t.lead_days, t.penalty_sar FROM instance i JOIN template t ON t.code=i.template_code WHERE i.id=?", (raw,)).fetchone()
        if not r:
            raise HTTPException(404, "البند غير موجود")
        done = date.fromisoformat(body.done_date) if body.done_date else today
        new_due = engine.next_due(date.fromisoformat(r["due_date"]), done, r["recurrence_months"])
        c.execute("UPDATE instance SET due_date=?, last_done=?, evidence_note=? WHERE id=?",
                  (new_due.isoformat(), done.isoformat(), body.note, raw))
        removed = r["penalty_sar"] if engine._status((date.fromisoformat(r["due_date"]) - today).days, r["lead_days"]) != "ok" else 0
        _log(c, r["org_id"], "complete", f"{r['title']} — الاستحقاق التالي {new_due.isoformat()}", removed)
        result = dict(next_due=new_due.isoformat())
    else:
        r = c.execute("SELECT d.*, t.recurrence_months, t.title, t.lead_days, t.penalty_sar, e.name FROM emp_doc d JOIN template t ON t.code=d.template_code "
                      "JOIN employee e ON e.id=d.employee_id WHERE d.id=?", (raw,)).fetchone()
        if not r:
            raise HTTPException(404, "الوثيقة غير موجودة")
        new_exp = date.fromisoformat(body.new_expiry) if body.new_expiry else db.add_months(today, r["recurrence_months"])
        c.execute("UPDATE emp_doc SET expiry=? WHERE id=?", (new_exp.isoformat(), raw))
        removed = r["penalty_sar"] if engine._status((date.fromisoformat(r["expiry"]) - today).days, r["lead_days"]) != "ok" else 0
        _log(c, r["org_id"], "renew", f"{r['title']} — {r['name']} — ينتهي {new_exp.isoformat()}", removed)
        result = dict(next_due=new_exp.isoformat())
    c.commit()
    c.close()
    return dict(ok=True, **result)


@app.get("/api/orgs/{org_id}/changes")
def changes(org_id: int):
    c = db.conn()
    _org(c, org_id)
    items = engine.load_items(c, org_id)
    pack_of = {r["id"]: r["pack"] for r in c.execute("SELECT id,pack FROM branch WHERE org_id=?", (org_id,))}
    acked = {r["change_id"]: r["ts"] for r in c.execute("SELECT * FROM change_ack WHERE org_id=?", (org_id,))}
    today = db.as_of()
    out = []
    for ch in c.execute("SELECT * FROM change WHERE status='published' ORDER BY effective DESC"):
        affects = json.loads(ch["affects"])
        ch_packs = json.loads(ch["packs"])
        hit = [i for i in items if i["code"] in affects and pack_of[i["branch_id"]] in ch_packs]
        if not hit:
            continue
        per_branch: dict[int, dict] = {}
        for i in hit:
            b = per_branch.setdefault(i["branch_id"], dict(branch_id=i["branch_id"], branch_name=i["branch_name"], items=0, attention=0))
            b["items"] += 1
            b["attention"] += i["status"] != "ok"
        eff = date.fromisoformat(ch["effective"])
        out.append(dict(
            id=ch["id"], title=ch["title"], authority=ch["authority"], published=ch["published"], effective=ch["effective"],
            days_to_effective=(eff - today).days, summary=ch["summary"], action_required=ch["action_required"],
            affects=affects, source_url=ch["source_url"], source_quality=ch["source_quality"], is_demo=bool(ch["is_demo"]),
            provenance=ch["provenance"], reviewed=bool(ch["reviewed_by"]),
            acknowledged_at=acked.get(ch["id"]), impact=sorted(per_branch.values(), key=lambda b: -b["attention"])))
    c.close()
    return dict(changes=out)


@app.post("/api/orgs/{org_id}/changes/{change_id}/acknowledge")
def acknowledge(org_id: int, change_id: int):
    c = db.conn()
    _org(c, org_id)
    ch = c.execute("SELECT title FROM change WHERE id=?", (change_id,)).fetchone()
    if not ch:
        raise HTTPException(404, "التحديث غير موجود")
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    c.execute("INSERT OR REPLACE INTO change_ack(org_id,change_id,ts) VALUES(?,?,?)", (org_id, change_id, ts))
    _log(c, org_id, "ack_change", ch["title"])
    c.commit()
    c.close()
    return dict(ok=True, acknowledged_at=ts)


@app.get("/api/orgs/{org_id}/vip")
def vip(org_id: int):
    c = db.conn()
    org = _org(c, org_id)
    catalog = []
    for v in c.execute("SELECT * FROM vip_service ORDER BY price_from DESC"):
        if org["pack"] in json.loads(v["packs"]):
            catalog.append(dict(v, packs=json.loads(v["packs"])))
    reqs = [dict(r) for r in c.execute(
        "SELECT r.*, s.name AS service_name, b.name AS branch_name FROM vip_request r "
        "JOIN vip_service s ON s.code=r.service_code LEFT JOIN branch b ON b.id=r.branch_id "
        "WHERE r.org_id=? ORDER BY r.id DESC", (org_id,))]
    c.close()
    return dict(catalog=catalog, requests=reqs)


class VipReq(BaseModel):
    branch_id: int | None = None
    service_code: str
    item_ref: str = ""
    note: str = ""


@app.post("/api/orgs/{org_id}/vip/requests")
def vip_request(org_id: int, body: VipReq):
    c = db.conn()
    _org(c, org_id)
    s = c.execute("SELECT name FROM vip_service WHERE code=?", (body.service_code,)).fetchone()
    if not s:
        raise HTTPException(404, "الخدمة غير موجودة")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rid = c.execute("INSERT INTO vip_request(org_id,branch_id,service_code,item_ref,note,status,created_at,updated_at) VALUES(?,?,?,?,?,'new',?,?)",
                    (org_id, body.branch_id, body.service_code, body.item_ref, body.note, now, now)).lastrowid
    _log(c, org_id, "vip_request", s["name"])
    c.commit()
    c.close()
    return dict(ok=True, id=rid)


@app.post("/api/vip/requests/{req_id}/advance")
def vip_advance(req_id: int):
    """Demo helper standing in for the ops console: new -> in_progress -> done."""
    c = db.conn()
    r = c.execute("SELECT * FROM vip_request WHERE id=?", (req_id,)).fetchone()
    if not r:
        raise HTTPException(404, "الطلب غير موجود")
    nxt = {"new": "in_progress", "in_progress": "done"}.get(r["status"], r["status"])
    if nxt != r["status"]:
        c.execute("UPDATE vip_request SET status=?, updated_at=? WHERE id=?",
                  (nxt, datetime.now(timezone.utc).isoformat(timespec="seconds"), req_id))
        _log(c, r["org_id"], "vip_status", f"طلب #{req_id} → {nxt}")
        c.commit()
    c.close()
    return dict(ok=True, status=nxt)


@app.get("/api/orgs/{org_id}/audit")
def audit(org_id: int):
    c = db.conn()
    rows = [dict(r) for r in c.execute("SELECT * FROM audit WHERE org_id=? ORDER BY id DESC LIMIT 50", (org_id,))]
    c.close()
    return dict(entries=rows)


@app.get("/api/orgs/{org_id}/alerts")
def org_alerts(org_id: int):
    c = db.conn()
    org = _org(c, org_id)
    branches = [dict(r) for r in c.execute("SELECT * FROM branch WHERE org_id=? ORDER BY id", (org_id,))]
    items = engine.load_items(c, org_id)
    c.close()
    return alerts.build(dict(org), branches, items)


@app.get("/api/orgs/{org_id}/score-explain")
def score_explain(org_id: int, branch_id: int | None = None):
    """Why the readiness score is what it is, and what would move it (whole organisation, or one branch)."""
    c = db.conn()
    _org(c, org_id)
    items = engine.load_items(c, org_id, branch_id)
    c.close()
    return engine.explain_score(items)


class Remind(BaseModel):
    item_id: str


@app.post("/api/orgs/{org_id}/remind")
def remind(org_id: int, body: Remind):
    """Prepares the reminder the item's owner would receive (the text is returned so the customer can send it from their own
    WhatsApp today; automatic sending needs a messaging provider) and records that it was prepared."""
    c = db.conn()
    _org(c, org_id)
    if not re.fullmatch(r"(o|e)-\d+|g-\d+-.+-(overdue|soon|ok)", body.item_id):
        c.close()
        raise HTTPException(400, "معرّف غير صالح")
    items = engine.load_items(c, org_id)
    pool = items + [g for g, _ in engine._grouped(items)]
    hit = next((i for i in pool if i["id"] == body.item_id), None)
    if not hit:
        c.close()
        raise HTTPException(404, "البند غير موجود")
    owner = hit["owner"]
    _log(c, org_id, "remind", f"{hit['title']} → {owner['name']}")
    c.commit()
    c.close()
    return dict(ok=True, to=dict(name=owner["name"], role=owner["role"]), text=alerts.message_text(hit))


@app.get("/api/orgs/{org_id}/owner")
def owner_summary(org_id: int):
    """One page for whoever holds the budget: the number, the worst branch, the three things to do, what has been fixed since
    the organisation started using the product, and the score history (one point per day the page is opened)."""
    c = db.conn()
    org = _org(c, org_id)
    items = engine.load_items(c, org_id)
    branches = [dict(r) for r in c.execute("SELECT * FROM branch WHERE org_id=? ORDER BY id", (org_id,))]
    today = db.as_of().isoformat()
    s, money = engine.score(items), engine.money_at_risk(items)
    c.execute("INSERT INTO score_history(org_id,day,score,money) VALUES(?,?,?,?) ON CONFLICT(org_id,day) DO UPDATE SET score=excluded.score, money=excluded.money",
              (org_id, today, s, money))
    c.commit()
    history = [dict(r) for r in c.execute("SELECT day,score,money FROM (SELECT day,score,money FROM score_history WHERE org_id=? ORDER BY day DESC LIMIT 60) ORDER BY day", (org_id,))]
    wins = c.execute("SELECT COUNT(*) AS n, COALESCE(SUM(amount),0) AS removed FROM audit WHERE org_id=? AND action IN ('complete','renew')", (org_id,)).fetchone()
    vip_done = c.execute("SELECT COUNT(*) FROM vip_request WHERE org_id=? AND status='done'", (org_id,)).fetchone()[0]
    scored = [(b["name"], engine.score([i for i in items if i["branch_id"] == b["id"]]),
               engine.money_at_risk([i for i in items if i["branch_id"] == b["id"]])) for b in branches]
    worst = None
    for name, bs, bm in scored:
        if worst is None or bs < worst["score"]:
            worst = dict(name=name, score=bs, money=bm)
    al = alerts.build(dict(org), branches, items)
    c.close()
    return dict(org=dict(id=org["id"], name=org["name"]), as_of=today, score=s, band=engine.band(s), money_at_risk=money,
                exposure_30=engine.exposure_30(items), counts=engine.counts(items), worst_branch=worst,
                actions=[dict(id=i["id"], title=i["title"], kind=i["kind"], count=i.get("count", 1), branch_name=i["branch_name"],
                              status=i["status"], days_left=i["days_left"], penalty_sar=i["penalty_sar"]) for i in engine.urgent(items, 3)],
                wins=dict(fixed=wins["n"], exposure_removed=wins["removed"], vip_done=vip_done), history=history, digest=al["digest"])


class ImportRow(BaseModel):
    branch: str = ""
    city: str = ""
    employee: str = ""
    role: str = ""
    document: str = ""
    date: str = ""
    emp_id: str = ""


class ImportReq(BaseModel):
    org_name: str = ""
    pack: str = ""
    rows: list[ImportRow] = []


@app.get("/api/import/doc-types")
def import_doc_types():
    c = db.conn()
    out = importer.doc_types(c)
    c.close()
    return out


@app.get("/import-parse.js")
def import_parse_js():
    return FileResponse(STATIC / "import-parse.js", media_type="application/javascript")


@app.post("/api/import")
def import_org(body: ImportReq):
    c = db.conn()
    try:
        res = importer.run(c, body.model_dump())
        if res["org_id"]:
            n = sum(res["imported"].values())
            _log(c, res["org_id"], "import", f"استيراد بيانات: {res['imported']['employee_docs']} وثيقة موظف و{res['imported']['obligations']} التزام")
        c.commit()
    except importer.ImportError_ as e:
        c.close()
        raise HTTPException(422, e.detail)
    c.close()
    return res


@app.get("/api/orgs/{org_id}/staff")
def org_staff(org_id: int):
    c = db.conn()
    _org(c, org_id)
    out = staff.roster(c, org_id)
    c.close()
    return dict(staff=out)


class Assign(BaseModel):
    item_id: str
    owner_id: str
    due: str | None = None


@app.post("/api/orgs/{org_id}/assign")
def assign(org_id: int, body: Assign):
    c = db.conn()
    _org(c, org_id)
    key = staff.normalize_key(body.item_id)
    if not key:
        c.close()
        raise HTTPException(400, "معرّف غير صالح")
    people = {p["id"]: p for p in staff.roster(c, org_id)}
    if body.owner_id not in people:
        c.close()
        raise HTTPException(404, "المسؤول غير موجود")
    if body.due:
        try:
            if date.fromisoformat(body.due).isoformat() != body.due:
                raise ValueError
        except ValueError:
            c.close()
            raise HTTPException(422, "التاريخ يجب أن يكون بصيغة YYYY-MM-DD")
    items = [i for i in engine.load_items(c, org_id) if staff.item_key(i) == key]
    if not items:
        c.close()
        raise HTTPException(404, "البند غير موجود")
    c.execute("INSERT INTO assignment(org_id,key,owner_id,due) VALUES(?,?,?,?) ON CONFLICT(org_id,key) DO UPDATE SET owner_id=excluded.owner_id, due=excluded.due",
              (org_id, key, body.owner_id, body.due or None))
    _log(c, org_id, "assign", f"{items[0]['title']} ← {people[body.owner_id]['name']}")
    c.commit()
    c.close()
    return dict(ok=True, owner=dict(id=body.owner_id, name=people[body.owner_id]["name"], role=people[body.owner_id]["role"]))
