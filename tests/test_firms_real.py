"""Runs only when the real NASA FIRMS file is present at data/firms/sample_viirs_snpp.csv (it lives on P4's branch)."""
import os

import pytest

import config
import engine
import scenario_data

CSV = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "firms", "sample_viirs_snpp.csv")


@pytest.mark.skipif(not os.path.exists(CSV), reason="real FIRMS CSV not in this checkout")
def test_real_firms_file_drives_the_engine(monkeypatch):
    monkeypatch.setattr(config, "WILDFIRE_DATA_PATH", CSV)
    lg = engine.Engine("on", 2, 60).run()
    lat, lon = scenario_data.FIRMS_REGION_USED
    assert 59.0 < lat < 60.0 and -113.5 < lon < -112.0                       # densest window in the file (northern Alberta)
    assert scenario_data.FIRMS_READER_USED == "sensing.fire"
    wild = [h for h in lg.scenario["hazards"] if h["kind"] == "wildfire"]
    assert wild and all(h["source"] == "NASA_FIRMS" for h in wild)
    assert all(h["source"] == "SIMULATED" for h in lg.scenario["hazards"] if h["kind"] == "methane")
    assert lg.meta["completed"] and "sample_viirs_snpp" in lg.scenario["hazard_source_note"]
