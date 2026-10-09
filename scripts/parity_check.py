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
    reqs = [("GET", "/api/health", None), ("GET", "/api/orgs", None)]
    for o in orgs:
        reqs += [("GET", f"/api/orgs/{o}/{p}", None) for p in ("overview", "changes", "vip", "audit", "employee-docs")]
        for q in ("status=overdue", "status=due_soon", "code=iqama", "status=overdue&code=iqama"):
            reqs.append(("GET", f"/api/orgs/{o}/employee-docs?{q}", None))
    for b in snap["branches"]:
        reqs.append(("GET", f"/api/branches/{b['id']}/items", None))
        for q in ("status=overdue", "kind=employee_doc", "kind=obligation&status=due_soon", "status=ok"):
            reqs.append(("GET", f"/api/branches/{b['id']}/items?{q}", None))
        reqs.append(("GET", f"/api/orgs/{b['org_id']}/employee-docs?branch_id={b['id']}", None))
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
    # errors
    reqs += [("POST", "/api/items/x-1/complete", {}), ("POST", "/api/items/o-99999/complete", {}),
             ("POST", "/api/items/e-99999/complete", {}), ("POST", "/api/items/o-abc/complete", {}),
             ("GET", "/api/orgs/99/overview", None), ("GET", "/api/orgs/99/vip", None),
             ("GET", "/api/branches/999/items", None), ("POST", f"/api/orgs/{orgs[0]}/vip/requests", {"service_code": "nope"}),
             ("POST", "/api/vip/requests/999/advance", None),
             ("POST", f"/api/orgs/{orgs[0]}/changes/999/acknowledge", None)]
    # re-read everything touched
    for o in orgs:
        reqs += [("GET", f"/api/orgs/{o}/{p}", None) for p in ("overview", "changes", "vip", "audit", "employee-docs")]
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
