import json
from datetime import date, datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

import db
import engine

app = FastAPI(title="امتثال API", version="0.1")
STATIC = Path(__file__).parent / "static"


@app.on_event("startup")
def _startup() -> None:
    db.init()


def _log(c, org_id: int, action: str, detail: str) -> None:
    c.execute("INSERT INTO audit(org_id,ts,action,detail) VALUES(?,?,?,?)",
              (org_id, datetime.now(timezone.utc).isoformat(timespec="seconds"), action, detail))


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
        r = c.execute("SELECT i.*, t.recurrence_months, t.title FROM instance i JOIN template t ON t.code=i.template_code WHERE i.id=?", (raw,)).fetchone()
        if not r:
            raise HTTPException(404, "البند غير موجود")
        done = date.fromisoformat(body.done_date) if body.done_date else today
        new_due = engine.next_due(date.fromisoformat(r["due_date"]), done, r["recurrence_months"])
        c.execute("UPDATE instance SET due_date=?, last_done=?, evidence_note=? WHERE id=?",
                  (new_due.isoformat(), done.isoformat(), body.note, raw))
        _log(c, r["org_id"], "complete", f"{r['title']} — الاستحقاق التالي {new_due.isoformat()}")
        result = dict(next_due=new_due.isoformat())
    else:
        r = c.execute("SELECT d.*, t.recurrence_months, t.title, e.name FROM emp_doc d JOIN template t ON t.code=d.template_code "
                      "JOIN employee e ON e.id=d.employee_id WHERE d.id=?", (raw,)).fetchone()
        if not r:
            raise HTTPException(404, "الوثيقة غير موجودة")
        new_exp = date.fromisoformat(body.new_expiry) if body.new_expiry else db.add_months(today, r["recurrence_months"])
        c.execute("UPDATE emp_doc SET expiry=? WHERE id=?", (new_exp.isoformat(), raw))
        _log(c, r["org_id"], "renew", f"{r['title']} — {r['name']} — ينتهي {new_exp.isoformat()}")
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
    for ch in c.execute("SELECT * FROM change ORDER BY effective DESC"):
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
