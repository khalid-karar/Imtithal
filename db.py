import json
import os
import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from library import CHANGES, TEMPLATES, VIP_SERVICES

DB_PATH = Path(os.environ.get("IMTITHAL_DB", Path(__file__).parent / "imtithal.db"))


def as_of() -> date:
    v = os.environ.get("AS_OF")
    return date.fromisoformat(v) if v else date.today()


def conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c


SCHEMA = """
CREATE TABLE IF NOT EXISTS org(id INTEGER PRIMARY KEY, name TEXT, pack TEXT, city TEXT);
CREATE TABLE IF NOT EXISTS branch(id INTEGER PRIMARY KEY, org_id INTEGER, name TEXT, city TEXT, pack TEXT, headcount INTEGER);
CREATE TABLE IF NOT EXISTS template(
  code TEXT PRIMARY KEY, title TEXT, authority TEXT, category TEXT, scope TEXT, packs TEXT,
  min_headcount INTEGER DEFAULT 0, recurrence_months INTEGER, lead_days INTEGER, severity INTEGER,
  penalty_sar INTEGER, penalty_note TEXT, fix_steps TEXT, evidence TEXT, vip_code TEXT,
  source_url TEXT, verified INTEGER DEFAULT 0, verified_by TEXT, verified_on TEXT);
CREATE TABLE IF NOT EXISTS instance(
  id INTEGER PRIMARY KEY, org_id INTEGER, branch_id INTEGER, template_code TEXT,
  due_date TEXT, last_done TEXT, evidence_note TEXT);
CREATE TABLE IF NOT EXISTS employee(id INTEGER PRIMARY KEY, org_id INTEGER, branch_id INTEGER, name TEXT, role TEXT, is_saudi INTEGER);
CREATE TABLE IF NOT EXISTS emp_doc(id INTEGER PRIMARY KEY, org_id INTEGER, employee_id INTEGER, template_code TEXT, expiry TEXT);
CREATE TABLE IF NOT EXISTS change(
  id INTEGER PRIMARY KEY, title TEXT, authority TEXT, published TEXT, effective TEXT, summary TEXT,
  action_required TEXT, affects TEXT, source_url TEXT, source_quality TEXT, is_demo INTEGER, packs TEXT,
  status TEXT DEFAULT 'published', provenance TEXT DEFAULT 'manual', ai_provider TEXT, ai_confidence REAL,
  ai_notes TEXT DEFAULT '[]', evidence TEXT DEFAULT '[]', source_hash TEXT, source_text TEXT,
  created_at TEXT, reviewed_by TEXT, reviewed_at TEXT, reject_reason TEXT);
CREATE TABLE IF NOT EXISTS change_ack(org_id INTEGER, change_id INTEGER, ts TEXT, PRIMARY KEY(org_id, change_id));
CREATE TABLE IF NOT EXISTS vip_service(
  code TEXT PRIMARY KEY, name TEXT, description TEXT, price_from INTEGER, price_unit TEXT, sla_days INTEGER, packs TEXT);
CREATE TABLE IF NOT EXISTS vip_request(
  id INTEGER PRIMARY KEY, org_id INTEGER, branch_id INTEGER, service_code TEXT, item_ref TEXT, note TEXT,
  status TEXT, created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, org_id INTEGER, ts TEXT, action TEXT, detail TEXT);
CREATE INDEX IF NOT EXISTS ix_inst_branch ON instance(branch_id);
CREATE INDEX IF NOT EXISTS ix_doc_emp ON emp_doc(employee_id);
CREATE INDEX IF NOT EXISTS ix_emp_branch ON employee(branch_id);
"""

FIRST = ["أحمد", "محمد", "خالد", "سعد", "فهد", "عبدالله", "ناصر", "يوسف", "إبراهيم", "طارق",
         "سارة", "نورة", "ريم", "هند", "منى", "ليلى", "عمر", "علي", "حسن", "بدر", "ماجد", "وليد"]
LAST = ["العتيبي", "الدوسري", "القحطاني", "الحربي", "الشمري", "الزهراني", "الغامدي", "السبيعي",
        "الخان", "حسين", "رحمن", "إسلام", "كومار", "سانتوس", "رضا", "الشريف", "المطيري", "العنزي"]

