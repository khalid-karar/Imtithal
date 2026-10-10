# t1 frontend — show version in footer
Contract: `GET /api/version` -> `{version: string, as_of: "YYYY-MM-DD"}` (backend is adding it in parallel; handle failure silently).
Goal: in the existing footer disclaimer area of static/index.html add a small muted line "الإصدار 0.5.0 · بيانات حتى <as_of>" fetched once at startup via the existing `api()` helper. Numbers in `ltr()`.
Own: static/index.html only. Done when: line visible in a Playwright screenshot, no console errors. Result (≤10 lines) below.
## Result
