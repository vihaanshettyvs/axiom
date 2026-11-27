# What P1's engine.py must call (RealPhysics)

Import: `config.PHYSICS_REAL_PATH = "physics.api:RealPhysics"`, `config.USE_REAL["physics"] = True`.
`physics = RealPhysics()`; times in minutes, positions km. All outputs are plain dicts / contract classes.

## Required (PhysicsAPI, unchanged, already integrated)
| Call | When | Returns |
|---|---|---|
| `reset(seed, sats)` | start of each run | sats with derived fields filled at t=0 |
| `step(sats, t, dt)` | once per minute | sats (pos, vel, health, sensor_confidence, rul_min, status, debris_risk, in_view, in_contact, view_left/next_view/next_contact_min) |
| `coverage_windows(sat, t, horizon)` | planning | `[(t_start, t_end)]` |
| `upcoming_conjunctions(sat, t, horizon)` | each step | `[Conjunction]`, identical on every call for a seed |
| `dodge_fuel_cost(sat, lead)` / `dodge_effectiveness(sat, lead)` | when deciding/executing a dodge | kg / 0..1 (cost falls, effectiveness rises with lead) |
| `retirement_options(sat, t)` | when retiring | `[{name, fuel_kg, duration_min}]`, `[]` if no fuel, no propulsion or no command link |
| `tug_status(t)` / `request_tug(sat, t)` | tug logic | `{available, eta_min, service_min, free_at, fuel_kg}` / `{accepted, arrival_t, complete_t, ops, tug_fuel_cost_kg}` |

Engine duties (unchanged): set `RETIRING` + `orbit["retire_done_t"]`, set `LOST`, debit fuel for DODGE/retire actions.

## Optional extras (read-only for the brain / RunLog)
| Call | Use |
|---|---|
| `set_space_weather(w)` | 0..1, 0.5 nominal; recomputes life, re-entry, urgency from the next step |
| `retirement_lab(sat, t)` | burn / drag sail / tether / do-nothing comparison rows |
| `recommend_dodge(sat, t)` | per-threat risk, dodge yes/no, fuel cost, reason (heuristic) |
| `conjunction_reports(sat, t)` | Pc, closest approach, relative speed, consequence, risk |
| `debris_state(sat, t)` | relative range / closing speed to each threat |
| `observation_opportunities(sats, target_xy, t, horizon)` | who can see a point, when |
| `tug_rank(requests)` | competing requests -> chosen + reason |
| `sat.orbit["last_breath"]`, `sat.orbit["telemetry"]` | verdict + reason, RUL, point of no return, predicted re-entry, severity; fuel/battery/health/sensor/comm/propulsion telemetry |

## Scenario / standalone helpers (NOT called by the engine)
`inject_threat(sat, t, level)`, `execute_dodge(sat, t, debris_id, debit_fuel=False)` (route change + log; the
engine already debits fuel), `plan_route_change(sat, t_exec, dphase_min, dcross_km)`,
`space.orbits.make_constellation(n, seed)` (10-12 sat specs), `python -m space.demo`.

## Optional config keys
`SPACE_WEATHER`, `KNOWN_FAILURES = {"SAT-05": {"t": 60, "mode": "battery|sensor|communication|propulsion|structural"}}`,
`SENSOR_GLITCH_PROB`, `COMM_FAIL_PROB`, `PROP_FAIL_PROB` (all default off, so mock parity is unchanged).
