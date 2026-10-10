"""v0.5: score explanation, remind hand-off, owner summary."""
import os
import sys
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp()
os.environ["IMTITHAL_DB"] = str(Path(_TMP) / "wow.db")
os.environ["AS_OF"] = "2026-10-09"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient

import db
import main


@pytest.fixture()
def client():
    db.init(reset=True)
    with TestClient(main.app) as c:
        yield c


def first_org(c):
    return c.get("/api/orgs").json()["orgs"][0]["id"]


def test_explain_drivers_add_up_to_deduction(client):
    oid = first_org(client)
    d = client.get(f"/api/orgs/{oid}/score-explain").json()
    total = sum(x["points"] for x in d["drivers"]) + d["other_points"]
    assert abs(total - (100 - d["score"])) <= 1.0
    assert d["scenarios"]["fix_top3"] >= d["score"]
    assert d["scenarios"]["fix_overdue"] >= d["scenarios"]["fix_top3"] or d["scenarios"]["fix_overdue"] >= d["score"]
    pts = [x["points"] for x in d["drivers"]]
    assert pts == sorted(pts, reverse=True)


def test_remind_validates_and_logs(client):
    oid = first_org(client)
    item = client.get(f"/api/orgs/{oid}/score-explain").json()["drivers"][0]
    r = client.post(f"/api/orgs/{oid}/remind", json={"item_id": item["id"]})
    assert r.status_code == 200 and r.json()["to"]["name"] and r.json()["text"]
    assert client.post(f"/api/orgs/{oid}/remind", json={"item_id": "bogus"}).status_code in (400, 422)
    assert client.post(f"/api/orgs/{oid}/remind", json={"item_id": "o-999999"}).status_code == 404


def test_owner_summary_and_wins(client):
    oid = first_org(client)
    o = client.get(f"/api/orgs/{oid}/owner").json()
    assert 0 <= o["score"] <= 100 and len(o["actions"]) <= 3
    assert o["history"] and o["history"][-1]["score"] == o["score"]
    assert "من 100" in o["digest"]["body"] and " / 100" not in o["digest"]["body"]
    again = client.get(f"/api/orgs/{oid}/owner").json()
    assert len(again["history"]) == len(o["history"])  # one snapshot per day