ROLES = {
    "hotel": ["موظف استقبال", "مشرف تدبير منزلي", "عامل تدبير منزلي", "طاهٍ", "مساعد طاهٍ", "نادل", "فني صيانة", "أمن", "محاسب"],
    "hospital": ["ممرض", "طبيب", "فني مختبر", "صيدلي", "مساعد تمريض", "موظف استقبال", "فني أشعة", "إداري", "عامل نظافة"],
    "company": ["مهندس", "مشرف موقع", "فني", "عامل", "محاسب", "سائق", "إداري", "مساعد إداري"],
}
CLINICAL = {"ممرض", "طبيب", "فني مختبر", "صيدلي", "فني أشعة"}

DEMO = [
    dict(name="مجموعة الواحة للفنادق", pack="hotel", city="الرياض", branches=[
        ("فندق الواحة — الرياض", "الرياض", 30), ("فندق الواحة — جدة", "جدة", 24), ("فندق الواحة — الدمام", "الدمام", 18)]),
    dict(name="مستشفى الرعاية التخصصي", pack="hospital", city="الرياض", branches=[
        ("المستشفى الرئيسي", "الرياض", 34), ("مركز الرعاية — جدة", "جدة", 20)]),
    dict(name="شركة الأفق للمقاولات", pack="company", city="الرياض", branches=[
        ("المقر الرئيسي", "الرياض", 26), ("فرع الجبيل", "الجبيل", 20), ("فرع تبوك", "تبوك", 14)]),
]

# Narrative anchors so the demo tells a story: (branch name, template code) -> days until due
FORCED = {
    ("فندق الواحة — جدة", "LIC-CD"): -4,
    ("فندق الواحة — جدة", "HR-NITAQAT"): 3,
    ("فندق الواحة — الرياض", "HR-WORKERDATA"): 6,
    ("فندق الواحة — الدمام", "HR-WPS"): -2,
    ("المستشفى الرئيسي", "LIC-WASTE"): -9,
    ("مركز الرعاية — جدة", "LIC-MOH"): 12,
    ("فرع تبوك", "TAX-VAT"): -6,
    ("فرع الجبيل", "LIC-BALADY"): 9,
}


