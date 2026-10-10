# امتثال (Imtithal) — prototype v0.2

Arabic-first compliance platform for multi-branch Saudi employers (hotels, hospitals, companies):
obligations + employee-document expiries → dated, scored, with fix steps, a regulatory-change feed and a VIP "fix it for me" request flow.

**Demo data only.** All obligations are unverified until legally reviewed; penalty figures are illustrative.

## Run
    pip install -r requirements.txt
    python -m uvicorn main:app --port 8000
    # customers:  http://localhost:8000
    # analysts:   http://localhost:8000/admin   (demo token: demo-admin)
    # AS_OF=2026-10-09 pins the "today" date; delete imtithal.db to reseed

## v2 — AI-assisted regulatory changes (reviewer-gated)

Analyst pastes the text of a decision (or an allow-listed `*.gov.sa` URL) in `/admin` → a **draft** is generated
(title, authority, dates, summary, which obligations and sectors are affected, doubts, supporting quotes) →
the analyst edits it, sees the **blast radius** (which customers' branches would see it) → a named reviewer
confirms it against the source and publishes. **Customers never see drafts.** The gate is enforced server-side
(`admin.publish`), and published items carry "reviewed by an analyst" (and "drafted with AI" when applicable).

| Setting | Meaning |
|---|---|
| `ANTHROPIC_API_KEY` | Enables the model drafter (tool-use with a schema; `affects` is constrained to real obligation codes). |
| `IMTITHAL_LLM` | `auto` (default: model if key present, else rules) or `rules` to force the offline drafter. |
| `IMTITHAL_LLM_MODEL` | Model id (default `claude-sonnet-5-5`). |
| `IMTITHAL_ADMIN_TOKEN` | Analyst token. **Defaults to `demo-admin` — set your own.** Real auth (SSO/OTP + roles) is Phase 1. |

Safeguards: source text is fenced and treated as untrusted; model output is re-validated (unknown codes, bad dates and
over-long fields are dropped); any provider failure falls back to a keyword-rules drafter that labels itself as *not AI*;
only public regulatory text is sent to the model, never customer data; URL ingestion is https-only, allow-listed,
re-validated on every redirect and blocked from private addresses; duplicate sources are rejected.

## v0.3 — the "show me my own exposure" demo

- **Import** (`POST /api/import`, UI tab «استيراد بياناتك»): CSV/Excel of employee documents and branch licences → a new organisation with scores in seconds.
  Document names are matched in Arabic/English (`library.DOC_ALIASES`), Hijri dates are converted in the browser, rows that cannot be mapped are returned with a reason,
  and obligations the customer gave no date for are listed as `missing` — **dates are never guessed**.
- **Alerts** (`GET /api/orgs/{id}/alerts`): the WhatsApp-style messages and weekly owner digest the customer would receive, generated from live data (preview only; sending needs a messaging provider).
- **Exposure hero, countdown, branch ranking vs the portfolio average, owner PDF report, Excel (CSV) export, VIP status tracker, 60-second guided tour.**
- **Verification fields** (`verified_by`, `verified_on`) on every obligation: all items stay "under legal review" until a real reviewer signs them off.

**Import formats handled** (`static/import-parse.js`, shared by the browser and `tests/`): title rows above the header, one row per document *or* one column per document
(the usual Muqeem/Qiwa layout), Hijri and Gregorian dates (`1448/05/12`, `20-Oct-2026`, Arabic-Indic digits, Excel serials), blank branch cells (filled down), ID-number columns
(so two employees with the same name stay separate), and fuzzy document names — guesses are listed back to the customer. Fixtures live in `tests/fixtures/`;
the xlsx case needs `npm i xlsx` and is skipped otherwise.

## Static demo (Netlify)
    python scripts/build_static.py      # writes dist/ (browser-side engine, no server)
    python scripts/parity_check.py      # replays 150+ requests against FastAPI and the JS engine; must report 0 mismatches
`netlify.toml` builds and publishes `dist/`. The analyst console is not part of the static build.

## Tests
    pip install -r requirements-dev.txt
    pytest

## v0.4 — "where / who / how / what it costs" in one look
- Heat map (branch × domain) on the home screen; click a cell, a branch, a domain or a person to open a side drawer with the items.
- Every item now carries a domain, an owner (default: branch manager, or HR for employee documents), an optional internal due date and a cautious, unverified "possible consequence" line. Assignment: `POST /api/orgs/{id}/assign`; roster: `GET /api/orgs/{id}/staff`.
- "View as" switch: owner / HR manager / branch manager (client-side view; real roles and auth come later).
- Named people exist only for the three seeded demo organisations; imported organisations get role titles.

## v0.5 — first-run "wow", explainable score, one-tap fixes, owner view
- **Reveal after import:** a full-screen "your exposure today" moment (total SAR, worst branch, top 3 items).
- **Forgiving import:** per-row problem table with inline fixes (branch, document type, date, employee), drop-row, duplicate detection.
- **Explainable score:** `GET /api/orgs/{id}/score-explain` — the two weighted parts, the items costing the most points (exact shares of the deduction) and "if you fix these" scenarios.
- **One-tap actions on every red item:** remind owner (`POST /api/orgs/{id}/remind` → prepared WhatsApp text, logged as *prepared*; nothing is sent by the server), assign, resolve, bulk-assign.
- **Owner view:** `GET /api/orgs/{id}/owner` — score, money, worst branch, top 3 actions, wins ("fixed since you started", exposure removed from the audit log), real daily score history and weekly digest.
- Calendar with Hijri + Gregorian dates, global search, good-news/empty states.
- Honesty: score history only contains real daily snapshots; exposure removed is the penalty of items that were overdue/soon when completed; score weights are assumptions, not legal facts.
- Every endpoint is mirrored in `static/demo-api.js`; `scripts/parity_check.py` must report 0 mismatches.
