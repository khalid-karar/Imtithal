# t1 frontend — show version in footer
Contract: `GET /api/version` -> `{version: string, as_of: "YYYY-MM-DD"}` (backend is adding it in parallel; handle failure silently).
Goal: in the existing footer disclaimer area of static/index.html add a small muted line "الإصدار 0.5.0 · بيانات حتى <as_of>" fetched once at startup via the existing `api()` helper. Numbers in `ltr()`.
Own: static/index.html only. Done when: line visible in a Playwright screenshot, no console errors. Result (≤10 lines) below.
## Result

Added #verLine under .foot in static/index.html; fetched once at startup via api("/api/version") (silent catch), text "الإصدار 0.5.0 · بيانات حتى 2026-10-09" with ltr(). Verified with uvicorn :8765 + Playwright: line renders, console errors only the Google Fonts tunnel failure. Server killed. Not committed. No open issues.
