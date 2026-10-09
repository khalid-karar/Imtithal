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

## Tests
    pip install -r requirements-dev.txt
    pytest
