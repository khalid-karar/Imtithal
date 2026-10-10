# t1 devops — CI
Goal: `.github/workflows/ci.yml` on push/PR: setup python 3.13, pip cache, install requirements*.txt, run `AS_OF=2026-10-09 python -m pytest -q`, `AS_OF=2026-10-09 python scripts/parity_check.py` (fail if output lacks "0 mismatches"), `python scripts/build_static.py`. Needs node for parity (setup-node 22).
Own: .github/ only. Done when: YAML valid (python -c yaml.safe_load) and commands verified locally. Result (≤10 lines) below.
## Result
