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

## v1.1.1 additions
- A satellite that DODGEs or RETIREs in a minute does not also receive an OBSERVE decision in that minute (it burns, it does not re-point). Found by P2's audit rules; seed-42 numbers moved (ON detect 79.5, localize 83.5, loc err 14.0 km, fuel 0.95 kg).
- Known weakness: methane (weak-signal) leaks are confirmed late and seed-dependently (seed 42: t=148, seed 2: never within 180 min). Not tuned yet.

## v1.2 additions (demo validation)
Simplifications that remain, stated plainly:
- **FIRMS:** the NASA FIRMS loader exists (`scenario_data.py`) but this build has NO real FIRMS file. Every hazard in the shipped RunLogs is `source: "SIMULATED"` (`scenario.hazards[].source`, `meta.hazard_source = "synthetic"`). P4's `data/fires.csv` and `sensing/*` are not connected (not available to P1 when this was built).
- **Methane** hazards are always simulated (no real methane data source). Landfill leak = `LEAK-1` at (55, 42) km, placed where the constellation has regular coverage; at the original northern placement (62, 82) leaks were found in only 2 of 5 test seeds.
- **Debris:** scripted conjunctions (`config.CONJUNCTIONS`), not derived from positions. The debris that threatens the leak observer (SAT-09, DEB-7710, TCA 158) was placed by the scenario author; the brain acts on a 90-min forecast, so the dodge happens ~89 min before closest approach.
- **Retirement:** a drag sail or tether takes days to deorbit; the sim marks the satellite RETIRED after the method's `duration_min` (the burn / deployment), not after re-entry.
- **Drone** battery is `fuel_kg` (minutes-equivalent); it is clamped at 0 and the drone goes idle.
- **Brain tuning added in v1.2** (all identical for ON and OFF scenarios): diminishing returns for several satellites on one hazard (`REPEAT_LOOK_DECAY`), extra urgency for coin-flip tracks (`URGENCY_CONFIRM_W`), no OBSERVE while a satellite burns, retirement method chosen by fuel/risk/time score, best tug bidder wins and the others queue.
- Methane detection is still seed-dependent (not found in 180 min on 1 of 8 test seeds).

## v1.3 -- P4 modules (what is and is not connected)
- **Connected, executed and tested:** `sensing/fire.py` (FIRMS reader, used by `scenario_data.py` when `config.WILDFIRE_DATA_PATH` is set; falls back to a lenient reader if the CSV lacks P4's required columns; `scenario_data.FIRMS_READER_USED` says which), `sensing/insight.py` + `sensing/hazardvalue.py` + `sensing/report.py` + `sensing/runlog.py` (run on every ON/OFF pair by `engine.py --mode both`, written to `p4_report.json`).
- **Not called by the engine:** `sensing/telemetry.py`. P2's physics already writes `satellites[].orbit.telemetry` (battery, health, comm_ok...), so calling P4's would create a second, conflicting health model. It is tested standalone only.
- **Not implemented by P4:** `sensing/poserror.py`.
- **No real FIRMS data is in this build:** P4's `data/firms/sample_viirs_snpp.csv` has not been supplied to P1, so the shipped RunLogs are SIMULATED. Tests use a clearly-labelled synthetic fixture. Set `config.WILDFIRE_DATA_PATH` to the real CSV to switch.
- `sensing/report.py` labels the project "ORBITA" (cosmetic).

## v1.4 -- P5 modules
- **Used:** `eval/credits.py` (credits formula) and `eval/seeds.py`, unchanged. New `eval/real_benchmark.py` runs the REAL engine (ON/OFF, same seeds) and scores it with P5's credits formula -> `eval/benchmark_results_real.csv`, `eval/benchmark_real.png`.
- **Not used (incompatible, and one fabricates data):** P5's `eval/benchmark.py` falls back to `_mock()`, which draws random numbers with the Brain-ON advantage built in (leak 12-28 vs 45-85 min, etc.), because it calls `engine.run_simulation` and `config.USE_REAL["brain"]`, which do not exist. Its `benchmark_results.csv` and `final_charts.py` (hardcoded 12 vs 0 dead, 104 vs 24.5 min, 0.76 vs 0.69 kg) are therefore NOT measurements and must not appear in the deck. `eval/metrics.py` reads fields (`time_min`, `leak_localized`, `bytes_sent`, `fuel`) that the RunLog does not have, and `baseline/policies_off.py` returns decisions in a format that does not match `contracts.Decision`/`ActionType`; the engine's own BaselinePolicy remains the OFF policy.

## v1.5 -- FIRMS region selection
- The P4 file (`sample_viirs_snpp_071223.csv`, 74,605 VIIRS S-NPP detections, one day: 2023-07-12, GLOBAL) cannot be centred on its median. `scenario_data.select_dense_region` picks the densest 100x100 km window (1-degree bins, then the best candidate centre by detections within +-50 km; deterministic). Override with `config.FIRMS_REGION=(lat, lon)`. The chosen centre is written to `scenario.hazard_source_note`.
- Up to 3 wildfires are made from the strongest clusters (by FRP) inside that window; their start times are minutes after the first detection in the window, capped at 90 min (the real detections are spread over a day; the sim is 180 min).
- Real data is only the wildfire positions/strength/timing. The spread dynamics, sensors, methane leaks, debris and satellites remain simulated.
- Credit: "NASA FIRMS VIIRS S-NPP historical sample data (sample_viirs_snpp_071223.csv)". Download date not recorded by P4.
