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
- Dodge: along-track phasing shifts the miss by ~3 * dv * t; dv = 2 km / (3 (lead + 12 min)).
  Fuel = 0.04 kg + rocket equation (140 kg, Isp 60 s). Effectiveness = 1 - exp(-lead / 9 min).
  Both calibrated so cost falls and effectiveness rises with lead time (the ON/OFF story).

## Degradation (`space/degradation.py`)
1. Fuel - spent by the engine; propulsion-limited below 0.05 kg.
2. Battery/wear - `health -= degrade_rate * radiation(w) * dt`.
3. Sensor - optional glitch (`config.SENSOR_GLITCH_PROB`, default 0 = off) and scripted failure.
4. Structural/propulsion - random shocks (`SHOCK_PROB`) and scripted failure.
- Demo failure: `config.KNOWN_FAILURES = {"SAT-05": {"t": 60, "mode": "battery"}}`
  (modes: battery, sensor, structural, propulsion) or `sat.orbit["known_failure"]`.

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
  REFUEL if fuel < 95% capacity, REPAIR if health < 0.97 or a fault is open, else INSPECT.
  REFUEL+REPAIR = `service_min`; others are 0.4-0.8 of it. REBOOST is modelled in `OP_TIME` only.
- `tug_rank` (not part of the engine API) orders competing requests: `0.6 urgency + 0.4 value - 0.002 travel`.
