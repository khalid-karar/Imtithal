# امتثال (Imtithal) — project brief for every agent
Saudi HR/compliance SaaS. Arabic RTL. FastAPI + SQLite backend, dependency-free SPA, browser-side demo engine.

## Map (read only what you need; use Grep, then Read with offset/limit — index.html is 1400 dense lines)
- `main.py` endpoints · `engine.py` scoring/items · `db.py` schema · `alerts.py` messages/digest · `importer.py` import · `staff.py` roster · `library.py` regulatory templates · `llm.py` change drafting (reviewer-gated) · `admin.py`
- `static/index.html` whole UI · `static/demo-api.js` JS port of backend (Netlify demo) · `static/import-parse.js` shared parser
- `scripts/parity_check.py` replays requests against FastAPI and the JS port · `scripts/build_static.py` builds `dist/`

## Hard rules
1. **Parity:** every backend endpoint/engine change is mirrored in `static/demo-api.js`. `AS_OF=2026-10-09 python scripts/parity_check.py` must print `0 mismatches`.
2. **Honesty:** never guess dates, never fake data/history, no claim of "sent" unless a provider confirmed it. Penalty/deadline figures are estimates until `verified`.
3. **RTL:** numbers like "79 / 100" go in `ltr()` (`<bdi dir=ltr>`) or use "79 من 100" in plain text.
4. **Tests:** `AS_OF=2026-10-09 python -m pytest -q` green before any commit.
5. Branch per task (`feat/…`), never push to `main`. Commit trailers: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` and `Claude-Session: <session url>`.

## Agent protocol (saves tokens)
- Manager writes a task file `docs/handoff/<id>-<role>.md` (goal, files you own, done-when). Agent reads it, does the work, appends a **≤10-line result** (what changed, commands run, open issues). Chat replies stay ≤5 lines; details live in the file.
- File ownership: frontend → `static/index.html`, `static/import-parse.js`; backend → `*.py` (not scripts), `static/demo-api.js`; qa → `tests/`, `scripts/parity_check.py`; devops → `netlify.toml`, `scripts/build_static.py`, `.github/`, `requirements*.txt`, Dockerfile. Need a change in someone else's file → write it as a request in your handoff file, don't edit.
- Don't re-read files you just edited; don't paste whole files into replies; run narrow tests first (`pytest -q tests/test_x.py -k name`), full suite once at the end.
