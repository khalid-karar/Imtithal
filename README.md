# امتثال (Imtithal) — prototype v0.1

Arabic-first compliance platform for multi-branch Saudi employers (hotels, hospitals, companies):
obligations + employee-document expiries → dated, scored, with fix steps, a regulatory-change feed and a VIP "fix it for me" request flow.

**Demo data only.** All obligations are unverified until legally reviewed; penalty figures are illustrative.

## Run
    pip install -r requirements.txt
    python -m uvicorn main:app --port 8000
    # open http://localhost:8000
    # AS_OF=2026-10-09 pins the "today" date; delete imtithal.db to reseed
