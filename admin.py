"""Analyst console API (v2): ingest a source -> AI/rules draft -> human review -> publish.

The gate is enforced here, server-side: drafts and rejected items are never returned by the
customer endpoints (see main.changes), and publish() refuses unless a named reviewer has confirmed
the draft against the source and every required field is filled in.
"""
import hmac
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

import db
import engine
import llm

router = APIRouter()
STATIC = Path(__file__).parent / "static"


def require_admin(x_admin_token: str = Header(default="")) -> None:
    expected = os.environ.get("IMTITHAL_ADMIN_TOKEN", "demo-admin")  # demo default; set a real one in production
    if not hmac.compare_digest(x_admin_token.encode(), expected.encode()):
        raise HTTPException(401, "رمز المحلل غير صحيح")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _log(c, action: str, detail: str) -> None:
    c.execute("INSERT INTO audit(org_id,ts,action,detail) VALUES(0,?,?,?)", (_now(), action, detail))


def _catalog(c) -> list[dict]:
    return [dict(code=r["code"], title=r["title"], authority=r["authority"], scope=r["scope"], packs=json.loads(r["packs"]))
            for r in c.execute("SELECT code,title,authority,scope,packs FROM template ORDER BY code")]


def _ser(r, full: bool = False) -> dict:
    d = dict(
        id=r["id"], title=r["title"], authority=r["authority"], published=r["published"], effective=r["effective"],
        summary=r["summary"], action_required=r["action_required"], affects=json.loads(r["affects"] or "[]"),
        packs=json.loads(r["packs"] or "[]"), source_url=r["source_url"], status=r["status"], provenance=r["provenance"],
        ai_provider=r["ai_provider"], ai_confidence=r["ai_confidence"], ai_notes=json.loads(r["ai_notes"] or "[]"),
        evidence=json.loads(r["evidence"] or "[]"), created_at=r["created_at"], reviewed_by=r["reviewed_by"],
        reviewed_at=r["reviewed_at"], reject_reason=r["reject_reason"], is_demo=bool(r["is_demo"]))
    if full:
        d["source_text"] = r["source_text"] or ""
    return d


def _get(c, change_id: int):
    r = c.execute("SELECT * FROM change WHERE id=?", (change_id,)).fetchone()
    if not r:
        raise HTTPException(404, "التحديث غير موجود")
    return r


@router.get("/admin")
def admin_page():
    return FileResponse(STATIC / "admin.html")


@router.get("/api/admin/catalog", dependencies=[Depends(require_admin)])
def catalog():
    c = db.conn()
    out = dict(catalog=_catalog(c), packs=list(llm.PACKS), provider=llm.pick_provider())
    c.close()
    return out


@router.get("/api/admin/changes", dependencies=[Depends(require_admin)])
def list_changes(status: str | None = None):
    c = db.conn()
    q = "SELECT * FROM change" + (" WHERE status=?" if status else "") + " ORDER BY id DESC"
    rows = [_ser(r) for r in c.execute(q, (status,) if status else ())]
    c.close()
    return dict(changes=rows)


@router.get("/api/admin/changes/{change_id}", dependencies=[Depends(require_admin)])
def get_change(change_id: int):
    c = db.conn()
    r = _ser(_get(c, change_id), full=True)
    c.close()
    return r


class DraftIn(BaseModel):
    text: str = ""
    url: str = ""
    label: str = ""


