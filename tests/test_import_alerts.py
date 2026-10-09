"""Import, alerts and verification-field tests."""
import os
import sys
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp()
os.environ["IMTITHAL_DB"] = str(Path(_TMP) / "w.db")
os.environ["AS_OF"] = "2026-10-09"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient

import alerts
import db
import importer
import main


@pytest.fixture()
def client():
    db.init(reset=True)
    with TestClient(main.app) as c:
        yield c


def row(**k):
    d = dict(branch="الرياض", city="الرياض", employee="", role="", document="", date="2026-10-20")
    d.update(k)
    return d


def test_norm_key_folds_arabic_variants():
    assert importer.norm_key("  الإقامة ") == importer.norm_key("الاقامة")
    assert importer.norm_key("رخصة البلديّة") == importer.norm_key("رخصة البلدية")
    assert importer.norm_key("IQAMA") == "iqama"


def test_import_maps_aliases_and_reports_skips(client):
    rows = [row(employee="سعد", role="نادل", document="Iqama"),
            row(employee="سعد", document="الإقامة"),                      # duplicate
            row(document="civil defense"),
            row(employee="x", document="???"),                             # unknown
            row(employee="x", document="Iqama", date="20/10/2026"),   # not ISO -> client must convert
            dict(branch="", document="Iqama", date="2026-10-20"),
            row(employee="x", document="civil defense")]                         # branch licence given with an employee
    r = client.post("/api/import", json=dict(org_name="تجربة", pack="hotel", rows=rows))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["imported"] == dict(branches=1, employees=1, employee_docs=1, obligations=1)
    reasons = {s["row"]: s["reason"] for s in d["skipped"]}
    assert reasons == {2: "مكرر", 4: "نوع الوثيقة غير معروف", 5: "التاريخ غير صالح (YYYY-MM-DD)", 6: "الفرع مطلوب",
                       7: "هذا البند يخص الفرع وليس موظفًا"}
    assert client.get(f"/api/orgs/{d['org_id']}/overview").json()["counts"]["total"] == 2


def test_import_never_invents_dates(client):
    d = client.post("/api/import", json=dict(org_name="x", pack="hotel", rows=[row(document="civil defense")])).json()
    assert d["missing"] and d["missing"][0]["count"] > 5          # everything else is reported as missing, not guessed
    items = client.get(f"/api/branches/{d['missing'][0]['branch_id']}/items").json()["items"]
    assert [i["code"] for i in items] == ["LIC-CD"]


def test_import_validation(client):
    ok = [row(document="civil defense")]
    assert client.post("/api/import", json=dict(org_name="", pack="hotel", rows=ok)).status_code == 422
    assert client.post("/api/import", json=dict(org_name="x", pack="bank", rows=ok)).status_code == 422
    assert client.post("/api/import", json=dict(org_name="x", pack="hotel", rows=[])).status_code == 422
    big = client.post("/api/import", json=dict(org_name="x", pack="hotel", rows=ok * 5001))
    assert big.status_code == 422


def test_import_sector_mismatch_is_skipped_not_created(client):
    d = client.post("/api/import", json=dict(org_name="x", pack="company", rows=[row(employee="e", document="سباهي")])).json()
    assert d["org_id"] is None and d["skipped"][0]["reason"] == "غير منطبقة على هذا القطاع"


def test_alerts_shape_and_text(client):
    d = client.get("/api/orgs/1/alerts").json()
    assert d["summary"]["overdue_items"] > 0 and d["summary"]["penalty_sar"] > 0
    assert 1 <= len(d["messages"]) <= 6
    m = d["messages"][0]
    assert m["channel"] == "whatsapp" and "تنبيه امتثال" in m["text"] and "الإجراء:" in m["text"]
    assert "مؤشر الجاهزية" in d["digest"]["body"] and d["digest"]["subject"].startswith("ملخص امتثال")
    assert client.get("/api/orgs/99/alerts").status_code == 404


def test_ar_days():
    assert [alerts.ar_days(n) for n in (1, 2, 4, 11)] == ["يوم واحد", "يومين", "4 أيام", "11 يومًا"]


def test_items_expose_verification_fields_unverified_by_default(client):
    it = client.get("/api/branches/1/items").json()["items"][0]
    assert it["verified"] is False and it["verified_by"] is None and it["verified_on"] is None


def test_verification_fields_flow_through_when_set(client):
    c = db.conn()
    c.execute("UPDATE template SET verified=1, verified_by='م. فلان', verified_on='2026-10-01' WHERE code='LIC-CD'")
    c.commit(); c.close()
    items = client.get("/api/branches/2/items").json()["items"]
    cd = next(i for i in items if i["code"] == "LIC-CD")
    assert cd["verified"] is True and cd["verified_by"] == "م. فلان" and cd["verified_on"] == "2026-10-01"
