"""Unit tests: contracts, plume, leakhunter, haps, triage.   Run: python -m pytest -q"""
import json, math
import numpy as np
import pytest

import config
import mocks
from contracts import (GRID_N, CELL_KM, Satellite, Observation, Detection, Estimate, Asset, Conjunction, PendingItem,
                       WorldView, ActionType, make_rng, grid_xy, pos_to_cell, to_jsonable, dist)
from brain.plume import PlumeModel, edge_weight
from brain.leakhunter import LeakHunter, _box_sum, binary_entropy, expected_gain
from brain.haps import AdaptiveHAPSPlanner, LawnmowerPlanner, should_dispatch_drone
from brain.triage import TriageBrain, BaselinePolicy


def sat(**kw):
    d = dict(id="S", kind="SAT", pos=(50.0, 50.0), sensor_confidence=0.8, sensor_radius_km=12.0, slew_km=22.0,
             sigma_km=1.5, fp_rate=0.04, health=1.0, fuel_kg=1.0, orbit={"A": (0, 0), "B": (1, 1), "period": 100,
                                                                      "phase": 0, "degrade_rate": 0.0, "base_conf": 0.8})
    d.update(kw)
    return Satellite(**d)


def obs(aim, dets, **kw):
    d = dict(id="o", t=0.0, sensor_id="S", source="SAT", aim=aim, radius_km=12.0,
             detections=[Detection(p, 0.6) for p in dets], sigma_km=1.5, pd_nominal=0.8, fp_rate=0.04)
    d.update(kw)
    return Observation(**d)


# ---------------------------------------------------------------- contracts
def test_rng_is_deterministic_and_keyed():
    assert make_rng(1, "a", 2).random() == make_rng(1, "a", 2).random()
    assert make_rng(1, "a", 2).random() != make_rng(1, "a", 3).random()

def test_grid_geometry():
    X, Y = grid_xy()
    assert X.shape == (GRID_N, GRID_N) == (50, 50)
    assert pos_to_cell(0.1, 99.9) == (0, 49)
    assert abs(X[0, 1] - X[0, 0] - CELL_KM) < 1e-9

def test_jsonable_roundtrip():
    s = to_jsonable(sat())
    json.dumps(s)
    assert s["id"] == "S" and isinstance(s["pos"], list)


# ---------------------------------------------------------------- plume
def test_plume_is_dynamic():
    p = PlumeModel(42)
    p.step(0, 1)
    h0 = [(h.pos, h.radius_km) for h in p.hazards() if h.active][0]
    for t in range(1, 60):
        p.step(t, 1)
    h1 = [(h.pos, h.radius_km) for h in p.hazards() if h.active][0]
    assert dist(h0[0], h1[0]) > 3.0 and h1[1] > h0[1]
    kinds = sorted(h.kind for h in p.hazards() if h.active)
    assert kinds == ['methane', 'methane', 'wildfire', 'wildfire']      # 2nd fire ignites t=25, leaks t=10/35

def test_plume_deterministic():
    a, b = PlumeModel(5), PlumeModel(5)
    for t in range(30):
        a.step(t, 1); b.step(t, 1)
    assert [h.pos for h in a.hazards()] == [h.pos for h in b.hazards()]

def test_sensor_misses_and_false_positives():
    p = PlumeModel(42)
    p.step(0, 1)
    h = p.hazards()[0]
    s = sat(sensor_confidence=0.8)
    hits = fp = 0
    N = 400
    for i in range(N):
        o = p.observe(s, h.pos, 200 + i, f"o{i}")
        hits += any(not d.is_false_positive for d in o.detections)
        fp += any(d.is_false_positive for d in o.detections)
    assert 0.35 * N < hits < 0.95 * N                      # sometimes missed (cloud, pd<1)
    assert 0 < fp < 0.15 * N                               # some false positives, not many

def test_edge_weight():
    assert edge_weight(0, 10) == 1 and edge_weight(10, 10) == 0 and 0 < edge_weight(8.5, 10) < 1


# ---------------------------------------------------------------- leakhunter
def test_box_sum_matches_bruteforce():
    A = np.random.default_rng(0).random((GRID_N, GRID_N))
    S = _box_sum(A, 2)
    for iy, ix in [(0, 0), (10, 20), (49, 49), (25, 3)]:
        ref = A[max(0, iy - 2):iy + 3, max(0, ix - 2):ix + 3].sum()
        assert abs(S[iy, ix] - ref) < 1e-9

