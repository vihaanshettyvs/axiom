# ENGINE.md — how engine.py calls every module, and what each teammate must provide

## One simulated minute (engine.step)
| # | Engine does | Calls | Owner |
|---|---|---|---|
| 0 | (once) build scenario | `scenario_data.build_hazard_specs()` → `config.HAZARD_SOURCE` → FIRMS CSV (`config.WILDFIRE_DATA_PATH`) → synthetic `config.HAZARDS` | P1 / P4 |
| 1 | orbits, degradation, servicing, coverage, debris risk | `physics.step(sats, t, dt)` | **P2** |
| 1 | hazards move (wildfire + methane) | `plume.step(t, dt)` | P1 (hazard data: P4 via HAZARD_SOURCE) |
| 2 | estimator ages its belief | `lh.predict(dt)` | P1 |
| 2 | each tasked/in-view sensor scans | `plume.observe(sensor, aim, t, obs_id)` → `Observation` | P1 |
| 3 | HAPS/drone scans reach the estimator at once | `lh.update(obs, t)` | P1 |
| 4 | conjunction forecast for the brain | `physics.upcoming_conjunctions(sat, t, 90)` | **P2** |
| 5 | brain decides | `triage.decide(WorldView) -> [Decision]` | P1 |
| 6 | apply: OBSERVE sets aim; DOWNLINK/HANDOFF move buffered scans (then `lh.update`); DODGE `physics.dodge_*`; RETIRE `physics.retirement_options`; TUG `physics.request_tug`; DISPATCH_* set HAPS/drone targets | physics API | P1 + **P2** |
| 7 | collisions at tca | `physics.upcoming_conjunctions(sat, t, 1)` | **P2** |
| 8 | beliefs, estimates, metrics → Frame | `lh.grid()/grids()/estimates()/entropy_bits()/uncertainty()` | P1 |
| 8 | optional hooks | `extension.on_step(frame)` | **P4** (optional) |
Start of run: `extension.on_reset(meta)`. End: `extension.on_end(summary)`.
The brain sees only `WorldView` (estimates, belief grid, platform states, conjunction forecasts, buffers) — **never ground truth**.

## Fault isolation (engine.py `Guarded`)
Every module is wrapped. If it fails to import/construct, or raises inside any call, the engine swaps in the mock, writes a `MODULE_FALLBACK` event to that frame and carries on. Extensions that fail are disabled (`EXTENSION_DISABLED`). Bad decisions are skipped (`ACTION_FAILED`). Missing data files fall back (`DATA_FALLBACK`). If even a mock fails the run ends cleanly with `meta.completed = false` and `meta.error`. `meta.modules` shows `real | mock | fallback` for each module.

## Interfaces teammates must follow (full types in `contracts.py`)
**P2 physics** — class `RealPhysics` at `config.PHYSICS_REAL_PATH`: `reset, step, coverage_windows, upcoming_conjunctions, dodge_fuel_cost, dodge_effectiveness, retirement_options, tug_status, request_tug` (see CONTRACTS.md). Optional: `set_space_weather(w)`, `retirement_lab(sat,t)`. Done and integrated.

**P3 frontend** — read RunLog JSON only (`out/runlog_brain_{on,off}.json`, 12 sats, hazards of kind `wildfire` and `methane`). Per frame: `satellites, hazards(truth), observations, decisions(+reason), estimates(kind), belief_permille (combined 50x50), belief_by_kind{wildfire,methane}, events, metrics`. `scenario.retirement_lab` for the slider/lab; `meta.modules/hazard_source/completed` for a status badge. Typed loading in Python: `RunLog.read(path)`.

**P4** (role not stated in my brief, so two OPTIONAL plug-in points; ignore either you don't need):
1. *Hazard data*: `config.HAZARD_SOURCE = "yourmodule:build_hazards"`; function takes no args and returns a list of dicts: `id, kind("wildfire"|"methane"), pos(x,y km), t_start(min), radius0, rmax, expansion, wind(vx,vy km/min), wind_turn, int0(0-1), int_rate`. Or just drop a NASA FIRMS CSV and set `config.WILDFIRE_DATA_PATH`. Do not re-implement plume/estimator/physics.
2. *Telemetry / any observer*: `config.EXTENSIONS = {"telemetry": "yourmodule:Telemetry"}`; class with no-arg constructor and optional `on_reset(meta)`, `on_step(frame: Frame)`, `on_end(summary: dict)`. Read-only; must not mutate frames.

**P5 benchmark/deck** — `engine.compare(seed, duration, out_dir)` → metrics table; `RunLog.summary` per run; `python engine.py --mode both --seed N --duration M`. Results across seeds: see README.

## Run
```
python engine.py --mode both --seed 42 --duration 180      # ON vs OFF + out/*.json
python engine.py --mode on --duration 60 --mock-all        # every module mocked
python -m pytest -q                                         # 59 tests
```
