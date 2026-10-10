"""Replay one request sequence against FastAPI (TestClient) and the browser engine (demo-api.js under node);
fail on any difference. Run: python scripts/parity_check.py"""
import json, os, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
AS_OF = "2026-10-09"
TS_KEYS = {"ts", "created_at", "updated_at", "acknowledged_at"}


def norm(o):
    if isinstance(o, dict):
        return {k: ("<ts>" if k in TS_KEYS else norm(v)) for k, v in o.items()}
    if isinstance(o, list):
        return [norm(x) for x in o]
    return o


def main():
    import build_static
    tmp = tempfile.mkdtemp()
    snap = build_static.snapshot(AS_OF, Path(tmp) / "p.db")        # also seeds the DB the API will use
    data = Path(tmp) / "data.json"
    data.write_text(json.dumps(snap, ensure_ascii=False))
    from fastapi.testclient import TestClient
    import main as app_main
    client = TestClient(app_main.app)

    orgs = [o["id"] for o in snap["orgs"]]
    reqs = [("GET", "/api/health", None), ("GET", "/api/version", None), ("GET", "/api/orgs", None), ("GET", "/api/import/doc-types", None)]
    for o in orgs:
        reqs += [("GET", f"/api/orgs/{o}/{p}", None) for p in ("overview", "changes", "vip", "audit", "employee-docs", "score-explain", "owner")]
        for q in ("status=overdue", "status=due_soon", "code=iqama", "status=overdue&code=iqama"):
            reqs.append(("GET", f"/api/orgs/{o}/employee-docs?{q}", None))
    for b in snap["branches"]:
        reqs.append(("GET", f"/api/branches/{b['id']}/items", None))
        for q in ("status=overdue", "kind=employee_doc", "kind=obligation&status=due_soon", "status=ok"):
            reqs.append(("GET", f"/api/branches/{b['id']}/items?{q}", None))
        reqs.append(("GET", f"/api/orgs/{b['org_id']}/employee-docs?branch_id={b['id']}", None))
        reqs.append(("GET", f"/api/orgs/{b['org_id']}/score-explain?branch_id={b['id']}", None))
    ins = [i["id"] for i in snap["instances"]]
    docs = [d["id"] for d in snap["emp_docs"]]
    # mutations, each followed by reads of what they touch
    for i in (ins[0], ins[5], ins[40]):
        reqs.append(("POST", f"/api/items/o-{i}/complete", {"note": "تم", "done_date": "2026-10-01"}))
    reqs.append(("POST", f"/api/items/o-{ins[7]}/complete", {}))
    reqs.append(("POST", f"/api/items/e-{docs[0]}/complete", {"new_expiry": "2028-01-31"}))
    reqs.append(("POST", f"/api/items/e-{docs[3]}/complete", {}))
    reqs.append(("POST", f"/api/items/e-{docs[400]}/complete", {}))
    for o in orgs:
        reqs.append(("POST", f"/api/orgs/{o}/changes/{snap['changes'][0]['id']}/acknowledge", None))
        reqs.append(("POST", f"/api/orgs/{o}/changes/{snap['changes'][1]['id']}/acknowledge", None))
    code = snap["vip_services"][0]["code"]
    b0 = snap["branches"][0]["id"]
    reqs += [("POST", f"/api/orgs/{orgs[0]}/vip/requests", {"branch_id": b0, "service_code": code, "item_ref": "x", "note": "n"}),
             ("POST", f"/api/orgs/{orgs[0]}/vip/requests", {"service_code": code}),
             ("POST", "/api/vip/requests/1/advance", None), ("POST", "/api/vip/requests/1/advance", None),
             ("POST", "/api/vip/requests/1/advance", None), ("POST", "/api/vip/requests/2/advance", None)]
    # responsibility: roster, default owners, assignments (obligation + employee-doc group), reassign, errors
    ob0 = ins[2]
    reqs += [("GET", f"/api/orgs/{o}/staff", None) for o in orgs]
    reqs += [("POST", f"/api/orgs/{orgs[0]}/assign", {"item_id": f"o-{ob0}", "owner_id": "hr", "due": "2026-10-20"}),
             ("POST", f"/api/orgs/{orgs[0]}/assign", {"item_id": f"o-{ob0}", "owner_id": f"b{b0}"}),
             ("POST", f"/api/orgs/{orgs[0]}/assign", {"item_id": f"g-{b0}-EMP-IQAMA-overdue", "owner_id": "gm", "due": "2026-10-25"}),
             ("POST", f"/api/orgs/{orgs[0]}/assign", {"item_id": f"g-{b0}-EMP-IQAMA", "owner_id": f"b{b0}"}),
             ("POST", f"/api/orgs/{orgs[0]}/assign", {"item_id": "x-1", "owner_id": "hr"}),
             ("POST", f"/api/orgs/{orgs[0]}/assign", {"item_id": f"o-{ob0}", "owner_id": "nobody"}),
             ("POST", f"/api/orgs/{orgs[0]}/assign", {"item_id": f"o-{ob0}", "owner_id": "hr", "due": "2026-02-30"}),
             ("POST", f"/api/orgs/{orgs[0]}/assign", {"item_id": "o-999999", "owner_id": "hr"}),
             ("POST", f"/api/orgs/{orgs[0]}/assign", {"item_id": "g-999-EMP-IQAMA", "owner_id": "hr"}),
             ("POST", "/api/orgs/99/assign", {"item_id": "o-1", "owner_id": "hr"}), ("GET", "/api/orgs/99/staff", None)]
    # one-tap reminders: obligation, single employee document, grouped employee documents, and the error paths
    reqs += [("POST", f"/api/orgs/{orgs[0]}/remind", {"item_id": f"o-{ob0}"}),
             ("POST", f"/api/orgs/{orgs[0]}/remind", {"item_id": f"e-{docs[0]}"}),
             ("POST", f"/api/orgs/{orgs[0]}/remind", {"item_id": f"g-{b0}-EMP-IQAMA-overdue"}),
             ("POST", f"/api/orgs/{orgs[0]}/remind", {"item_id": f"g-{b0}-EMP-IQAMA-soon"}),
             ("POST", f"/api/orgs/{orgs[0]}/remind", {"item_id": "nonsense"}), ("POST", f"/api/orgs/{orgs[0]}/remind", {"item_id": "o-999999"}),
             ("POST", f"/api/orgs/{orgs[0]}/remind", {"item_id": "g-999-EMP-IQAMA-overdue"}), ("POST", "/api/orgs/99/remind", {"item_id": "o-1"})]
    reqs += [("GET", f"/api/orgs/{o}/{p}", None) for o in orgs for p in ("score-explain", "owner", "audit")]
    reqs += [("GET", "/api/orgs/99/score-explain", None), ("GET", "/api/orgs/99/owner", None), ("GET", f"/api/orgs/{orgs[0]}/score-explain?branch_id=999", None)]
    # alerts (before and after the mutations above)
    reqs += [("GET", f"/api/orgs/{o}/alerts", None) for o in orgs]
    # import: aliases (Arabic/English/hamza variants), duplicates, bad dates, unknown docs, sector mismatch, scope errors
    rows = [
        dict(branch="فرع الرياض", city="الرياض", employee="سعد القحطاني", role="نادل", document="Iqama", date="2026-10-20"),
        dict(branch="فرع الرياض", employee="سعد القحطاني", document="الإقامة", date="2026-10-21"),
        dict(branch="فرع الرياض", employee="سعد القحطاني", document="رخصة العمل", date="2026-12-01"),
        dict(branch="فرع الرياض", employee="سعد القحطاني", document="تأمين طبي", date="2026-09-01"),
        dict(branch="فرع الرياض", employee="منى الحربي", role="استقبال", document="شهادة صحية", date="2026-10-12"),
        dict(branch="فرع الرياض", document="civil defense", date="2026-09-01"),
        dict(branch="فرع الرياض", document="رخصة البلدية", date="2027-03-01"),
        dict(branch="فرع الرياض", document="رخصة البلديّة", date="2027-03-05"),
        dict(branch="فرع جدة", city="جدة", employee="علي", role="طاهٍ", document="  IQAMA ", date="2026-11-15"),
        dict(branch="فرع جدة", employee="علي", document="عقد العمل", date="2027-01-01"),
        dict(branch="فرع جدة", document="Commercial Registration", date="2026-10-30"),
        dict(branch="فرع جدة", document="الدفاع المدني", date="2026-10-01"),
        dict(branch="", document="Iqama", date="2026-10-20"),
        dict(branch="فرع جدة", employee="x", document="???", date="2026-10-20"),
        dict(branch="فرع جدة", employee="x", document="Iqama", date="20/10/2026"),
        dict(branch="فرع جدة", employee="x", document="Iqama", date="2026-02-30"),
        dict(branch="فرع جدة", document="Iqama", date="2026-10-20"),
        dict(branch="فرع جدة", employee="y", document="سباهي", date="2026-10-20"),
        dict(branch="فرع جدة", employee="y", document="شهادة السلامة", date="2026-10-20"),
        dict(branch="فرع جدة", employee="ravi", emp_id="1", role="فني", document="تجديد الإقامة السارية", date="2026-11-20"),   # fuzzy
        dict(branch="فرع جدة", employee="ravi", emp_id="2", role="فني", document="Iqama", date="2026-11-21"),     # same name, other id
        dict(branch="فرع جدة", employee="ravi", emp_id="2", role="فني", document="iqama", date="2026-11-22"),     # duplicate of the above
        dict(branch="فرع جدة", employee="ravi", emp_id="2", document="Work Permit (Qiwa)", date=""),               # empty date
        dict(branch="فرع جدة", document="شهادة السلامة والصحة المهنية", date="2026-12-01"),                         # longest-name fuzzy
    ]
    nb = max(b["id"] for b in snap["branches"])
    reqs += [("POST", "/api/import", dict(org_name="منشأة تجريبية", pack="hotel", rows=rows))]
    new_org = max(orgs) + 1
    reqs += [("GET", f"/api/orgs/{new_org}/{p}", None) for p in ("overview", "alerts", "changes", "vip", "audit", "employee-docs", "score-explain", "owner")]
    reqs += [("GET", "/api/orgs", None)] + [("GET", f"/api/branches/{nb + k}/items", None) for k in (1, 2)]
    reqs += [("POST", f"/api/items/e-{max(docs) + 1}/complete", {"new_expiry": "2029-01-01"}),
             ("POST", f"/api/orgs/{new_org}/vip/requests", {"service_code": code, "branch_id": nb + 1}),
             ("GET", f"/api/orgs/{new_org}/vip", None), ("GET", f"/api/orgs/{new_org}/alerts", None)]
    reqs += [("GET", f"/api/orgs/{new_org}/staff", None)]
    reqs += [("POST", "/api/import", dict(org_name="", pack="hotel", rows=rows)),
             ("POST", "/api/import", dict(org_name="x", pack="bank", rows=rows)),
             ("POST", "/api/import", dict(org_name="x", pack="hotel", rows=[])),
             ("POST", "/api/import", dict(org_name="x", pack="company", rows=[dict(branch="ب", employee="e", document="سباهي", date="2026-10-20")])),
             ("POST", "/api/import", dict(org_name="شركة", pack="company", rows=[dict(branch="ب", employee="e", document="iqama", date="2027-10-20")])),
             ("GET", f"/api/orgs/{new_org + 1}/overview", None), ("GET", f"/api/orgs/{new_org + 1}/alerts", None)]
    # errors
    reqs += [("POST", "/api/items/x-1/complete", {}), ("POST", "/api/items/o-99999/complete", {}),
             ("POST", "/api/items/e-99999/complete", {}), ("POST", "/api/items/o-abc/complete", {}),
             ("GET", "/api/orgs/99/overview", None), ("GET", "/api/orgs/99/vip", None),
             ("GET", "/api/branches/999/items", None), ("POST", f"/api/orgs/{orgs[0]}/vip/requests", {"service_code": "nope"}),
             ("POST", "/api/vip/requests/999/advance", None),
             ("POST", f"/api/orgs/{orgs[0]}/changes/999/acknowledge", None)]
    # re-read everything touched
    for o in orgs:
        reqs += [("GET", f"/api/orgs/{o}/{p}", None) for p in ("overview", "changes", "vip", "audit", "employee-docs", "score-explain", "owner")]
    for b in snap["branches"]:
        reqs.append(("GET", f"/api/branches/{b['id']}/items", None))

    py = []
    for m, u, b in reqs:
        r = client.get(u) if m == "GET" else client.post(u, json=b)
        py.append({"status": r.status_code, "body": r.json()})
    rq, ro = Path(tmp) / "reqs.json", Path(tmp) / "out.json"
    rq.write_text(json.dumps(reqs, ensure_ascii=False))
    subprocess.run(["node", str(ROOT / "scripts" / "parity.js"), str(data), str(rq), str(ro)], check=True)
    js = json.loads(ro.read_text())

    from collections import Counter
    print("statuses", dict(Counter(p["status"] for p in py)), "bytes", sum(len(json.dumps(p)) for p in py))
    assert any(p["status"]==200 and "overview" in u and p["body"]!=py[i0]["body"] for (m,u,b),p in zip(reqs,py) for i0 in [2]) , "mutations had no visible effect"
    bad = 0
    for (m, u, b), p, j in zip(reqs, py, js):
        if norm(p) != norm(j):
            bad += 1
            if bad <= 5:
                print("MISMATCH", m, u, b)
                pj, jj = json.dumps(norm(p), ensure_ascii=False, sort_keys=True), json.dumps(norm(j), ensure_ascii=False, sort_keys=True)
                k = next((n for n in range(min(len(pj), len(jj))) if pj[n] != jj[n]), 0)
                print("  py:", pj[max(0, k - 80):k + 120]); print("  js:", jj[max(0, k - 80):k + 120])
    print(f"{len(reqs)} requests, {bad} mismatches")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
