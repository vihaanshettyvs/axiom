# Algorithms in plain English

**Engine loop (every simulated minute).** Physics moves satellites and degrades them → the plume moves → every sensor that can see something scans (satellites only where the brain pointed them last minute) → HAPS/drone scans reach the estimator immediately, satellite scans wait in a buffer → the estimator ages its belief → the brain looks at the *belief* (never the truth) and issues decisions → the engine applies them (burn fuel, downlink, dodge…) → collisions are rolled → one Frame is written to the RunLog.

**Plume (`brain/plume.py`).** Each fire drifts with a wind that slowly rotates plus random gusts, grows in radius, and its intensity rises toward a ceiling with noise. A scan detects it with probability = sensor quality × how central it is × how intense it is × (1 − cloud). Detections are jittered by sensor noise; sometimes a ghost appears.

**LeakHunter (`brain/leakhunter.py`).** A 50×50 grid holds "how likely is a fire centre here". Each minute the grid blurs a little (fires move) and drifts back toward a tiny prior (old information goes stale). A scan that sees nothing multiplies the covered cells by (1 − trust·Pd), so probability drops where we looked and found nothing — but cloudy scans count for little. A scan that sees something boosts cells near the reported position, weighed against the chance it's a false alarm: one detection ≈ "maybe", two consistent ones ≈ "yes", and a lone ghost fades when later scans come back empty. Delayed reports are treated as less precise because the fire has moved. Peaks of the grid become Estimates with existence, confidence, ± km spread, intensity and growth; a drone hit marks one "confirmed".

**Triage brain (`brain/triage.py`).** Every option is turned into the same "utility" number: *information value* (urgency × importance × expected information gain × sensor health), plus *loss avoided* (risk reduction × satellite value), minus *fuel*, *bandwidth* and other costs.
* OBSERVE – each satellite in view evaluates nadir, each hazard it can reach, and a ring of exploratory points; best wins; a "virtual" look is subtracted from the belief so the next satellite picks something else (coordination).
* DOWNLINK – in contact, send detections and the newest scan per area, compressed; discard stale duplicates.
* HANDOFF – a satellite with detections but a distant contact passes them over the crosslink to one whose contact is sooner.
* DODGE – dodge only if collision-probability × satellite value × effectiveness beats the fuel; acting early is cheaper and more effective.
* RETIRE – when life is almost over and fuel allows, de-orbit instead of dying as debris.
* REQUEST TUG – valuable, low-fuel/unhealthy satellites that will survive the rendezvous.
* DISPATCH HAPS / DRONE – see below.
Every decision stores its numbers and a sentence of reasoning, plus the next-best alternative.

**HAPS planner (`brain/haps.py`).** Candidate waypoints on a 5 km lattice are scored by (uncertainty + likelihood in the footprint, boosted near towns) ÷ (1 + travel time/25 min). Tightly localised or drone-confirmed fires are discounted until their data goes stale, so the HAPS does not hover over a known fire. A waypoint is held ≥10 min unless something is 2.5× better. The baseline is a serpentine lawnmower. **Drone escalation rule:** dispatch when a hazard is probably real (≥60 %), tightly localised (≤4 km), recently seen by air, not yet confirmed, and either intense (≥0.5) or backed by conflicting evidence, and the drone has the battery.

**BRAIN ON vs OFF.** Same seed, same world, same estimator. OFF: nadir-only scanning, raw FIFO downlink, late per-satellite dodging, lawnmower HAPS, no retirement/servicing/drone. ON: everything above.