@router.post("/api/admin/changes/draft", dependencies=[Depends(require_admin)])
def make_draft(body: DraftIn):
    text, url = body.text.strip(), body.url.strip()
    if not text and not url:
        raise HTTPException(400, "الصق نص المصدر أو أدخل رابطًا حكوميًا")
    if url:
        try:
            llm.check_source_url(url)
            if not text:
                text = llm.fetch_source(url)
        except llm.SourceError as e:
            raise HTTPException(422, str(e))
    c = db.conn()
    try:
        res = llm.draft_change(text, _catalog(c), body.label or url)
    except ValueError as e:
        c.close()
        raise HTTPException(400, str(e))
    dup = c.execute("SELECT id FROM change WHERE source_hash=? AND status!='rejected'", (res["source_hash"],)).fetchone()
    if dup:
        c.close()
        raise HTTPException(409, f"هذا المصدر موجود مسبقًا في التحديث رقم {dup['id']}")
    d = res["draft"]
    cur = c.execute(
        "INSERT INTO change(title,authority,published,effective,summary,action_required,affects,source_url,source_quality,is_demo,packs,"
        "status,provenance,ai_provider,ai_confidence,ai_notes,evidence,source_hash,source_text,created_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,0,?,'draft',?,?,?,?,?,?,?,?)",
        (d["title"] or body.label or "(بدون عنوان)", d["authority"], d["published"], d["effective"], d["summary"],
         d["action_required"], json.dumps(d["affects"]), url, "رسمي" if url else "نص ملصوق", json.dumps(d["packs"]),
         "ai" if res["provider"] == "anthropic" else "rules", res["provider"], d["confidence"],
         json.dumps(res["notes"] + d["uncertainties"], ensure_ascii=False), json.dumps(d["evidence_quotes"], ensure_ascii=False),
         res["source_hash"], text[:30000], _now()))
    _log(c, "change_draft", f"مسودة #{cur.lastrowid} ({res['provider']})")
    c.commit()
    out = _ser(_get(c, cur.lastrowid), full=True)
    c.close()
    return out


class ChangePatch(BaseModel):
    title: str | None = None
    authority: str | None = None
    published: str | None = None
    effective: str | None = None
    summary: str | None = None
    action_required: str | None = None
    affects: list[str] | None = None
    packs: list[str] | None = None


@router.patch("/api/admin/changes/{change_id}", dependencies=[Depends(require_admin)])
def edit_change(change_id: int, body: ChangePatch):
    c = db.conn()
    r = _get(c, change_id)
    if r["status"] != "draft":
        c.close()
        raise HTTPException(409, "يمكن تعديل المسودات فقط — أعد المنشور إلى مسودة أولًا")
    known = {x["code"] for x in _catalog(c)}
    upd: dict = {}
    for f, n in (("title", 160), ("authority", 120), ("summary", 600), ("action_required", 600)):
        v = getattr(body, f)
        if v is not None:
            upd[f] = " ".join(v.split())[:n]
    for f in ("published", "effective"):
        v = getattr(body, f)
        if v is not None:
            if v and not llm._clean_date(v):
                c.close()
                raise HTTPException(422, "التاريخ يجب أن يكون بصيغة YYYY-MM-DD")
            upd[f] = v
    if body.affects is not None:
        bad = [x for x in body.affects if x not in known]
        if bad:
            c.close()
            raise HTTPException(422, "رموز غير معروفة: " + "، ".join(bad))
        upd["affects"] = json.dumps(list(dict.fromkeys(body.affects)))
    if body.packs is not None:
        if any(p not in llm.PACKS for p in body.packs):
            c.close()
            raise HTTPException(422, "قطاع غير معروف")
        upd["packs"] = json.dumps(list(dict.fromkeys(body.packs)))
    if upd:
        c.execute("UPDATE change SET " + ",".join(f"{k}=?" for k in upd) + " WHERE id=?", (*upd.values(), change_id))
        _log(c, "change_edit", f"تعديل مسودة #{change_id}: " + "، ".join(upd))
        c.commit()
    out = _ser(_get(c, change_id), full=True)
    c.close()
    return out


