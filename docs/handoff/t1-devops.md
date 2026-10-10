# t1 devops — CI
Goal: `.github/workflows/ci.yml` on push/PR: setup python 3.13, pip cache, install requirements*.txt, run `AS_OF=2026-10-09 python -m pytest -q`, `AS_OF=2026-10-09 python scripts/parity_check.py` (fail if output lacks "0 mismatches"), `python scripts/build_static.py`. Needs node for parity (setup-node 22).
Own: .github/ only. Done when: YAML valid (python -c yaml.safe_load) and commands verified locally. Result (≤10 lines) below.
## Result
- Added `.github/workflows/ci.yml`: push + PR, ubuntu-latest, Python 3.13 with pip cache (keyed on requirements*.txt), Node 22, `AS_OF=2026-10-09`.
- Steps: `pip install -r requirements-dev.txt`; `python -m pytest -q`; `python scripts/parity_check.py` tee'd to parity.log and gated by anchored regex `^[0-9]+ requests, 0 mismatches$` (so "10 mismatches" cannot pass); `python scripts/build_static.py`.
- Verified locally: YAML parses (7 steps). pytest 51 passed, 1 skipped. parity 211 requests, 0 mismatches. build_static wrote dist/ (gitignored).
- Not committed. Working tree also has other agents' edits (main.py, static/*, docs/handoff/t1-backend.md); CI run results on those are not verified here.
- Open: parity_check.py exits 0 even on mismatches, so the grep gate is the only failure signal. Consider a nonzero exit in parity_check.py (qa-owned).
- Open: no deploy job yet; Netlify deploy and Postgres plan not in scope.
- Rollback: `rm .github/workflows/ci.yml` (before commit); after commit, `git revert <sha>`.
