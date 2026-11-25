# Example outputs (real output of the code)

Run the standalone simulation: `python -m space.demo` (12 satellites, 240 min; `--seed`, `--minutes`, `--weather`, `--n`).
Tests: `python -m pytest -q space/tests`.

## Standalone demo (first 130 min, seed 42)
```
t=    0  THREAT HIGH: DEB-T00-9475 -> SAT-02, TCA t=69, likelihood 0.182
t=    0  THREAT MEDIUM: DEB-T01-9895 -> SAT-05, TCA t=41, likelihood 0.044
t=    0  THREAT LOW: DEB-T02-4370 -> SAT-08, TCA t=69, likelihood 0.004
t=    1  DODGE SAT-02 vs DEB-T00-9475: risk 0.038 (likelihood 0.182 x consequence 0.21), burn 68 min before TCA costs 0.061 kg and removes 100%; benefit 15.0 vs cost 3.7  -> done
t=    1  HOLD SAT-05 vs DEB-T01-9895: risk 0.012 (...), burn 40 min before TCA costs 0.089 kg and removes 99%; benefit 4.7 vs cost 5.3
t=    1  HOLD SAT-08 vs DEB-T02-4370: risk 0.001 (...); benefit 0.5 vs cost 3.7
t=    1  TUG SAT-09 REPAIR first (urgency 0.70, mission value 0.75); deferred: SAT-11, SAT-03. -> accepted ['REFUEL', 'REPAIR']
t=   41  SERVICED SAT-09: fuel 2.00 kg, health 0.45
t=   50  FAILURE SAT-04: communication (severity 0.35)
t=   50  RETIRE SAT-04: no command link, so only passive disposal is possible, ... failures (communication) leave little future usefulness (0.03).
t=   50  RETIRE SAT-04: no propellant/propulsion; passive option edt_tether (re-entry 4 d)
t=   70  FAILURE SAT-07: propulsion (severity 0.50)
```

## Debris risk (`conjunction_reports`)
```json
{"debris_id": "DEB-3341", "sat_id": "SAT-04", "relative_speed_kms": 7.79, "closest_approach_km": 1.03,
 "time_to_closest_approach_min": 120.0, "collision_probability": 0.15, "consequence": 0.221, "risk": 0.0331,
 "disclaimer": "HEURISTIC risk score ... not a validated orbital collision probability ..."}
```

## Telemetry (`sat.orbit["telemetry"]`)
```json
{"fuel_kg": 1.5, "fuel_frac": 0.75, "battery": 0.95, "health": 0.95, "sensor_performance": 1.0,
 "sensor_confidence": 0.782, "comm_ok": true, "propulsion_ok": true, "failure_severity": 0.0,
 "active_failures": [], "failure_prob_60m": 0.033}
```

## Retirement Lab and space weather (SAT-05)
| Weather | Remaining life | Drag-sail re-entry | Tether re-entry | Do nothing |
|---|---|---|---|---|
| 0.0 (quiet) | 207 min | 3076 d | 6.7 d | 33175 d |
| 0.5 (nominal) | 107 min | 308 d | 4.3 d | 3318 d |
| 1.0 (storm) | 72 min | 31 d | 2.8 d | 332 d |

The controlled burn re-enters in ~0.1 d at every setting (perigee already in dense air), costs 0.30 kg.
