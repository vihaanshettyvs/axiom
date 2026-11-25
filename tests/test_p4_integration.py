"""P4 modules executed for real: FIRMS reader -> hazards -> engine run; telemetry; analysis report on a real RunLog."""
import json

import numpy as np

import config
import engine
import scenario_data
from sensing.fire import FireReplay, geographic_to_local_km, load_fire_detections
from sensing.report import generate_p4_report
from sensing.telemetry import TelemetryState, advance_telemetry

HEADER = "latitude,longitude,acq_date,acq_time,satellite,instrument,confidence,frp,daynight\n"


def _fixture(tmp_path):
    # SYNTHETIC fixture in the full FIRMS schema (NOT real fire data) -- it only tests the code path.
    rows = [f"{37.0 + 0.1 * (i % 3):.4f},{-120.0 + 0.1 * (i % 2):.4f},2024-08-01,{1000 + 5 * i:04d},N,VIIRS,n,{10 + i}.5,D\n"
            for i in range(12)]
    p = tmp_path / "firms_full_schema.csv"
    p.write_text(HEADER + "".join(rows))
    return str(p)


def test_p4_fire_reader_geometry_and_replay(tmp_path):
    dets = load_fire_detections(_fixture(tmp_path), 37.0, -120.0)
    assert len(dets) == 12 and dets[0].timestamp_utc <= dets[-1].timestamp_utc
    x, y = geographic_to_local_km(37.1, -120.0, 37.0, -120.0)
    assert abs(x) < 1e-6 and 10.9 < y < 11.3                     # 0.1 deg latitude ~ 11.1 km
    assert len(FireReplay(dets, dets[0].timestamp_utc).at(0)) >= 1
    assert len(FireReplay(dets, dets[0].timestamp_utc).at(1000)) == 12


def test_firms_data_drives_the_engine_through_p4_reader(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WILDFIRE_DATA_PATH", _fixture(tmp_path))
    lg = engine.Engine("on", 42, 30).run()
    assert scenario_data.FIRMS_READER_USED == "sensing.fire"
    assert lg.meta["hazard_source"].startswith("firms:") and lg.meta["completed"]
    src = {h["id"]: h["source"] for h in lg.scenario["hazards"]}
    assert any(v == "NASA_FIRMS" for v in src.values()) and src["LEAK-1"] == "SIMULATED"   # methane is never real data


def test_p4_telemetry_is_deterministic_and_degrades():
    def run(seed):
        st, rng = TelemetryState("SAT-X", failure_mode="battery_degradation"), np.random.default_rng(seed)
        return [advance_telemetry(st, 1.0, rng).battery_health_pct for _ in range(30)]
    a, b = run(1), run(1)
    assert a == b and a[-1] < a[0] <= 100.0


def test_p4_report_on_a_real_runlog(tmp_path):
    out = tmp_path / "o"
    engine.compare(42, 40, str(out))
    rep = json.load(open(out / "p4_report.json"))
    assert rep["comparison"]["bandwidth"]["brain_off_mb"] > rep["comparison"]["bandwidth"]["brain_on_mb"] > 0
    assert rep["runs"]["brain_on"]["observation_analysis"]["observation_count"] > 0
    assert rep["runs"]["brain_on"]["hazard_estimates"] is not None


def test_global_firms_file_is_reduced_to_the_densest_compact_cluster(tmp_path, monkeypatch):
    # SYNTHETIC GLOBAL fixture (not real data): a dense 60-fire cluster, a smaller one far away, and scattered fires.
    import random
    rng = random.Random(3)
    rows = []
    for i in range(60):
        rows.append((37.0 + rng.uniform(-0.25, 0.25), -120.0 + rng.uniform(-0.3, 0.3), 1000 + i))
    for i in range(25):
        rows.append((-20.0 + rng.uniform(-0.2, 0.2), 130.0 + rng.uniform(-0.2, 0.2), 1200 + i))
    for i in range(400):
        rows.append((rng.uniform(-60, 60), rng.uniform(-170, 170), 100 + i % 1500))
    p = tmp_path / "global.csv"
    p.write_text(HEADER + "".join(f"{a:.4f},{b:.4f},2023-07-12,{t:04d},N,VIIRS,n,{10 + (i % 40)}.5,D\n"
                                  for i, (a, b, t) in enumerate(rows) if t % 100 < 60))
    monkeypatch.setattr(config, "WILDFIRE_DATA_PATH", str(p))
    specs = scenario_data.load_firms_csv(str(p))
    lat0, lon0 = scenario_data.FIRMS_REGION_USED
    assert abs(lat0 - 37.0) < 0.6 and abs(lon0 + 120.0) < 0.6          # picked the dense cluster, not the global median
    wild = [s for s in specs if s["kind"] == "wildfire"]
    assert wild and all(3 <= s["pos"][0] <= 97 and 3 <= s["pos"][1] <= 97 for s in wild)
    lg = engine.Engine("on", 42, 20).run()
    assert "36." in lg.scenario["hazard_source_note"] and "SIMULATED" in lg.scenario["hazard_source_note"]


def test_real_scale_global_file_loads_fast(tmp_path):
    import random, time
    rng = random.Random(5)
    p = tmp_path / "big.csv"
    with open(p, "w") as fh:
        fh.write(HEADER)
        for i in range(74605):
            fh.write(f"{rng.uniform(-60, 70):.4f},{rng.uniform(-160, 170):.4f},2023-07-12,{rng.randint(0, 23) * 100 + rng.randint(0, 59):04d},N,VIIRS,n,{rng.uniform(1, 90):.1f},D\n")
    t0 = time.time()
    specs = scenario_data.load_firms_csv(str(p))
    assert time.time() - t0 < 25 and specs