def test_positive_detection_raises_belief_near_detection():
    lh = LeakHunter()
    before = lh.grid().copy()
    lh.update(obs((50, 50), [(52, 48)]), 0.0)
    ix, iy = pos_to_cell(52, 48)
    assert lh.grid()[iy, ix] > 50 * before[iy, ix]
    assert lh.grid()[iy, ix] < 0.95                         # one reading is NOT trusted blindly

def test_two_consistent_detections_confirm_one_does_not():
    lh = LeakHunter()
    lh.update(obs((50, 50), [(52, 48)]), 0.0)
    e1 = lh.estimates(0)[0].existence
    lh.update(obs((50, 50), [(51.5, 48.5)], id="o2"), 1.0)
    e2 = lh.estimates(1)[0].existence
    assert e1 < 0.8 < e2

def test_negative_detection_reduces_probability():
    lh = LeakHunter()
    lh.update(obs((50, 50), [(52, 48)]), 0.0)
    ix, iy = pos_to_cell(52, 48)
    p0 = lh.grid()[iy, ix]
    lh.update(obs((52, 48), [], id="o2"), 1.0)
    assert lh.grid()[iy, ix] < 0.5 * p0

def test_false_positive_fades_after_negatives():
    lh = LeakHunter()
    lh.update(obs((50, 50), [(52, 48)]), 0.0)
    for k in range(3):
        lh.predict(1.0); lh.update(obs((52, 48), [], id=f"n{k}", pd_nominal=0.9), 1.0 + k)
    assert not lh.estimates(4) or lh.estimates(4)[0].existence < 0.15

def test_cloudy_negative_is_weak_evidence():
    a, b = LeakHunter(), LeakHunter()
    for lh in (a, b):
        lh.update(obs((50, 50), [(52, 48)]), 0.0)
    a.update(obs((52, 48), [], id="n", visibility=1.0), 1.0)
    b.update(obs((52, 48), [], id="n", visibility=0.1), 1.0)
    ix, iy = pos_to_cell(52, 48)
    assert b.grid()[iy, ix] > 2 * a.grid()[iy, ix]

def test_old_observation_is_less_sharp():
    a, b = LeakHunter(), LeakHunter()
    a.update(obs((50, 50), [(50, 50)], t=10.0), 10.0)       # fresh
    b.update(obs((50, 50), [(50, 50)], t=10.0), 30.0)       # 20 min old
    assert a.estimates(10)[0].uncertainty_km < b.estimates(30)[0].uncertainty_km

def test_multiple_hazards_and_predict_conserves_mass():
    lh = LeakHunter()
    for k in range(2):
        lh.update(obs((20, 20), [(20, 20)], id=f"a{k}"), k)
        lh.update(obs((80, 70), [(80, 70)], id=f"b{k}"), k)
    est = lh.estimates(2)
    assert len(est) == 2 and {round(e.pos[0] / 10) for e in est} == {2, 8}
    m0 = lh.grid().sum()
    lh.predict(1.0)
    assert abs(lh.grid().sum() - m0) / m0 < 0.02
    assert lh.entropy_bits() > 0 and 0.0 <= lh.uncertainty(est) <= 1.0

def test_drone_confirmation_sets_flag():
    lh = LeakHunter()
    lh.update(obs((50, 50), [(50, 50)], id="a"), 0)
    lh.update(obs((50, 50), [(50, 50)], id="b"), 1)
    assert not lh.estimates(1)[0].confirmed
    lh.update(obs((50, 50), [(50, 50)], id="d", source="DRONE", radius_km=1.8, sigma_km=0.15, pd_nominal=0.98,
                  fp_rate=0.002), 2)
    assert lh.estimates(2)[0].confirmed


# ---------------------------------------------------------------- haps
def test_lawnmower_covers_area_in_order():
    lw = LawnmowerPlanner()
    ys = sorted({round(w[1]) for w in lw.wps})
    assert ys[0] < 10 and ys[-1] > 85 and len(ys) >= 7

def test_adaptive_goes_to_high_probability_and_avoids_confirmed():
    pl = AdaptiveHAPSPlanner()
    D = np.full((GRID_N, GRID_N), config.LH_PRIOR)
    X, Y = grid_xy()
    D += 0.3 * np.exp(-((X - 80) ** 2 + (Y - 20) ** 2) / 4)
    wp, _, _ = pl.plan((50.0, 50.0), D, [], 0.0)
    assert dist(wp, (80, 20)) < 12
    conf = Estimate("E", (80.0, 20.0), 1.0, 1.0, 1.0, 0.8, 0.0, True, 0.0, 5)
    pl2 = AdaptiveHAPSPlanner()
    wp2, _, _ = pl2.plan((50.0, 50.0), D, [conf], 1.0)
    assert dist(wp2, (80, 20)) > 10

