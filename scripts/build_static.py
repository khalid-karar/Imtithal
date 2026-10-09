"""Build the server-less demo into dist/ (host it on Netlify or any static host).

    python scripts/build_static.py [--as-of 2026-10-09] [--out dist]

Bakes the seeded demo data into demo-data.json and ships static/index.html + demo-api.js, which answers the
/api/* calls in the browser. The analyst console (/admin) is deliberately NOT included: AI drafting needs a server.
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def snapshot(as_of: str, db_path: Path) -> dict:
    os.environ["AS_OF"] = as_of
    os.environ["IMTITHAL_DB"] = str(db_path)
    import db  # imported after env is set so DB_PATH points at the temp file

    db.DB_PATH = db_path
    db.init(reset=True)
    c = db.conn()
    rows = lambda q: [dict(r) for r in c.execute(q)]
    templates = []
    for r in c.execute("SELECT * FROM template ORDER BY code"):
        d = dict(r)
        d["fix_steps"], d["packs"] = json.loads(d["fix_steps"]), json.loads(d["packs"])
        d["verified"] = bool(d["verified"])
        templates.append(d)
    changes = []
    for r in c.execute("SELECT * FROM change WHERE status='published' ORDER BY effective DESC"):
        d = {k: r[k] for k in ("id", "title", "authority", "published", "effective", "summary", "action_required", "source_url",
                               "source_quality", "is_demo", "provenance", "reviewed_by")}
        d["affects"], d["packs"] = json.loads(r["affects"]), json.loads(r["packs"])
        changes.append(d)
    vip = []
    for r in c.execute("SELECT * FROM vip_service"):
        d = dict(r)
        d["packs"] = json.loads(d["packs"])
        vip.append(d)
    emp_docs = rows("SELECT d.id, d.org_id, d.template_code, d.expiry, e.id AS eid, e.name, e.role, e.branch_id "
                    "FROM emp_doc d JOIN employee e ON e.id=d.employee_id ORDER BY d.id")
    snap = dict(as_of=as_of, orgs=rows("SELECT * FROM org ORDER BY id"), branches=rows("SELECT * FROM branch ORDER BY id"),
                templates=templates, instances=rows("SELECT * FROM instance ORDER BY id"), emp_docs=emp_docs,
                changes=changes, vip_services=vip)
    c.close()
    snap["build_id"] = hashlib.sha256(json.dumps(snap, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]
    return snap


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--as-of", default=os.environ.get("AS_OF") or __import__("datetime").date.today().isoformat())
    ap.add_argument("--out", default=str(ROOT / "dist"))
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    with tempfile.TemporaryDirectory() as tmp:
        snap = snapshot(a.as_of, Path(tmp) / "build.db")
    (out / "demo-data.json").write_text(json.dumps(snap, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    shutil.copy(ROOT / "static" / "demo-api.js", out / "demo-api.js")
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    marker = "<script>\nconst S = "
    assert html.count(marker) == 1, "index.html layout changed: cannot inject demo-api.js"
    html = html.replace(marker, '<script src="demo-api.js"></script>\n' + marker)
    html = html.replace("<title>امتثال — منصة الامتثال التنظيمي</title>",
                        "<title>امتثال — عرض تجريبي</title>\n<meta name=\"robots\" content=\"noindex\">")
    (out / "index.html").write_text(html, encoding="utf-8")
    (out / "_headers").write_text(
        "/*\n  X-Robots-Tag: noindex\n  X-Content-Type-Options: nosniff\n  Referrer-Policy: no-referrer\n"
        "/demo-data.json\n  Cache-Control: no-cache\n", encoding="utf-8")
    print(f"built {out} — build_id={snap['build_id']} as_of={snap['as_of']} "
          f"orgs={len(snap['orgs'])} instances={len(snap['instances'])} emp_docs={len(snap['emp_docs'])}")


if __name__ == "__main__":
    main()
