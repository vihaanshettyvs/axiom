"""REAL benchmark: runs the actual engine (Brain ON and OFF, same seeds) and scores it with P5's credits formula.

    python -m eval.real_benchmark --seeds 1 2 3 4 5 6 7 42     # -> eval/benchmark_results_real.csv + eval/benchmark_real.png

Every number comes from a RunLog the engine just produced. Nothing is simulated by this file or hardcoded.
"""
from __future__ import annotations

import argparse
import csv
import os
from concurrent.futures import ProcessPoolExecutor

import validate_demo
from eval.credits import calculate_credits

COLS = ["seed", "mode", "leak_localization_min", "fire_response_min", "uncontrolled_dead", "sats_lost",
        "controlled_retirements", "total_fuel_used_kg", "data_sent_mb", "emergencies_handled", "invalid_actions", "credits"]


def row(r):
    cr = calculate_credits(r["retired"], r["uncontrolled_dead"], r["fuel_remaining_pct"], r["bw_saved_pct"])
    return dict(seed=r["seed"], mode="brain_on" if r["mode"] == "on" else "brain_off",
                leak_localization_min=r["leak_localized_min"], fire_response_min=r["fireE_localized_min"],
                uncontrolled_dead=r["uncontrolled_dead"], sats_lost=r["sats_lost"], controlled_retirements=r["retired"],
                total_fuel_used_kg=round(r["fuel_kg"], 3), data_sent_mb=round(r["data_mb"], 1),
                emergencies_handled=r["emergencies_handled"], invalid_actions=r["invalid"]["total"], credits=cr)


def charts(rows, png):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import statistics as st
    def avg(mode, k):
        v = [r[k] for r in rows if r["mode"] == mode and r[k] is not None]
        return (st.mean(v) if v else 0.0), (st.pstdev(v) if len(v) > 1 else 0.0), len(v)
    panels = [("leak_localization_min", "Leak localized after start (min)"), ("data_sent_mb", "Data sent (MB, log scale)"),
              ("uncontrolled_dead", "Uncontrolled dead satellites / run"), ("total_fuel_used_kg", "Fuel used / run (kg)")]
    fig, ax = plt.subplots(1, 4, figsize=(16, 4.2), dpi=150)
    for a, (k, title) in zip(ax, panels):
        vals = [avg("brain_off", k), avg("brain_on", k)]
        a.bar(["Brain OFF", "Brain ON"], [v[0] for v in vals], yerr=[v[1] for v in vals], capsize=5, color=["#8C9BA5", "#1E3B2F"])
        a.set_title(title, fontsize=10, fontweight="bold")
        if k == "data_sent_mb":
            a.set_yscale("log")
    n = len({r["seed"] for r in rows})
    miss = {m: sum(1 for r in rows if r["mode"] == m and r["leak_localization_min"] is None) for m in ("brain_on", "brain_off")}
    note = ""
    if miss["brain_on"] or miss["brain_off"]:
        note = f"  Leak never localized in 180 min (excluded from leak bar): ON {miss['brain_on']}/{n}, OFF {miss['brain_off']}/{n}."
    fig.suptitle(f"Measured from real engine runs: {n} fixed seeds, identical worlds for ON and OFF (error bars = std dev).{note}", fontsize=8)
    plt.tight_layout()
    plt.savefig(png)


def redraw(csv_path, png):
    """Re-draw the chart from an existing results CSV (no simulation)."""
    num = lambda v: None if v in ("", None) else float(v)
    with open(csv_path) as fh:
        rows = [{k: (v if k == "mode" else num(v)) for k, v in r.items()} for r in csv.DictReader(fh)]
    charts(rows, png)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, nargs="*", default=[1, 2, 3, 4, 5, 6, 7, 42])
    ap.add_argument("--duration", type=int, default=180)
    ap.add_argument("--csv", default="eval/benchmark_results_real.csv")
    ap.add_argument("--png", default="eval/benchmark_real.png")
    a = ap.parse_args()
    jobs = [(m, s, a.duration) for s in a.seeds for m in ("on", "off")]
    with ProcessPoolExecutor(max_workers=min(6, os.cpu_count() or 2)) as ex:
        rows = [row(r) for r in ex.map(validate_demo.run_one, jobs)]
    with open(a.csv, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)
    charts(rows, a.png)
    print("saved", a.csv, a.png, "rows:", len(rows))


if __name__ == "__main__":
    main()
