"""Demo validation: run Brain ON and Brain OFF on several fixed seeds and compute REAL metrics from the RunLogs.

    python validate_demo.py                      # seeds 1-7 and 42, 180 min  -> out/validation.json + table
    python validate_demo.py --seeds 1 2 3 --duration 60

Nothing here is hardcoded: every number is read from the RunLog the engine just produced.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from concurrent.futures import ProcessPoolExecutor
from typing import Any, Dict, List

import config
import engine

LANDFILL = next(h for h in config.HAZARDS if h["id"] == "LEAK-1")
GONE = ("DEAD", "RETIRED", "LOST")


def _first_conf(lg, kind: str, pos, radius: float = 6.0):
    return next((f.t for f in lg.frames for e in f.estimates
                 if e.kind == kind and e.existence > 0.8 and math.dist(e.pos, pos) < radius), None)


def audit(lg) -> Dict[str, Any]:
    """Count unsafe / invalid / contradictory things in a RunLog (read-only)."""
    bad: Dict[str, int] = {}
    ex: Dict[str, str] = {}

    def flag(k, m):
        bad[k] = bad.get(k, 0) + 1
        ex.setdefault(k, m)

    gone: Dict[str, float] = {}
    retire_n: Dict[str, int] = {}
    for f in lg.frames:
        servicing = [s.id for s in f.satellites if s.status == "SERVICING"]
        if len(servicing) > 1:
            flag("two_satellites_servicing", f"t={f.t} {servicing}")
        per: Dict[str, set] = {}
        for s in f.satellites:
            if s.fuel_kg < -1e-9 or s.health < -1e-9:
                flag("negative_fuel_or_health", f"{s.id} t={f.t}")
            b = s.orbit.get("telemetry", {}).get("battery")
            if b is not None and b < -1e-9:
                flag("negative_battery", f"{s.id} t={f.t}")
            if s.kind == "SAT":
                if s.status in GONE and s.id not in gone:
                    gone[s.id] = f.t
                if s.id in gone and s.status not in GONE:
                    flag("satellite_came_back", f"{s.id} t={f.t}")
        for d in f.decisions:
            a = d.action
            if not d.reason.strip():
                flag("decision_without_reason", f"t={f.t} {a.actor_id} {a.type.value}")
            if a.actor_id in gone and f.t > gone[a.actor_id] and a.type.value not in ("DOWNLINK",):
                flag("action_after_loss_or_retirement", f"{a.actor_id} {a.type.value} t={f.t}")
            per.setdefault(a.actor_id, set()).add(a.type.value)
            if a.type.value == "RETIRE":
                retire_n[a.actor_id] = retire_n.get(a.actor_id, 0) + 1
        for sid, ty in per.items():
            if "DODGE" in ty and "OBSERVE" in ty:
                flag("dodge_and_observe_same_minute", f"{sid} t={f.t}")
        for e in f.events:
            if e["type"] in ("ACTION_FAILED", "DODGE_FAILED", "TUG_DENIED", "MODULE_FALLBACK", "MODULE_WARNING"):
                flag("engine_rejected_or_failed:" + e["type"], f"t={f.t} {e['actor']}")
    for sid, n in retire_n.items():
        if n > 1:
            flag("repeated_retire", f"{sid} x{n}")
    return dict(total=sum(bad.values()), by_type=bad, examples=ex)


def emergencies(lg) -> Dict[str, bool]:
    fe = next(h for h in config.HAZARDS if h["id"] == "FIRE-E")
    fw = next(h for h in config.HAZARDS if h["id"] == "FIRE-W")
    collisions = {e["actor"] for f in lg.frames for e in f.events if e["type"] == "COLLISION"}
    last = {s.id: s for s in lg.frames[-1].satellites}
    return {
        "landfill_leak_localized": _first_conf(lg, "methane", LANDFILL["pos"]) is not None
        and any(d.hazard_id == LANDFILL["id"] for f in lg.frames for o in f.observations for d in o.detections),
        "wildfire_east_localized": _first_conf(lg, "wildfire", fe["pos"], 8.0) is not None,
        "wildfire_west_localized": _first_conf(lg, "wildfire", fw["pos"], 8.0) is not None,
        "no_debris_collision": not collisions,
        "dying_satellite_not_lost_uncontrolled": last["SAT-05"].status != "DEAD",
        "low_fuel_satellite_serviced": bool(last["SAT-03"].orbit.get("serviced")),
    }


def run_one(args):
    mode, seed, duration = args
    lg = engine.Engine(mode, seed, duration).run()
    fe = next(h for h in config.HAZARDS if h["id"] == "FIRE-E")
    fw = next(h for h in config.HAZARDS if h["id"] == "FIRE-W")
    t_leak = _first_conf(lg, "methane", LANDFILL["pos"])
    seen = next((f.t for f in lg.frames for o in f.observations for d in o.detections
                 if d.hazard_id == LANDFILL["id"]), None)            # ground truth: a REAL detection of the leak must exist
    if seen is None or (t_leak is not None and seen > t_leak):
        t_leak = None
    t_fe = _first_conf(lg, "wildfire", fe["pos"], 8.0)
    t_fw = _first_conf(lg, "wildfire", fw["pos"], 8.0)
    em = emergencies(lg)
    s = lg.summary
    sats = [x for x in lg.frames[-1].satellites if x.kind == "SAT"]
    first = {x.id: x.fuel_kg for x in lg.frames[0].satellites if x.kind == "SAT"}
    cap = sum(first.values())
    raw_mb = sum(o.size_raw_mb for f in lg.frames for o in f.observations)
    return dict(
        mode=mode, seed=seed,
        leak_localized_min=None if t_leak is None else t_leak - LANDFILL["t_start"],
        fireE_localized_min=None if t_fe is None else t_fe - fe["t_start"],
        fireW_localized_min=None if t_fw is None else t_fw - fw["t_start"],
        fuel_kg=s["fuel_used_kg"], data_mb=s["bandwidth_mb"], alerts=s["attention_alerts"],
        mean_loc_error_km=s["mean_loc_error_km"], detection_latency_min=s["mean_detection_latency_min"],
        sats_lost=s["sats_lost"], uncontrolled_dead=s["uncontrolled_dead"],
        emergencies_handled=sum(em.values()), emergencies=em, invalid=audit(lg),
        completed=lg.meta["completed"],
        retired=s["retired"], serviced=s["serviced"],
        fuel_remaining_pct=100.0 * sum(x.fuel_kg for x in sats) / cap if cap else 0.0,
        bw_saved_pct=max(0.0, 100.0 * (1.0 - s["bandwidth_mb"] / raw_mb)) if raw_mb else 0.0,
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, nargs="*", default=[1, 2, 3, 4, 5, 6, 7, 42])
    ap.add_argument("--duration", type=int, default=180)
    ap.add_argument("--out", default="out")
    a = ap.parse_args()
    jobs = [(m, s, a.duration) for s in a.seeds for m in ("on", "off")]
    with ProcessPoolExecutor(max_workers=min(6, os.cpu_count() or 2)) as ex:
        rows: List[Dict[str, Any]] = list(ex.map(run_one, jobs))
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "validation.json"), "w") as fh:
        json.dump(rows, fh, indent=1)
    fmt = lambda v: "never" if v is None else (f"{v:.1f}" if isinstance(v, float) else str(v))
    print("seed | mode | leak_loc | fireE_loc | fireW_loc | fuel | data MB | lost/dead | emerg | invalid")
    for r in rows:
        print(f"{r['seed']:>3} | {r['mode']:>3} | {fmt(r['leak_localized_min']):>5} | {fmt(r['fireE_localized_min']):>5} | "
              f"{fmt(r['fireW_localized_min']):>5} | {r['fuel_kg']:.2f} | {r['data_mb']:.0f} | "
              f"{r['sats_lost']}/{r['uncontrolled_dead']} | {r['emergencies_handled']}/6 | {r['invalid']['total']}")


if __name__ == "__main__":
    main()
