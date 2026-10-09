"""Messy real-world exports -> rows -> POST /api/import. Needs node; the xlsx case also needs `npm i xlsx` (skipped otherwise)."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp()
os.environ["IMTITHAL_DB"] = str(Path(_TMP) / "p.db")
os.environ["AS_OF"] = "2026-10-09"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest
from fastapi.testclient import TestClient

import db
import main

FIX = ROOT / "tests" / "fixtures"
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


@pytest.fixture()
def client():
    db.init(reset=True)
    with TestClient(main.app) as c:
        yield c


def parse(client, name, default=""):
    dt = Path(_TMP) / "doc_types.json"
    dt.write_text(json.dumps(client.get("/api/import/doc-types").json()))
    p = subprocess.run(["node", str(ROOT / "tests" / "parse_fixture.js"), str(dt), str(FIX / name), default],
                       capture_output=True, text=True, env={**os.environ, "NODE_PATH": os.environ.get("NODE_PATH", "")})
    if p.returncode == 3:
        pytest.skip("xlsx package not installed")
    return json.loads(p.stdout)


def load(client, name, pack="hotel", default=""):
    parsed = parse(client, name, default)
    assert "error" not in parsed, parsed
    res = client.post("/api/import", json=dict(org_name="t", pack=pack, rows=parsed["rows"])).json()
    return parsed, res


def test_muqeem_wide_with_title_rows_hijri_and_fill_down(client):
    parsed, res = load(client, "muqeem_wide.csv")
    info = parsed["info"]
    assert info["format"] == "wide" and info["header_row"] == 3
    assert {c["code"] for c in info["doc_columns"]} == {"EMP-IQAMA", "EMP-WP", "EMP-HEALTH", "EMP-INS"}
    assert "رقم الإقامة" == info["mapped"]["emp_id"]                  # the ID-number column is an identifier, never a document
    assert res["imported"]["branches"] == 2
    assert res["imported"]["employees"] == 4                         # two "أحمد خان" with different iqama numbers stay separate
    assert res["imported"]["employee_docs"] == 13                    # blank cells create nothing
    assert res["skipped_total"] == 0, res["skipped"]
    items = client.get(f"/api/orgs/{res['org_id']}/employee-docs").json()["items"]
    iq = next(i for i in items if i["code"] == "EMP-IQAMA" and i["employee"]["name"] == "محمد علي")
    assert iq["due_date"] == "2026-10-23"                           # 1448/05/12 AH (Umm al-Qura)
    khan = [i for i in items if i["employee"]["name"] == "أحمد خان"]
    assert {i["branch_name"] for i in khan} == {"فرع الرياض"}          # blank branch cell = same branch as the row above


def test_same_name_different_id_are_two_employees(client):
    parsed, res = load(client, "english_wide.xlsx", default="")
    assert res["imported"]["employees"] == 3                         # Ravi Kumar twice (different iqama numbers) + Nora
    assert res["skipped_total"] == 0


def test_english_long_semicolon_mixed_formats_and_reasons(client):
    parsed, res = load(client, "english_long_semicolon.csv")
    reasons = {s["row"]: s["reason"] for s in res["skipped"]}
    assert reasons[4] == "التاريخ غير صالح (YYYY-MM-DD)"             # 2026-13-45 is not a date
    assert reasons[5] == "التاريخ فارغ"
    assert reasons[6] == "نوع الوثيقة غير معروف"
    assert res["imported"]["employee_docs"] == 3                      # iqama, work permit, insurance (Arabic-Indic digits)
    assert any(f["document"] == "Iqama (Residence)" for f in res["fuzzy"])     # guessed matches are surfaced, not hidden
    items = client.get(f"/api/orgs/{res['org_id']}/employee-docs").json()["items"]
    assert any(i["due_date"] == "2026-10-20" and i["employee"]["name"] == "Khan, Ahmed" for i in items)
    assert any(i["due_date"] == "2026-10-21" for i in items)


def test_branch_licence_sheet(client):
    parsed, res = load(client, "branch_licences.csv")
    assert parsed["info"]["format"] == "wide" and "ملاحظات" in parsed["info"]["ignored"]
    assert res["imported"]["obligations"] == 5 and res["imported"]["branches"] == 2


def test_unrecognised_file_gets_a_helpful_error(client, tmp_path):
    f = tmp_path / "x.csv"; f.write_text("a,b,c\n1,2,3\n")
    dt = tmp_path / "dt.json"; dt.write_text(json.dumps(client.get("/api/import/doc-types").json()))
    p = subprocess.run(["node", str(ROOT / "tests" / "parse_fixture.js"), str(dt), str(f)], capture_output=True, text=True)
    assert "الأعمدة الموجودة" in json.loads(p.stdout)["error"]
