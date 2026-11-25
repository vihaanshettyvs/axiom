"""Integration tests: engine, determinism, brain ON vs OFF, mock/real switching, RunLog schema."""
import itertools, json, os
import pytest

import config, engine
from contracts import RunLog


@pytest.fixture(scope="module")
def comp():
    return engine.compare(42, 180, out_dir=None)

def test_all_mock_runs_and_is_replayable():
    lg = engine.run("on", 42, 40, {k: False for k in config.USE_REAL})
    assert len(lg.frames) == 40
    json.dumps(lg.to_dict())

def test_deterministic_same_seed_same_runlog():
    a = json.dumps(engine.run("on", 42, 60).to_dict(), sort_keys=True)
    b = json.dumps(engine.run("on", 42, 60).to_dict(), sort_keys=True)
    assert a == b
    assert a != json.dumps(engine.run("on", 43, 60).to_dict(), sort_keys=True)

def test_identical_initial_conditions_between_modes():
    on, off = engine.run("on", 42, 30), engine.run("off", 42, 30)
    for fo, ff in zip(on.frames, off.frames):
        assert [h.pos for h in fo.hazards] == [h.pos for h in ff.hazards]          # same world
        # same constellation, except where a DODGE has legitimately shifted a route (P2 execute_dodge, logged in orbit["maneuvers"])
        for a, b in zip(fo.satellites, ff.satellites):
            if a.kind == "SAT" and not a.orbit.get("maneuvers") and not b.orbit.get("maneuvers"):
                assert a.pos == b.pos
    assert [s.pos for s in on.frames[0].satellites] == [s.pos for s in off.frames[0].satellites]
    assert on.scenario == off.scenario

@pytest.mark.parametrize("combo", list(itertools.product([False, True], repeat=4))[::3])
def test_modules_switch_independently(combo):
    ur = dict(physics=False, plume=combo[0], leakhunter=combo[1], triage=combo[2], haps=combo[3])
    lg = engine.run("on", 42, 25, ur)
    assert len(lg.frames) == 25 and lg.meta["use_real"] == ur

def test_runlog_schema(tmp_path):
    lg = engine.run("on", 42, 20)
    p = tmp_path / "r.json"
    lg.save(str(p))
    d = RunLog.load(str(p))
    assert {"meta", "scenario", "frames", "summary"} <= set(d)
    f = d["frames"][5]
    for k in ("t", "satellites", "hazards", "observations", "decisions", "estimates", "belief_permille",
              "entropy_bits", "uncertainty", "events", "metrics"):
        assert k in f
    assert len(f["belief_permille"]) == 50 and len(f["belief_permille"][0]) == 50
    assert d["meta"]["grid_n"] == 50 and d["meta"]["step_min"] == 1.0

def test_every_decision_has_reason_and_costs(comp):
    on, _ = comp["_logs"]
    ds = [d for f in on.frames for d in f.decisions]
    assert len(ds) > 100 and all(len(d.reason) > 20 for d in ds)
    kinds = {d.action.type.value for d in ds}
    assert {"OBSERVE", "DOWNLINK", "DODGE", "RETIRE", "DISPATCH_HAPS", "DISPATCH_DRONE", "REQUEST_TUG"} <= kinds

def test_brain_on_beats_brain_off(comp):
    m = comp["metrics"]
    for k in ("mean_loc_error_km", "mean_time_to_detect_min", "mean_detection_latency_min", "bandwidth_mb",
              "attention_alerts", "expected_sat_loss", "uncontrolled_dead"):
        assert m[k]["brain_on"] < m[k]["brain_off"], k
    assert m["sats_lost"]["brain_on"] <= m["sats_lost"]["brain_off"]
    # ON may spend a little more fuel (early dodges, re-pointing) but must buy a large risk reduction with it
    assert m["fuel_used_kg"]["brain_on"] < 1.25 * m["fuel_used_kg"]["brain_off"]

@pytest.mark.parametrize("seed", [7, 123])
def test_brain_on_wins_on_other_seeds(seed):
    m = engine.compare(seed, 180)["metrics"]
    assert m["mean_time_to_detect_min"]["brain_on"] < m["mean_time_to_detect_min"]["brain_off"]
    assert m["bandwidth_mb"]["brain_on"] < m["bandwidth_mb"]["brain_off"]
    assert m["mean_loc_error_km"]["brain_on"] < m["mean_loc_error_km"]["brain_off"]

def test_sample_runlog_written():
    os.makedirs("out", exist_ok=True)
    engine.compare(42, 180, out_dir="out")
    assert os.path.getsize("out/runlog_brain_on.json") > 100_000
