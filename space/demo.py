"""Standalone space-systems demonstration (no engine, no UI).

Run from the repo root:   python -m space.demo [--seed 42] [--minutes 240] [--weather 0.5] [--n 12]

Twelve satellites fly their ground tracks; debris threats approach three of them; failures
(communication, propulsion, battery) are scripted; the one shared tug serves competing requests.
A trivial scripted "policy" stands in for P1's brain and exercises every physics interaction:
  threat -> recommend_dodge -> execute_dodge (fuel, route change)
  degradation -> telemetry -> last_breath verdict -> retirement option -> RETIRING -> RETIRED
  low fuel / damage -> competing tug requests -> tug_rank -> request_tug -> SERVICING -> serviced
All numbers are simplified prototype models, see docs/ASSUMPTIONS.md.
"""
from __future__ import annotations

import argparse
from typing import Any, Dict, List

import config
from contracts import Satellite, Status
from physics.api import RealPhysics
from space import orbits


def build_sats(n: int, seed: int) -> List[Satellite]:
    sats = []
    for d in orbits.make_constellation(n, seed):
        sats.append(Satellite(
            id=d["id"], kind="SAT", fuel_kg=d["fuel"], fuel_capacity_kg=2.0, health=d["health"],
            mission_importance=d["importance"], sensor_radius_km=12.0, slew_km=22.0,
            orbit=dict(A=d["A"], B=d["B"], period=d["period"], phase=d["phase"], base_conf=0.8,
                       degrade_rate=d["degrade"], alt_km=d["alt_km"])))
    sats.append(Satellite(id="TUG-1", kind="TUG", status=Status.IDLE.value, orbit={"park": (0.0, -30.0)}))
    return sats


