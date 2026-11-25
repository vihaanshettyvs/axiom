# CONTRACTS.md — ORBITAL TRIAGE shared contracts (v1.0.0, FROZEN after hour 1)

Source of truth: `contracts.py`. **Do not change a field without telling the team first.** Additive, defaulted fields are the only change that does not break anyone.

## Conventions
| Thing | Rule |
|---|---|
| Time | minutes (float), sim starts at `t=0`, step 1 min |
| Position | km, local 2D frame, origin = SW corner of the 100×100 km region, x east, y north |
| Probability grid | 50×50, `grid[iy][ix]`, cell = 2 km, cell centre `((ix+.5)*2, (iy+.5)*2)` |
| Randomness | `make_rng(seed, *keys)` only. Streams keyed by (sensor, minute) so BRAIN ON/OFF see the same world |
| Frontend | reads **only** the RunLog JSON. Never imports physics/brain |

## Classes
### Satellite (also used for HAPS / DRONE / TUG via `kind`)
`id, kind("SAT"|"HAPS"|"DRONE"|"TUG"), pos, vel(km/min), status, fuel_kg, fuel_capacity_kg, health(0-1), sensor_confidence(nominal Pd, health-adjusted), sensor_radius_km(footprint), slew_km(max re-pointing from nadir), sigma_km(position noise), fp_rate(false positive per scan), cloud_sensitivity(0-1), rul_min, mission_importance(0-1), debris_risk(instant collision prob), in_view, in_contact, view_left_min, next_view_min, next_contact_min, buffer_mb, aim, target, orbit{}`
`orbit` is **physics-private** (P2 may store anything JSON-able). Mock keys: `A,B,period,phase,degrade_rate,base_conf,tug_arrival_t,tug_done_t,retire_done_t,serviced`.
`status` ∈ ACTIVE, DEGRADED(<0.5 health), SERVICING, RETIRING, RETIRED(graceful), DEAD(uncontrolled → debris), LOST(collision), IDLE.

### Hazard — ground truth wildfire (never given to the brain)
`id, kind, pos, vel, radius_km, intensity(0-1), t_start, active`

### Detection / Observation — one scan; empty `detections` = negative scan
`Observation: id, t, sensor_id, source, aim, radius_km, detections[], sigma_km, pd_nominal, fp_rate, size_raw_mb, size_comp_mb, visibility(sensor's own clear-sky estimate), delivered_t`
`Detection: pos, intensity, is_false_positive(truth flag), hazard_id(truth flag)` — truth flags are for metrics/debug only; LeakHunter ignores them.

### Action / Decision
`Action: type(ActionType), actor_id, target, target_id, params{}, fuel_cost(kg), bandwidth_cost(MB)`
`ActionType`: OBSERVE, DOWNLINK, HANDOFF, DODGE, RETIRE, DISPATCH_HAPS, DISPATCH_DRONE, REQUEST_TUG
`Decision: t, action, urgency, importance, info_gain, fuel_cost, bandwidth_cost, risk_reduction, health, expected_benefit, reason(str), alternatives[]`
Action params: OBSERVE→`target`=aim point; DOWNLINK→`item_ids, compress, drop_ids`; HANDOFF→`item_ids, dst`; DODGE→`target_id`=debris id, `lead, eff`; RETIRE→`name, fuel_kg, duration_min`; DISPATCH_*→`target`=waypoint.

### Estimate — what the brain believes
`id, pos, existence(0-1), confidence, uncertainty_km, intensity_est, growth_est(per 10 min), confirmed(drone), last_obs_t, n_pos`

### RunLog (what the frontend replays)
```
RunLog { meta{contract_version, mode:"BRAIN_ON"|"BRAIN_OFF", seed, duration_min, step_min, grid_n, cell_km, area_km, use_real},
         scenario{assets[], satellites[{id,A,B,period,phase}], hazard_ids, haps_start, drone_base, sensor_specs, conjunctions[]},
         frames[Frame], summary{...} }
Frame  { t, satellites[], hazards[](truth), observations[], decisions[], estimates[],
         belief_permille[50][50] (int, prob*1000), entropy_bits, uncertainty(0-1), events[{t,type,actor,msg}],
         metrics{fuel_used_kg, bandwidth_mb, alerts, sats_lost, uncontrolled_dead, retired, serviced,
                 expected_sat_loss, dodges, loc_error_km, observations, downlinked_scans, dropped_scans} (cumulative) }
```
Event types: ALERT, CONFIRMED, DODGE, DODGE_FAILED, HANDOFF(throttled), RETIRE, RETIRED, DEAD, COLLISION, TUG_REQUEST, SERVICING, SERVICED, DISPATCH_HAPS, DISPATCH_DRONE, DRONE_DONE.

## Interfaces (mock and real must match) — `PhysicsAPI` is P2's
```python
reset(seed, sats) -> sats
step(sats, t, dt) -> sats            # propagate, degrade, finish servicing, refresh derived fields (see Satellite)
coverage_windows(sat, t, horizon_min) -> [(t_start, t_end)]
upcoming_conjunctions(sat, t, horizon_min) -> [Conjunction(sat_id, debris_id, tca, probability)]   # t <= tca < t+horizon
dodge_fuel_cost(sat, lead_min) -> kg          # must DECREASE with lead time
dodge_effectiveness(sat, lead_min) -> 0..1    # must INCREASE with lead time
retirement_options(sat, t) -> [{"name","fuel_kg","duration_min"}]   # [] if not enough fuel
tug_status(t) -> {"available","eta_min","service_min"}
request_tug(sat, t) -> {"accepted","arrival_t","complete_t"}        # physics owns the servicing timeline & status changes
```
Engine selects the implementation with `config.USE_REAL["physics"]` and `config.PHYSICS_REAL_PATH = "physics.api:RealPhysics"`.
Engine-side derived data P2 must keep up to date in `step()`: `pos, vel, health, sensor_confidence, rul_min, status, debris_risk, in_view, in_contact, view_left_min, next_view_min, next_contact_min`.
Also `PlumeAPI`, `LeakHunterAPI`, `TriageAPI` Protocols in `contracts.py`.

## Change log
* 1.0.0 — initial. (`Observation.visibility` was added during hour 1, before freeze.)
* 1.1.0 — ADDITIVE ONLY, defaulted: `Detection.kind`, `Estimate.kind` ("wildfire"|"methane", default "wildfire"), `Frame.belief_by_kind` (per-kind 50x50 permille grids; `belief_permille` stays the combined grid), `RunLog.from_dict/read/load_dict`. New event types: MODULE_FALLBACK, DATA_FALLBACK, EXTENSION_DISABLED, ACTION_FAILED, SPACE_WEATHER. New meta keys: hazard_source, n_satellites, modules, extensions, completed, error, warnings. Nothing renamed or removed.