def add_months(d: date, months: int) -> date:
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    last = [31, 29 if y % 4 == 0 and (y % 100 != 0 or y % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    return date(y, m, min(d.day, last))


def _offset(rng: random.Random, lead: int, rec_months: int) -> int:
    r = rng.random()
    if r < 0.10:
        return -rng.randint(1, 40)
    if r < 0.26:
        return rng.randint(0, max(lead, 1))
    return rng.randint(lead + 1, max(lead + 30, rec_months * 30))


def init(reset: bool = False) -> None:
    if reset and DB_PATH.exists():
        DB_PATH.unlink()
    c = conn()
    c.executescript(SCHEMA)
    _migrate(c)
    if c.execute("SELECT COUNT(*) FROM org").fetchone()[0]:
        c.close()
        return
    today = as_of()

    for t in TEMPLATES:
        c.execute(
            "INSERT INTO template(code,title,authority,category,scope,packs,min_headcount,recurrence_months,lead_days,severity,"
            "penalty_sar,penalty_note,fix_steps,evidence,vip_code,source_url,verified) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)",
            (t["code"], t["title"], t["authority"], t["category"], t["scope"], json.dumps(t["packs"]), t.get("min_headcount", 0),
             t["recurrence_months"], t["lead_days"], t["severity"], t["penalty_sar"], t["penalty_note"],
             json.dumps(t["fix_steps"], ensure_ascii=False), t["evidence"], t["vip_code"], t["source_url"]))
    for ch in CHANGES:
        c.execute("INSERT INTO change(id,title,authority,published,effective,summary,action_required,affects,source_url,"
                  "source_quality,is_demo,packs,status,provenance) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,'published','manual')",
                  (ch["id"], ch["title"], ch["authority"], ch["published"], ch["effective"], ch["summary"],
                   ch["action_required"], json.dumps(ch["affects"]), ch["source_url"], ch["source_quality"], ch["is_demo"], json.dumps(ch["packs"])))
    for v in VIP_SERVICES:
        c.execute("INSERT INTO vip_service VALUES(?,?,?,?,?,?,?)",
                  (v["code"], v["name"], v["description"], v["price_from"], v["price_unit"], v["sla_days"], json.dumps(v["packs"])))

    templates = {t["code"]: t for t in TEMPLATES}
    for o in DEMO:
        oid = c.execute("INSERT INTO org(name,pack,city) VALUES(?,?,?)", (o["name"], o["pack"], o["city"])).lastrowid
        for bname, bcity, n_emp in o["branches"]:
            bid = c.execute("INSERT INTO branch(org_id,name,city,pack,headcount) VALUES(?,?,?,?,?)",
                            (oid, bname, bcity, o["pack"], n_emp)).lastrowid
            rng = random.Random(bid * 7919)
            for code, t in templates.items():
                if t["scope"] != "branch" or not _applies(t, o["pack"], n_emp):
                    continue
                off = FORCED.get((bname, code), _offset(rng, t["lead_days"], t["recurrence_months"]))
                due = today + timedelta(days=off)
                last = add_months(due, -t["recurrence_months"])
                c.execute("INSERT INTO instance(org_id,branch_id,template_code,due_date,last_done,evidence_note) VALUES(?,?,?,?,?,'')",
                          (oid, bid, code, due.isoformat(), last.isoformat()))
            for _ in range(n_emp):
                role = rng.choice(ROLES[o["pack"]])
                saudi = 1 if rng.random() < 0.35 else 0
                name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
                eid = c.execute("INSERT INTO employee(org_id,branch_id,name,role,is_saudi) VALUES(?,?,?,?,?)",
                                (oid, bid, name, role, saudi)).lastrowid
                codes = ["EMP-INS", "EMP-CONTRACT"] if saudi else ["EMP-IQAMA", "EMP-WP", "EMP-INS", "EMP-CONTRACT"]
                if o["pack"] in ("hotel", "hospital") and role not in ("أمن", "محاسب", "إداري"):
                    codes.append("EMP-HEALTH")
                if o["pack"] == "hospital" and role in CLINICAL:
                    codes.append("EMP-SCFHS")
                for code in codes:
                    t = templates[code]
                    if o["pack"] not in t["packs"]:
                        continue
                    exp = today + timedelta(days=_offset(rng, t["lead_days"], t["recurrence_months"]))
                    c.execute("INSERT INTO emp_doc(org_id,employee_id,template_code,expiry) VALUES(?,?,?,?)",
                              (oid, eid, code, exp.isoformat()))
    c.commit()
    c.close()


_CHANGE_COLS = {"status": "TEXT DEFAULT 'published'", "provenance": "TEXT DEFAULT 'manual'", "ai_provider": "TEXT",
                "ai_confidence": "REAL", "ai_notes": "TEXT DEFAULT '[]'", "evidence": "TEXT DEFAULT '[]'", "source_hash": "TEXT",
                "source_text": "TEXT", "created_at": "TEXT", "reviewed_by": "TEXT", "reviewed_at": "TEXT", "reject_reason": "TEXT"}


def _migrate(c: sqlite3.Connection) -> None:
    """Bring a v1 database up to date (v1 -> v2 added the review-gate columns on `change`)."""
    have = {r["name"] for r in c.execute("PRAGMA table_info(change)")}
    for col, decl in _CHANGE_COLS.items():
        if col not in have:
            c.execute(f"ALTER TABLE change ADD COLUMN {col} {decl}")
    have_t = {r["name"] for r in c.execute("PRAGMA table_info(template)")}
    for col in ("verified_by", "verified_on"):          # who legally verified an obligation, and when (null = not verified)
        if col not in have_t:
            c.execute(f"ALTER TABLE template ADD COLUMN {col} TEXT")
    c.commit()


def _applies(t: dict, pack: str, headcount: int) -> bool:
    return pack in t["packs"] and headcount >= t.get("min_headcount", 0)
