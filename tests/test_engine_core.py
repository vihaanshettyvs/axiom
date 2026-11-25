"""Central-engine tests: mock run, fallbacks, extensions, data loader, save/load, determinism."""
import json, os, textwrap
import pytest

import config, engine, scenario_data
from contracts import RunLog, Frame, Satellite, Decision

ALL_MOCK = {k: False for k in config.USE_REAL}


def test_60_minute_simulation_with_mocks_completes(tmp_path):
    lg = engine.Engine("on", 42, 60, ALL_MOCK).run()
    assert lg.meta["completed"] is True and len(lg.frames) == 60
    assert lg.meta["modules"] == {"physics": "mock", "plume": "mock", "lh": "mock", "triage": "mock"}
    assert [f.t for f in lg.frames] == [float(i) for i in range(60)]
    p = tmp_path / "mock60.json"
    lg.save(str(p))
    assert os.path.getsize(p) > 10_000


def test_world_has_12_satellites_haps_drone_tug_and_both_hazard_kinds():
    lg = engine.Engine("on", 42, 40).run()
    kinds = [s.kind for s in lg.frames[0].satellites]
    assert kinds.count("SAT") == 12 and kinds.count("HAPS") == 1 and kinds.count("DRONE") == 1 and kinds.count("TUG") == 1
    assert {h.kind for h in lg.frames[-1].hazards if h.active} == {"wildfire", "methane"}
    assert set(lg.frames[-1].belief_by_kind) == {"wildfire", "methane"}
    assert len(lg.frames[-1].belief_by_kind["methane"]) == 50


def test_methane_is_detected_and_tracked_as_its_own_kind():
    lg = engine.Engine("on", 42, 180).run()          # methane is the slow, weak signal: needs the full scenario
    ests = [e for f in lg.frames for e in f.estimates if e.kind == "methane" and e.existence > 0.8]
    assert ests and all(e.id.startswith("LEAK") for e in ests)


def test_save_and_load_runlog_roundtrip(tmp_path):
    lg = engine.Engine("off", 42, 25).run()
    p = tmp_path / "r.json"
    lg.save(str(p))
    back = RunLog.read(str(p))
    assert isinstance(back.frames[3], Frame) and isinstance(back.frames[3].satellites[0], Satellite)
    assert back.to_dict() == RunLog.load_dict(str(p))


def test_same_seed_reproducible_and_modes_share_the_world():
    a = json.dumps(engine.Engine("on", 5, 40).run().to_dict(), sort_keys=True)
    assert a == json.dumps(engine.Engine("on", 5, 40).run().to_dict(), sort_keys=True)
    on, off = engine.Engine("on", 5, 30).run(), engine.Engine("off", 5, 30).run()
    assert [h.pos for h in on.frames[-1].hazards] == [h.pos for h in off.frames[-1].hazards]


def test_missing_real_physics_module_falls_back_to_mock(monkeypatch):
    monkeypatch.setattr(config, "PHYSICS_REAL_PATH", "does_not.exist:Nope")
    lg = engine.Engine("on", 42, 30).run()
    assert lg.meta["completed"] and lg.meta["modules"]["physics"] == "fallback" or lg.meta["modules"]["physics"] == "mock"
    ev = [e for f in lg.frames for e in f.events if e["type"] == "MODULE_FALLBACK"]
    assert ev and ev[0]["actor"] == "physics" and len(lg.frames) == 30


def test_module_that_crashes_mid_run_is_swapped_for_its_mock(monkeypatch):
    from brain.triage import TriageBrain
    orig = TriageBrain.decide
    def boom(self, view):
        if view.t >= 10:
            raise RuntimeError("synthetic failure")
        return orig(self, view)
    monkeypatch.setattr(TriageBrain, "decide", boom)
    lg = engine.Engine("on", 42, 30).run()
    assert lg.meta["completed"] and len(lg.frames) == 30 and lg.meta["modules"]["triage"] == "fallback"
    ev = [(int(f.t), e["actor"]) for f in lg.frames for e in f.events if e["type"] == "MODULE_FALLBACK"]
    assert ev == [(10, "triage")]


def test_bad_extension_is_disabled_not_fatal(monkeypatch, tmp_path):
    (tmp_path / "ext_ok.py").write_text("class T:\n    n=0\n    def on_step(self, f): T.n += 1\n")
    (tmp_path / "ext_bad.py").write_text("class B:\n    def on_step(self, f): raise ValueError('x')\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(config, "EXTENSIONS", {"ok": "ext_ok:T", "bad": "ext_bad:B", "missing": "nope:X"})
    lg = engine.Engine("on", 42, 15).run()
    assert lg.meta["completed"] and lg.meta["extensions"] == ["ok"]
    import ext_ok
    assert ext_ok.T.n == 15
    assert sum(e["type"] == "EXTENSION_DISABLED" for f in lg.frames for e in f.events) == 2


def test_firms_loader_and_fallback(tmp_path, monkeypatch):
    # SYNTHETIC test fixture in FIRMS format (not real fire data)
    csv_ = textwrap.dedent("""\
        latitude,longitude,bright_ti4,frp,acq_date,acq_time,confidence
        34.00,-118.00,340,45.0,2026-08-01,1000,h
        34.01,-118.01,330,30.0,2026-08-01,1010,h
        34.20,-117.80,360,80.0,2026-08-01,1100,h
        garbage,row,,,,,
        """)
    f = tmp_path / "firms.csv"
    f.write_text(csv_)
    specs = scenario_data.load_firms_csv(str(f))
    assert 1 <= len(specs) <= 3 and all(0 < s["pos"][0] < 100 and 0 < s["pos"][1] < 100 for s in specs)
    assert min(s["t_start"] for s in specs) == 0.0
    monkeypatch.setattr(config, "WILDFIRE_DATA_PATH", str(f))
    lg = engine.Engine("on", 42, 20).run()
    assert lg.meta["hazard_source"].startswith("firms:") and lg.meta["completed"]
    monkeypatch.setattr(config, "WILDFIRE_DATA_PATH", str(tmp_path / "missing.csv"))
    lg = engine.Engine("on", 42, 20).run()
    assert lg.meta["hazard_source"] == "synthetic"
    assert any(e["type"] == "DATA_FALLBACK" for f_ in lg.frames for e in f_.events)


def test_configurable_duration():
    assert len(engine.Engine("on", 1, 7, ALL_MOCK).run().frames) == 7