def test_drone_escalation_rule():
    h = sat(id="H", kind="HAPS"); d = sat(id="D", kind="DRONE", status="IDLE", fuel_kg=70.0, pos=(50, 50))
    e = Estimate("E", (60.0, 60.0), 0.9, 0.8, 2.0, 0.7, 0.0, False, 10.0, 4)
    assert should_dispatch_drone(e, h, d, 15.0)[0]
    e.confirmed = True
    assert not should_dispatch_drone(e, h, d, 15.0)[0]
    e.confirmed, e.existence = False, 0.3
    assert not should_dispatch_drone(e, h, d, 15.0)[0]


# ---------------------------------------------------------------- triage
def world(sats, ests=(), pending=None, conj=None, t=10.0, D=None):
    return WorldView(t, sats, list(ests), D if D is not None else np.full((GRID_N, GRID_N), config.LH_PRIOR),
                     [Asset("T", (80.0, 60.0), 1.0)], conj or {}, pending or {}, {"available": False, "eta_min": 25,
                     "service_min": 15}, [], 150.0)

def test_brain_assigns_observe_to_estimate_with_reason():
    ph = mocks.MockPhysics()
    s = sat(id="SAT-X", pos=(60.0, 40.0), in_view=True)
    e = Estimate("EST-01", (75.0, 55.0), 0.8, 0.7, 2.0, 0.7, 0.0, False, 0.0, 3)
    D = np.full((GRID_N, GRID_N), config.LH_PRIOR)
    X, Y = grid_xy()
    D += 0.8 * np.exp(-((X - 75) ** 2 + (Y - 55) ** 2) / 8)
    ds = TriageBrain(ph).decide(world([s], [e], D=D))
    obs_d = [d for d in ds if d.action.type == ActionType.OBSERVE]
    assert obs_d and obs_d[0].action.target_id == "EST-01"
    assert dist(obs_d[0].action.target, e.pos) < 12            # re-pointed toward the hazard
    assert "SAT-X" in obs_d[0].reason and "fuel" in obs_d[0].reason and len(obs_d[0].reason) > 40
    assert obs_d[0].expected_benefit > 0 and 0 <= obs_d[0].info_gain <= 1

def test_dodge_only_when_worth_it_and_early():
    ph = mocks.MockPhysics()
    s = sat(id="SAT-X", mission_importance=0.8)
    big = Conjunction("SAT-X", "DEB-A", 70.0, 0.10)
    tiny = Conjunction("SAT-X", "DEB-B", 70.0, 0.001)
    brain = TriageBrain(ph)
    ds = brain.decide(world([s], conj={"SAT-X": [big]}, t=10.0))
    assert any(d.action.type == ActionType.DODGE for d in ds)
    ds = brain.decide(world([s], conj={"SAT-X": [tiny]}, t=10.0))
    assert not any(d.action.type == ActionType.DODGE for d in ds)

def test_baseline_dodges_late_with_higher_cost():
    ph = mocks.MockPhysics()
    s = sat(id="SAT-X", debris_risk=0.02)
    c = Conjunction("SAT-X", "DEB-A", 70.0, 0.10)
    d_on = TriageBrain(ph).decide(world([s], conj={"SAT-X": [c]}, t=10.0))
    d_off = BaselinePolicy(ph).decide(world([s], conj={"SAT-X": [c]}, t=62.0))
    on = next(d for d in d_on if d.action.type == ActionType.DODGE)
    off = next(d for d in d_off if d.action.type == ActionType.DODGE)
    assert off.fuel_cost > on.fuel_cost

def test_retire_when_dying_and_downlink_compression():
    ph = mocks.MockPhysics()
    s = sat(id="SAT-X", rul_min=15.0, health=0.1, fuel_kg=0.9, in_contact=True)
    items = [PendingItem(f"i{k}", "SAT-X", float(k), k == 0, 20.0, 0.5 if k == 0 else 0.1, 0.0, (50.0 + k * 0.5, 50.0), 12.0)
             for k in range(5)]
    ds = TriageBrain(ph).decide(world([s], pending={"SAT-X": items}))
    kinds = {d.action.type for d in ds}
    assert ActionType.RETIRE in kinds and ActionType.DOWNLINK in kinds
    dl = next(d for d in ds if d.action.type == ActionType.DOWNLINK)
    assert dl.bandwidth_cost < 5 < sum(i.size_raw_mb for i in items)   # compressed, far below raw 100 MB

def test_worldview_has_no_ground_truth():
    names = {f for f in WorldView.__dataclass_fields__}
    assert "hazards" not in names and "truth" not in names
