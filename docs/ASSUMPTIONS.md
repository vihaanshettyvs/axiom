# ASSUMPTIONS.md - physics (P2)

**Everything here is a simplified prototype model, not an operational tool.** Numbers are
chosen to be plausible and explainable, and to keep `RealPhysics` behaviourally identical to
`MockPhysics` at nominal settings (a test enforces this over 180 minutes).

## Geometry and orbits (`space/orbits.py`)
- Ground track = straight segment A->B repeating every `period` min (config `SATELLITES`), a
  locally-linearised nadir track over the 100x100 km region. The in-region period is
  **time-compressed for the demo**; physical altitude is separate (`orbit["alt_km"]`, default 550 km)
  and is used only by drag/retirement models.
- Visible = footprint (sensor radius + slew) reaches the region. Ground contact = fraction of track in `CONTACT_S_RANGE`.

## Debris (`space/debris.py`)
- Events are scripted in `config.CONJUNCTIONS`, so BRAIN ON/OFF see the same world.
- `Pc = 0.5 * exp(-0.5 (miss/sigma)^2)`; miss distance is back-solved from the scripted Pc. Relative speed
  (7-14 km/s), size and covariance come from `make_rng(seed, "deb", debris_id)`.
- `risk = Pc * consequence`, consequence = importance * (0.5 + 0.5 health) * severity(speed, size).
- Dodge: along-track phasing shifts the miss by ~3 * dv * t; dv = 2.4 km / (3 (lead + 21 min)).
  Fuel from the rocket equation (200 kg, Isp 50 s), no fixed floor. Effectiveness = 1 - exp(-lead / 9 min).
  Parameters were calibrated so the cost curve stays within ~10% of the mock's over 0-90 min lead
  (0.26 kg at zero lead, ~0.05 kg at 90 min); cost falls and effectiveness rises with lead time.
  An earlier calibration was up to 43% above the mock at long lead and made brain-ON burn extra fuel.

## Collision Avoidance 2.0 (`debris.evaluate`, `RealPhysics.assess_conjunction`)
Exposes and checks numbers the model already had. Nothing here is a new orbit model.
- **TCA is scripted** (`config.CONJUNCTIONS`); it is reported as `time_to_tca_min` with `tca_source = "scripted"`, not predicted.
- **Predicted miss distance** is the one back-solved from the scripted likelihood above, so it restates that likelihood
  as a distance; it is not an independent measurement. `miss_sigma_ratio` = miss / sigma.
- **After the burn:** the along-track phasing shift (2.4 km x effectiveness) adds to the cross-track miss in quadrature,
  `miss_after = sqrt(miss^2 + shift^2)`. `miss_gain_km = miss_after - miss`.
- **Risk score / tier:** `risk_score = likelihood x consequence` (the existing `risk`). Tier: LOW < 0.005 <= MEDIUM < 0.02 <= HIGH
  (`RISK_TIER_MEDIUM`, `RISK_TIER_HIGH`). These are fixed, readable thresholds, not calibrated against anything. "NONE" = no conjunction.
- **Projected outcome** (`projected_outcome`, `projected_improved`): AVOIDED if `miss_after >= 3 sigma`; INEFFECTIVE if
  `miss_gain < 0.25 km`; otherwise REDUCED. `projected_improved = projected_outcome != INEFFECTIVE`. This is what the model says
  the burn *would* achieve. The 3 sigma and 0.25 km values are chosen conventions (`DODGE_SAFE_SIGMA`, `DODGE_MIN_GAIN_KM`).
- **Execution outcome** (`execution_outcome`) is separate and says whether the burn actually happened: `NOT_EXECUTED` (an
  assessment, nothing burned), `EXECUTED`, `FAILED_INSUFFICIENT_FUEL` or `FAILED_PROPULSION` (refused: no propellant spent, no
  route change, not counted as a dodge). **Never read `projected_outcome` as a result unless `execution_outcome == EXECUTED`,
  and even then it is still a model projection, not an observed avoidance.**
- **Feasibility:** infeasible if propulsion has failed or `fuel - cost < FUEL_RESERVE_KG` (`infeasible_reason`). When infeasible the
  projection is still computed so the operator can see what a funded burn would have done, but it is hypothetical: the record
  carries `projection_note = "HYPOTHETICAL projection only: ..."`. With failed propulsion the effectiveness is 0, so the projection
  is INEFFECTIVE (a dead thruster achieves nothing).
- **Brain ON:** keeps its utility rule and additionally skips a burn that is infeasible or projected INEFFECTIVE, and keeps the
  propellant needed for a riskier (higher `risk_score`) encounter of the same satellite that is still ahead.
  Brain OFF (fixed threshold) is unchanged. Mock physics has no `assess_conjunction`; the brain then uses the original rule.
