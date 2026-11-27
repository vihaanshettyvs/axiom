"""Real-NASA-FIRMS wildfire scenario: Brain ON vs OFF on several seeds (metrics read from the RunLogs).

    python validate_firms.py path/to/sample_viirs_snpp.csv [--seeds 1 2 3 4 5 42] [--duration 180]

Wildfires = real FIRMS detections (positions, strength, timing); methane leaks, debris, satellites, sensors = simulated.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from concurrent.futures import ProcessPoolExecutor

import config
import engine
import scenario_data
import validate_demo


def run_one(args):
    path, mode, seed, duration = args
    config.WILDFIRE_DATA_PATH = path
    lg = engine.Engine(mode, seed, duration).run()
    truth = {h.id: h for h in lg.frames[0].hazards}
    spec = {h["id"]: h for h in lg.scenario["hazards"]}
    out = {}
    for hid, h in truth.items():
        t0 = spec[hid]["t_start"]
        seen = next((f.t for f in lg.frames for o in f.observations for d in o.detections
                     if d.hazard_id == hid and not d.is_false_positive), None)
        conf = next((f.t for f in lg.frames for e in f.estimates
                     if e.kind == h.kind and e.existence > 0.8 and math.dist(e.pos, h.pos) < 8.0), None)
        ok = conf is not None and seen is not None and seen <= conf
        out[hid] = dict(kind=h.kind, source=spec[hid]["source"], t_start=t0, localized_after_start_min=(conf - t0) if ok else None)
    s = lg.summary
    return dict(mode=mode, seed=seed, hazards=out, fuel_kg=s["fuel_used_kg"], data_mb=s["bandwidth_mb"],
                sats_lost=s["sats_lost"], uncontrolled_dead=s["uncontrolled_dead"], completed=lg.meta["completed"],
                invalid=validate_demo.audit(lg)["total"], note=lg.scenario["hazard_source_note"],
                region=scenario_data.FIRMS_REGION_USED)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--seeds", type=int, nargs="*", default=[1, 2, 3, 4, 5, 42])
    ap.add_argument("--duration", type=int, default=180)
    ap.add_argument("--out", default="out/firms_validation.json")
    a = ap.parse_args()
    jobs = [(a.csv, m, s, a.duration) for s in a.seeds for m in ("on", "off")]
    with ProcessPoolExecutor(max_workers=min(6, os.cpu_count() or 2)) as ex:
        rows = list(ex.map(run_one, jobs))
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w") as fh:
        json.dump(rows, fh, indent=1)
    fmt = lambda v: "never" if v is None else f"{v:.0f}"
    for r in rows:
        hz = " ".join(f"{k}:{fmt(v['localized_after_start_min'])}" for k, v in r["hazards"].items())
        print(f"seed {r['seed']:>2} {r['mode']:>3} | {hz} | fuel {r['fuel_kg']:.2f} | data {r['data_mb']:.0f} MB | "
              f"lost/dead {r['sats_lost']}/{r['uncontrolled_dead']} | invalid {r['invalid']} | done {r['completed']}")
    print(rows[0]["note"])


if __name__ == "__main__":
    main()