def run(seed: int = 42, minutes: int = 240, weather: float = 0.5, n: int = 12, verbose: bool = True) -> Dict[str, Any]:
    phys = RealPhysics()
    phys.set_space_weather(weather)
    sats = phys.reset(seed, build_sats(n, seed))
    by_id = {s.id: s for s in sats}
    events: List[str] = []

    def log(t, msg):
        events.append(f"t={t:5.0f}  {msg}")
        if verbose:
            print(events[-1])

    # ---- scenario: own threats (replace the engine's scripted conjunctions) and scripted failures ----
    phys.enc.clear()
    for sid, lvl in (("SAT-02", "HIGH"), ("SAT-05", "MEDIUM"), ("SAT-08", "LOW")):
        e = phys.inject_threat(by_id[sid], 0.0, lvl)
        log(0, f"THREAT {lvl}: {e['debris_id']} -> {sid}, TCA t={e['tca']:.0f}, likelihood {e['p']:.3f}")
    by_id["SAT-04"].orbit["known_failure"] = {"t": 50, "mode": "communication"}
    by_id["SAT-07"].orbit["known_failure"] = {"t": 70, "mode": "propulsion"}
    by_id["SAT-09"].health, by_id["SAT-09"].orbit["degrade_rate"] = 0.30, 0.0035       # dying
    by_id["SAT-03"].fuel_kg = 0.30                                                       # needs a refuel
    by_id["SAT-11"].health, by_id["SAT-11"].mission_importance = 0.45, 0.9              # damaged, valuable

    seen_verdict: Dict[str, str] = {}
    for t in range(1, minutes + 1):
        phys.step(sats, float(t), 1.0)
        # --- debris: act on recommendations ---
        for s in sats:
            if s.kind != "SAT" or not s.operational:
                continue
            for rec in phys.recommend_dodge(s, float(t)):
                if rec["lead_min"] > 90:
                    continue
                if rec["recommend_dodge"]:
                    r = phys.execute_dodge(s, float(t), rec["debris_id"], debit_fuel=True)
                    log(t, f"{rec['reason']}  -> {'done' if r['executed'] else r['reason']}")
                elif seen_verdict.get(rec["debris_id"]) is None:
                    seen_verdict[rec["debris_id"]] = "HOLD"
                    log(t, rec["reason"])
        # --- degradation / last breath / retirement ---
        for s in sats:
            if s.kind != "SAT":
                continue
            for f in s.orbit.get("telemetry", {}).get("active_failures", []):
                key = f"{s.id}:{f}"
                if key not in seen_verdict:
                    seen_verdict[key] = f
                    log(t, f"FAILURE {s.id}: {f} (severity {s.orbit['telemetry']['failure_severity']:.2f})")
            if s.status == Status.DEAD.value and seen_verdict.get(s.id) != "DEAD":
                seen_verdict[s.id] = "DEAD"
                log(t, f"{s.id} DEAD (uncontrolled)")
            if not s.operational:
                continue
            lb = s.orbit["last_breath"]
            if seen_verdict.get(s.id) != lb["verdict"]:
                seen_verdict[s.id] = lb["verdict"]
                if lb["verdict"] != "SAVE":
                    log(t, lb["reason"])
            if lb["verdict"] == "RETIRE":
                opts = phys.retirement_options(s, float(t))
                if opts:
                    o = opts[0]
                    s.fuel_kg -= o["fuel_kg"]
                    s.status = Status.RETIRING.value
                    s.orbit["retire_done_t"] = t + o["duration_min"]
                    log(t, f"RETIRE {s.id} via {o['name']} ({o['fuel_kg']:.2f} kg, done t={t + o['duration_min']:.0f})")
                elif seen_verdict.get(s.id + ":passive") is None:
                    seen_verdict[s.id + ":passive"] = "x"
                    lab = [r for r in phys.retirement_lab(s, float(t)) if r["feasible"] and r["option"] in ("drag_sail", "edt_tether")]
                    best = min(lab, key=lambda r: r["reentry_days"]) if lab else None
                    log(t, f"RETIRE {s.id}: no propellant/propulsion; passive option "
                           + (f"{best['option']} (re-entry {best['reentry_days']:.0f} d)" if best else "none feasible"))
        # --- tug: competing requests ---
        if phys.tug_status(float(t))["available"] and phys.tug_fuel >= 0.05:
            reqs = []
            for s in sats:
                if s.kind != "SAT" or not s.operational or "tug_arrival_t" in s.orbit:
                    continue
                low_fuel = s.fuel_kg < 0.25 * s.fuel_capacity_kg
                damaged = s.health < 0.5
                if low_fuel or damaged:
                    reqs.append({"sat_id": s.id, "op": "REPAIR" if damaged else "REFUEL",
                                 "urgency": 1.0 - s.health if damaged else 0.5,
                                 "mission_value": s.mission_importance, "travel_min": config.TUG["eta_min"]})
            if reqs:
                pick = phys.tug_rank(reqs)
                r = phys.request_tug(by_id[pick["chosen"]], float(t))
                log(t, f"TUG {pick['reason']} -> {'accepted ' + str(r['ops']) if r['accepted'] else 'refused'}")
        for s in sats:
            if s.orbit.get("serviced") and seen_verdict.get(s.id + ":svc") is None and s.operational:
                seen_verdict[s.id + ":svc"] = "x"
                log(t, f"SERVICED {s.id}: fuel {s.fuel_kg:.2f} kg, health {s.health:.2f}")

    summary = {"events": events, "final": {s.id: (s.status, round(s.health, 2), round(s.fuel_kg, 2))
                                           for s in sats if s.kind == "SAT"},
               "tug_fuel_left_kg": phys.tug_fuel, "space_weather": weather}
    if verbose:
        print("\nFINAL (status, health, fuel kg):")
        for k, v in summary["final"].items():
            print(f"  {k}: {v}")
        print(f"tug propellant left: {phys.tug_fuel:.2f} kg")
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--minutes", type=int, default=240)
    ap.add_argument("--weather", type=float, default=0.5)
    ap.add_argument("--n", type=int, default=12)
    a = ap.parse_args()
    run(a.seed, a.minutes, a.weather, a.n)
