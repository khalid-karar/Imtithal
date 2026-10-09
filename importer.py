"""CSV/Excel import: turns the rows HR already has (employee + document + expiry, branch licences + expiry) into a new
organisation with branches, employees, documents and obligations. The browser parses the file; this module validates
rows and writes them. Nothing is guessed: rows we cannot map are returned with a reason, and obligations the customer did
not give dates for are reported as `missing` instead of being invented."""
import re
from datetime import date

import db
import library

MAX_ROWS = 5000
PACKS = ("hotel", "hospital", "company")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DIACRITICS = re.compile("[ً-ٰٟـ]")     # harakat, dagger alef, tatweel


class ImportError_(Exception):
    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


def norm_key(s) -> str:
    s = re.sub(r"\s+", " ", str(s if s is not None else "").strip().lower())
    s = _DIACRITICS.sub("", s)
    for a, b in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ة", "ه"), ("ى", "ي")):
        s = s.replace(a, b)
    return s


def alias_table(templates: list[dict], aliases: dict) -> dict:
    """normalised name -> template code; first template (by code) wins on a clash."""
    out: dict[str, str] = {}
    for t in sorted(templates, key=lambda t: t["code"]):
        for name in [t["code"], t["title"], *aliases.get(t["code"], [])]:
            out.setdefault(norm_key(name), t["code"])
    return out


def _valid_date(s: str) -> bool:
    if not _DATE.match(s):
        return False
    try:
        date.fromisoformat(s)
        return True
    except ValueError:
        return False


def run(c, payload: dict) -> dict:
    name = str(payload.get("org_name") or "").strip()
    pack = payload.get("pack")
    rows = payload.get("rows") or []
    if not name or len(name) > 80:
        raise ImportError_("اسم المنشأة مطلوب (حتى 80 حرفًا)")
    if pack not in PACKS:
        raise ImportError_("القطاع غير صالح")
    if not rows:
        raise ImportError_("لا توجد صفوف للاستيراد")
    if len(rows) > MAX_ROWS:
        raise ImportError_(f"الحد الأقصى {MAX_ROWS} صف")

    templates = []
    for r in c.execute("SELECT code,title,scope,packs,min_headcount,recurrence_months FROM template ORDER BY code"):
        d = dict(r)
        d["packs"] = __import__("json").loads(d["packs"])
        templates.append(d)
    by_code = {t["code"]: t for t in templates}
    table = alias_table(templates, library.DOC_ALIASES)

    skipped: list[dict] = []
    branches: dict[str, dict] = {}       # name -> {id, employees: {name: eid}, codes: set, city}
    seen: set = set()
    n_emp = n_docs = n_obl = 0
    org_id = None

    def skip(idx, reason):
        skipped.append(dict(row=idx, reason=reason))

    for idx, r in enumerate(rows, start=1):
        g = lambda k: str((r or {}).get(k) or "").strip()
        branch, city, emp, role, doc, due = g("branch"), g("city"), g("employee"), g("role"), g("document"), g("date")
        if not branch:
            skip(idx, "الفرع مطلوب"); continue
        code = table.get(norm_key(doc))
        if not code:
            skip(idx, "نوع الوثيقة غير معروف"); continue
        t = by_code[code]
        if pack not in t["packs"]:
            skip(idx, "غير منطبقة على هذا القطاع"); continue
        if not _valid_date(due):
            skip(idx, "التاريخ غير صالح (YYYY-MM-DD)"); continue
        if t["scope"] == "employee" and not emp:
            skip(idx, "اسم الموظف مطلوب لهذه الوثيقة"); continue
        if t["scope"] == "branch" and emp:
            skip(idx, "هذا البند يخص الفرع وليس موظفًا"); continue
        key = (branch, emp, code)
        if key in seen:
            skip(idx, "مكرر"); continue
        seen.add(key)

        if org_id is None:
            org_id = c.execute("INSERT INTO org(name,pack,city) VALUES(?,?,?)", (name, pack, city)).lastrowid
        b = branches.get(branch)
        if b is None:
            bid = c.execute("INSERT INTO branch(org_id,name,city,pack,headcount) VALUES(?,?,?,?,0)", (org_id, branch, city, pack)).lastrowid
            b = branches[branch] = dict(id=bid, employees={}, codes=set())
        if t["scope"] == "branch":
            c.execute("INSERT INTO instance(org_id,branch_id,template_code,due_date,last_done,evidence_note) VALUES(?,?,?,?,NULL,'')",
                      (org_id, b["id"], code, due))
            b["codes"].add(code)
            n_obl += 1
        else:
            eid = b["employees"].get(emp)
            if eid is None:
                eid = c.execute("INSERT INTO employee(org_id,branch_id,name,role,is_saudi) VALUES(?,?,?,?,0)", (org_id, b["id"], emp, role)).lastrowid
                b["employees"][emp] = eid
                n_emp += 1
            c.execute("INSERT INTO emp_doc(org_id,employee_id,template_code,expiry) VALUES(?,?,?,?)", (org_id, eid, code, due))
            n_docs += 1

    if org_id is None:
        return dict(org_id=None, imported=dict(branches=0, employees=0, employee_docs=0, obligations=0),
                    skipped=skipped[:50], skipped_total=len(skipped), missing=[])

    missing = []
    for bname, b in branches.items():
        heads = len(b["employees"])
        c.execute("UPDATE branch SET headcount=? WHERE id=?", (heads, b["id"]))
        miss = [t["title"] for t in templates
                if t["scope"] == "branch" and pack in t["packs"] and heads >= (t["min_headcount"] or 0) and t["code"] not in b["codes"]]
        if miss:
            missing.append(dict(branch=bname, branch_id=b["id"], count=len(miss), titles=miss[:5]))
    return dict(org_id=org_id, imported=dict(branches=len(branches), employees=n_emp, employee_docs=n_docs, obligations=n_obl),
                skipped=skipped[:50], skipped_total=len(skipped), missing=missing)
