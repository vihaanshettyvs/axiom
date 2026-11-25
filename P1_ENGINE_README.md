# ORBITAL TRIAGE — intelligence & simulation engine (owner: P1)

```bash
python engine.py --mode both --seed 42        # runs ON + OFF, prints table, writes out/*.json
python engine.py --mode on --mock-all         # frontend dev: every module mocked
python -m pytest -q                           # 59 tests (~50 s)
python -c "from brain.haps import compare_planners as c; print(c())"   # HAPS adaptive vs lawnmower
```
Files: `contracts.py config.py engine.py mocks.py brain/{plume,leakhunter,haps,triage}.py`, docs `CONTRACTS.md ASSUMPTIONS.md ALGORITHMS.md`, samples `out/runlog_brain_{on,off}.json`, `out/sample_runlog.json` (small), `out/mock/*` (all-mock), `out/comparison.json`.
Switch mock/real per module in `config.USE_REAL`. Needs only Python 3 + numpy (pytest for tests).

See `ENGINE.md` for the call sequence and teammate interfaces, `CONTRACTS.md` for fields, `docs/ASSUMPTIONS.md` for the physics assumptions.
