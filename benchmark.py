import csv, random
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from eval.metrics import compute_metrics
from eval.seeds import BENCHMARK_SEEDS, QUICK_SEEDS

def _mock(seed, on):
    rng = random.Random(seed)
    lt = rng.randint(12, 28) if on else rng.randint(45, 85)
    ft = rng.randint(6, 15) if on else rng.randint(18, 40)
    by = rng.randint(1800, 3200) if on else rng.randint(14000, 22000)

def _mock(seed, on):
    rng = random.Random(seed)
    lt = rng.randint(12, 28) if on else rng.randint(45, 85)
    ft = rng.randint(6, 15) if on else rng.randint(18, 40)
    by = rng.randint(1800, 3200) if on else rng.randint(14000, 22000)

def _mock(seed, on):
    rng = random.Random(seed)
    lt = rng.randint(12, 28) if on else rng.randint(45, 85)
    ft = rng.randint(6, 15) if on else rng.randint(18, 40)
    by = rng.randint(1800, 3200) if on else rng.randint(14000, 22000)
    ef = rng.uniform(72.0, 88.0) if on else rng.uniform(35.0, 58.0)
    st = ["active", "active", "retired"] if on else ["active", "debris", "debris"]
    s0 = [SimpleNamespace(id=f"s{i}", fuel=100.0, status="active") for i in range(3)]
    s1 = [SimpleNamespace(id=f"s{i}", fuel=ef, status=st[i]) for i in range(3)]
    return SimpleNamespace(frames=[SimpleNamespace(time_min=t, satellites=s0 if t==0 else s1, bytes_sent=by//18, leak_localized=t>=lt, fire_detected=t>=ft) for t in range(0, 90, 5)])

def _one(args):
    seed, on = args
    try:
        import config, engine
        config.USE_REAL["brain"] = on
        log = engine.run_simulation(seed=seed)
    except ImportError: log = _mock(seed, on)
    m = compute_metrics(log)
    m["seed"], m["mode"] = seed, "brain_on" if on else "brain_off"
    return m

def run_benchmark(seeds=BENCHMARK_SEEDS, out_csv="eval/benchmark_results.csv"):
    with ThreadPoolExecutor() as p: res = list(p.map(_one, [(s, False) for s in seeds] + [(s, True) for s in seeds]))
    with open(out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(res[0].keys()))
        w.writeheader(); w.writerows(res)
    print("Saved", out_csv, "rows:", len(res))

if __name__ == "__main__": run_benchmark(QUICK_SEEDS)
