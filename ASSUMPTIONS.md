# ASSUMPTIONS.md

Everything below is a deliberate simplification. Defend them as "scoped for a 9-hour prototype", not as physics claims.

**World**
* 100×100 km flat region; "orbits" are straight ground tracks that cross it every 110–130 min (scaled-down passes, not real LEO speeds). Real orbital mechanics is P2's job; `mocks.MockPhysics` only stands in until it is plugged in.
* Two wildfires (one ignites at t=0, one at t=25) + two towns at risk. Plume = drifting, slowly turning wind + gusts, logistic intensity growth, expanding radius.
* A hidden moving cloud band blinds optical sensors (satellites fully, HAPS 20 %, drone 0 %). The sensor reports its own cloud-mask estimate (`Observation.visibility`, noisy) — the estimator never sees the true cloud.

**Sensors** — P(detect)=quality × edge × intensity-term × (1−cloud); Gaussian position noise (grows as health falls); false positives with prob `fp_rate` per scan at a random place in the footprint. Specs in `config.SENSOR_SPECS`.

**Estimator** — grid PHD-style filter (expected hazards per cell ≈ P(hazard centre in cell)). Assumes: ≤1 hazard centre per ~cell, known sensor noise, 2× pessimistic clutter (`LH_CLUTTER_MULT`), 85 % trust in negative scans, hazards drift ≤0.15 km/min.

**Communications** — satellites buffer scans and can downlink only in ground contact (150 MB/min). BRAIN OFF sends raw FIFO (20 MB/scan); BRAIN ON sends compressed detections/summaries (0.1–0.5 MB), drops redundant empty scans, and relays urgent detections over a crosslink to a satellite whose contact comes sooner (store-and-forward `HANDOFF`). HAPS/drone links are direct. The belief is updated **only when data is delivered** → latency is real.

**Satellite life** — linear health decay + random shocks; RUL = health / expected decay rate; health ≤0.02 ⇒ uncontrolled DEAD (debris). Retirement = fuel-costed de-orbit. One servicing tug (25 min ETA, 15 min dock, +1 kg fuel, +0.35 health, 60 min cool-down); sat unavailable while docked. Re-pointing ("slew") costs 0.0004 kg/km only when tasking changes.

**Debris** — scripted conjunctions (`config.CONJUNCTIONS`); instantaneous risk = p·exp(−((t−tca)/12)²). BRAIN ON sees a 90-min forecast; BRAIN OFF reacts when instantaneous risk ≥ 1 % (late ⇒ higher fuel, lower effectiveness). Dodge fuel falls and effectiveness rises with lead time. Collision outcome is a seeded Bernoulli on the *residual* probability; `expected_sat_loss` (Σ residual p) is the smoother metric to quote. Brain ON deliberately *accepts* trivial risks (e.g. 0.4 %) — fuel is worth more.

**Utility ledger** (`config.py`) — one scale for all actions: info value 40/unit, fuel 60/kg, bandwidth 0.05/MB, loss 400, uncontrolled death 150, servicing 120, tug cost 25. These weights are tunable judgement calls, not measured.

**Brain OFF** — nadir-only sensors always on, raw FIFO downlink, per-satellite threshold dodging, HAPS lawnmower, no retirement/servicing/drone/handoff. It still runs the *same* estimator on whatever data arrives, so the comparison isolates decision-making.

**Metrics honesty** — localisation error is capped at 25 km when no estimate exists; "attention alerts" = items a human must read (BRAIN OFF: every raw detection incl. false ones; BRAIN ON: new confirmed hazards, confirmations, failures). Results vary by seed; BRAIN ON wins on seeds 42/7/123 but the margins differ (see README).

**Known limitations** — the brain can chase ghosts (a coincident pair of false positives raises a false track until a HAPS pass clears it); the estimator has no explicit wind model; one tug, one HAPS, one drone; the drone follows the estimate rather than planning a perimeter.

**v1.1 additions** — 12 satellites. Methane leaks are near-stationary sources with fluctuating emission; the methane channel is less sensitive (Pd x0.7) and less precise (sigma x1.4) than the fire channel, and has its own estimator grid (slower diffusion/relaxation). 25 % of false positives are reported as methane. **Real wildfire data:** no real FIRMS file ships with the repo (needs an API key + network, unavailable here). `scenario_data.load_firms_csv` converts a FIRMS CSV (region centred on the median detection; clusters ≤8 km merged; ≤3 fires; start time = minutes since earliest detection; intensity from FRP; wind is a default, not measured). The test uses a synthetic FIRMS-format fixture. Localisation error is capped at 25 km per hazard (previously uncapped when a far-off estimate existed, which overstated error). Fault isolation swaps a failed module for its mock mid-run; state held by the failed module (e.g. belief) is lost at the swap.
