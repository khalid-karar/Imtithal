# t1 backend — add GET /api/version
Goal: endpoint returning `{"version": "0.5.0", "as_of": "<db.as_of() iso>"}`; no DB access, no auth.
Own: main.py, static/demo-api.js (mirror in router; identical output).
Done when: endpoint works on FastAPI and in demo-api.js; narrow sanity check by hand.
Do NOT edit tests/ or parity_check.py (qa will add them). Result (≤10 lines) below.
## Result
