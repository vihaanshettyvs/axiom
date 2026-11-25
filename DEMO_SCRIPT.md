# Demo sequence (seed 2, Brain ON; `out/demo/runlog_brain_on.json`, backup: seed 7 in `out/backup/`)

All hazards in this log are SIMULATED (no real NASA FIRMS data). Times are minutes.

| t | What happens | Where it is in the log |
|---|---|---|
| 0 | Four emergencies are live or imminent: wildfire East (from t=0), landfill methane leak (starts t=10, hidden), a dying satellite (SAT-05, health 0.42), two low-fuel satellites (SAT-03, SAT-10) and 8 debris threats. | `scenario` |
| 0 | SAT-03 and SAT-10 both qualify for the single servicing tug. The brain ranks them and SAT-03 wins; the reason names the rival. Brain also dodges 3 threats early, when a dodge is cheapest. | events TUG_REQUEST, DODGE |
| 22-24 | Satellites get uncertain observations of the leak; LeakHunter's 50x50 grid (`belief_by_kind.methane`) concentrates and the leak is confirmed at ~(58,43). HAPS waypoints follow belief and uncertainty (DISPATCH_HAPS reasons). | observations, estimates, decisions |
| 24-35 | Drone is dispatched at t=24 (to the eastern wildfire, the first thing it can verify); a drone observation also confirms the leak track at t=35. | DISPATCH_DRONE, CONFIRMED |
| 25-40 | Tug docks with SAT-03 and services it (fuel 0.35 -> 1.30 kg). | SERVICING, SERVICED |
| 63 | SAT-05 degrades. Last Breath verdict goes WAIT -> RETIRE; the brain compares controlled deorbit, drag sail and EDT tether and picks the lowest fuel/risk/time cost. | RETIRE event (full comparison in the reason) |
| 69-72 | Debris approaches SAT-09, which is watching the leak. SAT-09 dodges (fuel debited, route shifted); SAT-03 takes over the leak watch. | DODGE, REASSIGN |
| 100 | Tug is free again (cooldown); SAT-10, which queued behind SAT-03, is served at t=125-140. | TUG_REQUEST, SERVICING, SERVICED |
| 114 | Drone is dispatched to the leak once the localization threshold is met. | DISPATCH_DRONE |
| all | Fuel, bandwidth (MB), battery, health and the decision reasons are updated each minute and recorded. | `frames[].metrics`, `satellites[].orbit.telemetry` |

Brain ON vs OFF on the same seed is in `out/demo/comparison.json`; all seeds are in `out/validation.json`
(`python validate_demo.py`). The OFF run lets SAT-05 die uncontrolled and sends raw data.

## Note on ids
The brain numbers its own tracks (`EST-xx` for wildfires, `LEAK-xx` for methane) in the order it finds them. They are NOT the hazard ids in `scenario.hazards` (`FIRE-E`, `FIRE-W`, `LEAK-1`, `LEAK-2`). Match them by position: the landfill leak `LEAK-1` is at (55, 42) km, so any `LEAK-xx` estimate near there is the landfill leak.

# Backup sequence (seed 7; `out/backup/runlog_brain_on.json`)

Same scenario, luckier start: a satellite is overhead when the leak begins, so the leak is found almost at once. All hazards SIMULATED.

| t | What happens | Log |
|---|---|---|
| 0 | Tug contest: SAT-03 outranks SAT-10 and is served first. Three early dodges. | TUG_REQUEST, DODGE |
| 10-12 | Landfill leak starts (t=10); first real detection t=10; track confirmed at ~(56,43) at t=12. | ALERT |
| 13-24 | Drone dispatched to the leak (localization threshold met); drone confirms it at t=24. | DISPATCH_DRONE, CONFIRMED |
| 25-40 | Tug docks with SAT-03 and services it. | SERVICING, SERVICED |
| 31-45 | SAT-04 and then SAT-11 dodge debris; observation passes to SAT-11, SAT-07, SAT-02. | DODGE, REASSIGN |
| 63-78 | SAT-05 retired via controlled_deorbit after comparing it with drag sail and EDT tether. | RETIRE, RETIRED |
| 69-88 | SAT-09 dodges the debris that threatens it; SAT-12 takes over the leak watch at t=88. | DODGE, REASSIGN |
| 94, 161 | Drone is sent back to the leak twice more. | DISPATCH_DRONE |
| 100-140 | SAT-10 requests the tug when it is free again; serviced t=125-140. | TUG_REQUEST, SERVICING, SERVICED |