@router.get("/api/admin/changes/{change_id}/impact", dependencies=[Depends(require_admin)])
def impact(change_id: int):
    """Blast radius: which customers' branches would see this change if it were published as it stands."""
    c = db.conn()
    r = _get(c, change_id)
    affects, packs = set(json.loads(r["affects"] or "[]")), set(json.loads(r["packs"] or "[]"))
    orgs, total_branches, total_items = [], 0, 0
    for o in c.execute("SELECT * FROM org ORDER BY id"):
        pack_of = {b["id"]: b["pack"] for b in c.execute("SELECT id,pack FROM branch WHERE org_id=?", (o["id"],))}
        per: dict[int, dict] = {}
        for i in engine.load_items(c, o["id"]):
            if i["code"] in affects and pack_of[i["branch_id"]] in packs:
                b = per.setdefault(i["branch_id"], dict(branch_id=i["branch_id"], branch_name=i["branch_name"], items=0, attention=0))
                b["items"] += 1
                b["attention"] += i["status"] != "ok"
        if per:
            orgs.append(dict(org_id=o["id"], org_name=o["name"], branches=list(per.values())))
            total_branches += len(per)
            total_items += sum(b["items"] for b in per.values())
    c.close()
    return dict(orgs=orgs, total_branches=total_branches, total_items=total_items)


class PublishIn(BaseModel):
    reviewer: str = ""
    confirmed_against_source: bool = False


@router.post("/api/admin/changes/{change_id}/publish", dependencies=[Depends(require_admin)])
def publish(change_id: int, body: PublishIn):
    c = db.conn()
    r = _get(c, change_id)
    problems = []
    if r["status"] != "draft":
        problems.append("الحالة الحالية لا تسمح بالنشر")
    if len(body.reviewer.strip()) < 2:
        problems.append("اسم المراجع مطلوب")
    if not body.confirmed_against_source:
        problems.append("يجب تأكيد مطابقة المسودة للمصدر الأصلي")
    for f, label in (("title", "العنوان"), ("authority", "الجهة"), ("summary", "الملخص"), ("action_required", "الإجراء المطلوب")):
        if not (r[f] or "").strip():
            problems.append(f"{label} مطلوب")
    if not llm._clean_date(r["effective"]):
        problems.append("تاريخ السريان مطلوب")
    if not json.loads(r["affects"] or "[]"):
        problems.append("اختر التزامًا واحدًا على الأقل متأثرًا")
    if not json.loads(r["packs"] or "[]"):
        problems.append("اختر قطاعًا واحدًا على الأقل")
    if not (r["source_url"] or r["source_text"]):
        problems.append("لا يوجد مصدر مرفق")
    if problems:
        c.close()
        raise HTTPException(422, "تعذر النشر: " + "؛ ".join(problems))
    c.execute("UPDATE change SET status='published', reviewed_by=?, reviewed_at=?, published=? WHERE id=?",
              (body.reviewer.strip(), _now(), r["published"] or date.today().isoformat(), change_id))
    _log(c, "change_publish", f"نُشر التحديث #{change_id} بواسطة {body.reviewer.strip()} ({r['provenance']})")
    c.commit()
    out = _ser(_get(c, change_id))
    c.close()
    return out


class RejectIn(BaseModel):
    reason: str = ""


@router.post("/api/admin/changes/{change_id}/reject", dependencies=[Depends(require_admin)])
def reject(change_id: int, body: RejectIn):
    c = db.conn()
    r = _get(c, change_id)
    if r["status"] != "draft":
        c.close()
        raise HTTPException(409, "يمكن رفض المسودات فقط")
    c.execute("UPDATE change SET status='rejected', reject_reason=? WHERE id=?", (body.reason.strip()[:300], change_id))
    _log(c, "change_reject", f"رُفضت المسودة #{change_id}")
    c.commit()
    c.close()
    return dict(ok=True)


@router.post("/api/admin/changes/{change_id}/unpublish", dependencies=[Depends(require_admin)])
def unpublish(change_id: int):
    """Pull a published change back to draft so it disappears from customers while it is corrected."""
    c = db.conn()
    r = _get(c, change_id)
    if r["status"] != "published":
        c.close()
        raise HTTPException(409, "التحديث غير منشور")
    c.execute("UPDATE change SET status='draft', reviewed_by=NULL, reviewed_at=NULL WHERE id=?", (change_id,))
    _log(c, "change_unpublish", f"أُعيد التحديث #{change_id} إلى مسودة")
    c.commit()
    c.close()
    return dict(ok=True)
