# t1 backend — add GET /api/version
Goal: endpoint returning `{"version": "0.5.0", "as_of": "<db.as_of() iso>"}`; no DB access, no auth.
Own: main.py, static/demo-api.js (mirror in router; identical output).
Done when: endpoint works on FastAPI and in demo-api.js; narrow sanity check by hand.
Do NOT edit tests/ or parity_check.py (qa will add them). Result (≤10 lines) below.
## Result
- Added GET /api/version in main.py -> {"version":"0.5.0","as_of":"<iso>"}; no DB, no auth.
- Mirrored in static/demo-api.js router (right after /api/health), same output using TODAY.
- Checked: FastAPI TestClient response by hand; `node --check` on demo-api.js OK.
- Not run: parity_check/pytest (qa to add tests/parity case for /api/version).
- New response fields: version (string), as_of (YYYY-MM-DD). No open issues.
