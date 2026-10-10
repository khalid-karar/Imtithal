# t1 qa — verify t1 backend+frontend+devops
Add tests for GET /api/version (tests/test_wow.py) and add the request to scripts/parity_check.py. Then run full gate on this branch: pytest, parity, build_static, one Playwright look at the footer. Verdict PASS/FAIL first line. Result below.
## Result
PASS (no blockers)
- parity_check.py already exits 1 when mismatches>0 (line 162); verified, no logic change needed. Added GET /api/version to its request list.
- tests/test_wow.py: added test_version_endpoint (shape, string version, as_of=2026-10-09). `AS_OF=2026-10-09 pytest -q`: 52 passed, 1 skipped.
- `AS_OF=2026-10-09 python scripts/parity_check.py`: 212 requests, 0 mismatches, exit 0.
- `AS_OF=2026-10-09 python scripts/build_static.py`: OK, as_of=2026-10-09. Playwright at 390px on dist/ and uvicorn: #verLine reads "الإصدار 0.5.0 · بيانات حتى 2026-10-09", no horizontal scroll, no console errors except Google Fonts blocked by the sandbox proxy.
- Non-blocking: version "0.5.0" is hardcoded in main.py and demo-api.js (drift risk; parity now guards the value).
- Non-blocking: build_static.py without AS_OF defaults to the real date, so a local build without AS_OF shows 2026-10-10. CI sets AS_OF, so no CI impact.
- Not committed. Product code untouched.