- **Recording:** each `DODGE` / `DODGE_FAILED` event carries an optional `data` dict (risk tier, miss before/after, fuel used,
  `projected_outcome`, `projected_improved`, `execution_outcome`). A `DODGE` event has `execution_outcome = EXECUTED`; a
  `DODGE_FAILED` event has `FAILED_*` and a hypothetical projection. The brain's decision text says "(projected: ...)" because a
  decision is a plan. The engine runs `execute_dodge` before debiting fuel, and a burn P2 refuses (propulsion failed) spends no
  propellant and is not counted as a dodge.
- **Known inconsistency:** collisions in the engine are still resolved with `likelihood x (1 - effectiveness)`. The projected outcome
  label uses the miss-distance view. The two are different simplifications and can disagree on how good a late burn is.
  Neither is a validated collision probability.

## Degradation (`space/degradation.py`)
1. Battery - wear `degrade_rate * radiation(w) * dt` lowers both `health` and the separate `orbit["battery"]`
   (structural shocks hit health, not the battery).
2. Propulsion - `orbit["prop_ok"] = False` (scripted or `PROP_FAIL_PROB`): no dodges, no burns.
3. Communication - `orbit["comm_ok"] = False` (scripted or `COMM_FAIL_PROB`): no ground contact, no commands.
4. Sensor - `orbit["sensor_factor"]` cut (scripted or `SENSOR_GLITCH_PROB`).
- Also: fuel depletion (engine debits fuel; reserve 0.05 kg) and random structural shocks (`SHOCK_PROB`).
- Demo failure: `config.KNOWN_FAILURES = {"SAT-05": {"t": 60, "mode": "battery"}}`
  (modes: battery, sensor, communication, propulsion, structural) or `sat.orbit["known_failure"]`.
- Telemetry: `sat.orbit["telemetry"]` = fuel, battery, health, sensor performance, comm/propulsion flags,
  failure severity, active failures, 60-min failure probability.

## Manoeuvres and threats
- Route change: a timing (phase) shift and/or cross-track shift of the ground track, logged in
  `orbit["maneuvers"]`; planned ones are queued and applied by `step`. A dodge is a route change of
  `2.4 km x effectiveness` of along-track shift expressed as timing (~0.005 min), so coverage barely changes.
- Generated threats (`inject_threat`) have TCA 35-90 min ahead and Pc bands LOW 0.004-0.02, MEDIUM 0.03-0.08,
  HIGH 0.10-0.30. **All risk values are heuristics, not validated collision probabilities.**
- Dodge recommendation: dodge if `risk x effectiveness x 400 > fuel_cost x 60` and the burn is affordable.

## Space weather (`space/__init__.py`)
- Index `w` in [0,1], 0.5 nominal (all factors 1.0).
- Density factor `10**(2(w-0.5))` (x0.1 .. x10) on a log-interpolated mid-activity thermosphere table.
- Radiation factor `1 + (w-0.5)` on wear (storms age batteries/electronics faster).
- Decay: `da/dt = -rho B sqrt(mu a)` (+ tether term), integrated in 5 km steps to 120 km.
- Effect on the sim: `rul_min` (via wear and orbital life), the Last Breath urgency, and all Retirement Lab
  re-entry times. Set with `RealPhysics.set_space_weather(w)`.

## Last Breath (`space/lastbreath.py`)
- `rul = min(health / wear_rate, orbital_life)`. Point of no return = `rul - duration(cheapest affordable option) - 5 min`
  (0 if no option is affordable). RETIRE when `rul <= 30 * (2 - importance)` min or (no propellant and health < 0.5);
  WAIT when `rul <= 4x` that limit or health < 0.6; else SAVE. Every verdict carries a reason string.

## Retirement Lab (`space/retire.py`)
- Burn: perigee to 80 km; fuel scaled so nominal altitude = 0.30 kg (mock-compatible).
- Drag sail: +10 m^2, 3 kg, deploy p = 0.97 (0.5 + 0.5 health).
- Tether: 3 km, `F = I L B`, `I = 1 A (0.7 + 0.6 w)`, B = 30 uT, deploy p = 0.85 (0.5 + 0.5 health), needs health >= 0.15.
- Effectiveness = deploy p x (1 if re-entry <= 25 yr else 0.4). Risk = deployment failure + exposure time.

## Tug (`space/tug.py`)
- One tug, `eta_min` travel, cool-down, one satellite at a time. Operations chosen from need:
  REFUEL if fuel < 95% capacity, REPAIR if health < 0.97 or a fault is open, REBOOST if the orbit is
  below 500 km (or `needs_reboost`), else INSPECT. REFUEL+REPAIR = `service_min`; others 0.4-0.8 of it.
- The tug has its own propellant (1.5 kg): INSPECT 0.05, REFUEL 0.30, REPAIR 0.25, REBOOST 0.20 kg per
  operation; a request is refused when it is exhausted.

## Comm loss and retirement
- A satellite without a command link cannot perform a burn: `retirement_options` returns `[]` and the lab marks
  the burn infeasible. Drag sail and tether are assumed to deploy from a pre-set autonomous timer
  (success probability x0.6). Its future usefulness is cut to 10% (data cannot reach the ground).
- `tug_rank` (not part of the engine API) orders competing requests: `0.6 urgency + 0.4 value - 0.002 travel`.
