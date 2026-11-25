"""Collision Avoidance 2.0: miss-distance evaluation, risk tiers, resource-aware DODGE, outcome recording.

Everything here is the simplified ORBITA model (scripted conjunctions, Gaussian heuristic, phasing burn). These tests
check the logic is consistent and deterministic; they do not validate real orbital collision probabilities.
"""
import copy

import pytest

import config
import engine
import mocks
from brain.triage import BaselinePolicy, TriageBrain
from contracts import ActionType, Conjunction, WorldView
from physics.api import RealPhysics
from space import debris

SAT = "SAT-02"                       # importance 0.8, health 0.9, fuel 1.2 in the default constellation


def make_physics(conjunctions, seed=42):
    """RealPhysics with a custom scripted conjunction list and the default constellation."""
    old = config.CONJUNCTIONS
    config.CONJUNCTIONS = list(conjunctions)
    try:
        ph = RealPhysics()
        sats = engine.build_platforms()
        sats = ph.reset(seed, sats)
    finally:
        config.CONJUNCTIONS = old
    return ph, sats


def sat_of(sats, sid=SAT):
    return next(s for s in sats if s.id == sid)


def view(ph, sats, t, dodged=()):
    conj = {s.id: ph.upcoming_conjunctions(s, t, config.CONJ_FORECAST_MIN) for s in sats if s.kind == "SAT"}
    return WorldView(t, sats, [], None, [], conj, {s.id: [] for s in sats if s.kind == "SAT"},
                     ph.tug_status(t), list(dodged), config.LINK_MB_PER_MIN, 42)


def dodges(decisions):
    return [d for d in decisions if d.action.type == ActionType.DODGE]


def brain_dodges(ph, sats, t, dodged=()):
    brain = TriageBrain(ph)
    v = view(ph, sats, t, dodged)
    return dodges(brain._bus_actions(v))


# ---- risk tier ------------------------------------------------------------------------------ #
def test_tier_thresholds_are_the_documented_ones():
    assert debris.risk_tier(0.0) == "LOW"
    assert debris.risk_tier(debris.RISK_TIER_MEDIUM - 1e-9) == "LOW"
    assert debris.risk_tier(debris.RISK_TIER_MEDIUM) == "MEDIUM"
    assert debris.risk_tier(debris.RISK_TIER_HIGH - 1e-9) == "MEDIUM"
    assert debris.risk_tier(debris.RISK_TIER_HIGH) == "HIGH"
    assert debris.worst_tier([]) == "NONE"


# ---- 1. no conjunction ---------------------------------------------------------------------- #
def test_no_conjunction():
    ph, sats = make_physics([])
    s = sat_of(sats)
    assert ph.assess_conjunction(s, 10.0) == []
    assert debris.worst_tier(ph.assess_conjunction(s, 10.0)) == "NONE"
    assert brain_dodges(ph, sats, 10.0) == []


# ---- 2. low-risk conjunction ---------------------------------------------------------------- #
def test_low_risk_conjunction_is_tiered_low_and_not_dodged():
    ph, sats = make_physics([(SAT, "DEB-LOW", 70, 0.002)])
    s = sat_of(sats)
    a = ph.assess_conjunction(s, 10.0)[0]
    assert a["sat_id"] == SAT and a["debris_id"] == "DEB-LOW"
    assert a["risk_tier"] == "LOW"
    assert a["time_to_tca_min"] == pytest.approx(60.0)
    assert brain_dodges(ph, sats, 10.0) == []                     # not worth the propellant


# ---- 3. high-risk conjunction --------------------------------------------------------------- #
def test_high_risk_conjunction_is_tiered_high_and_dodged_with_record():
    ph, sats = make_physics([(SAT, "DEB-HI", 80, 0.15)])
    s = sat_of(sats)
    a = ph.assess_conjunction(s, 10.0)[0]
    assert a["risk_tier"] == "HIGH" and a["feasible"]
    ds = brain_dodges(ph, sats, 10.0)
    assert len(ds) == 1
    prm = ds[0].action.params
    assert prm["risk_tier"] == "HIGH" and prm["outcome"] == "AVOIDED"
    assert prm["miss_after_km"] > prm["miss_km"]
    assert "Risk tier HIGH" in ds[0].reason and "km after the burn" in ds[0].reason


# ---- 4. successful avoidance (through the real engine) --------------------------------------- #
def test_successful_avoidance_records_miss_fuel_and_improvement(monkeypatch):
    monkeypatch.setattr(config, "CONJUNCTIONS", [(SAT, "DEB-OK", 80, 0.15)])
    eng = engine.Engine("on", seed=42, duration=15)
    fuel0 = eng.sat(SAT).fuel_kg
    log = eng.run()
    ev = [e for f in log.frames for e in f.events if e["type"] == "DODGE"]
    assert len(ev) == 1
    d = ev[0]["data"]
    assert d["executed"] and d["outcome"] == "AVOIDED" and d["improved"] is True
    assert d["predicted_miss_after_km"] > d["predicted_miss_km"]
    assert d["fuel_kg"] == pytest.approx(debris.dodge_fuel_cost(d["lead_min"]))
    assert fuel0 - eng.sat(SAT).fuel_kg == pytest.approx(d["fuel_kg"])          # propellant debited exactly once
    assert log.frames[-1].metrics["dodges"] == 1


# ---- 5. ineffective avoidance ---------------------------------------------------------------- #
def test_ineffective_avoidance_zero_lead_is_flagged_and_skipped_by_brain():
    ph, sats = make_physics([(SAT, "DEB-LATE", 80, 0.15)])
    s = sat_of(sats)
    a = ph.assess_conjunction(s, 80.0)[0]                         # at TCA: no lead time left
    assert a["outcome"] == "INEFFECTIVE" and a["improved"] is False
    assert a["miss_gain_km"] < debris.DODGE_MIN_GAIN_KM
    assert brain_dodges(ph, sats, 80.0) == []                     # brain will not burn for no gain
    r = ph.execute_dodge(s, 80.0, "DEB-LATE")                     # the physics still records what happened if forced
    assert r["executed"] and r["improved"] is False


def test_brain_skips_a_burn_whose_predicted_miss_gain_is_too_small(monkeypatch):
    # 10 min before TCA the burn is worth its fuel to the utility rule and adds ~0.9 km to the miss distance.
    # With a stricter minimum gain (a tunable constant) the evaluated outcome is INEFFECTIVE and the brain holds.
    ph, sats = make_physics([(SAT, "DEB-S", 60, 0.15)])
    s = sat_of(sats)
    assert len(brain_dodges(ph, sats, 50.0)) == 1                 # accepted with the default minimum gain
    monkeypatch.setattr(debris, "DODGE_MIN_GAIN_KM", 1.5)
    a = ph.assess_conjunction(s, 50.0)[0]
    assert a["outcome"] == "INEFFECTIVE" and a["improved"] is False and a["feasible"]
    assert brain_dodges(ph, sats, 50.0) == []                     # the economics did not change, only the evaluation


def test_ineffective_avoidance_when_propulsion_failed(monkeypatch):
    monkeypatch.setattr(config, "CONJUNCTIONS", [(SAT, "DEB-NP", 80, 0.15)])
    eng = engine.Engine("off", seed=42, duration=75)              # baseline would otherwise burn at low risk threshold
    eng.sat(SAT).orbit["prop_ok"] = False
    fuel0 = eng.sat(SAT).fuel_kg
    log = eng.run()
    kinds = [e["type"] for f in log.frames for e in f.events if e["type"].startswith("DODGE")]
    assert "DODGE" not in kinds                                   # no dodge counted
    assert eng.sat(SAT).fuel_kg == pytest.approx(fuel0)            # no propellant spent on a burn that cannot happen
    assert log.frames[-1].metrics["dodges"] == 0


# ---- 6. insufficient fuel -------------------------------------------------------------------- #
def test_insufficient_fuel_is_infeasible_and_brain_does_not_dodge():
    ph, sats = make_physics([(SAT, "DEB-FUEL", 80, 0.15)])
    s = sat_of(sats)
    s.fuel_kg = 0.06                                              # cost ~0.06 kg at 70 min lead; reserve is 0.05 kg
    a = ph.assess_conjunction(s, 10.0)[0]
    assert a["feasible"] is False and a["infeasible_reason"] == "insufficient_fuel"
    assert a["fuel_after_kg"] < config.FUEL_RESERVE_KG
    assert brain_dodges(ph, sats, 10.0) == []


def test_brain_respects_the_physics_feasibility_verdict():
    # Interface contract: if P2 says the burn is infeasible (whatever the reason), the brain must not order it.
    ph, sats = make_physics([(SAT, "DEB-X", 80, 0.15)])
    real = ph.assess_conjunction
    assert len(brain_dodges(ph, sats, 10.0)) == 1
    ph.assess_conjunction = lambda *a, **k: [dict(r, feasible=False, infeasible_reason="propulsion_failed")
                                              for r in real(*a, **k)]
    assert brain_dodges(ph, sats, 10.0) == []


def test_insufficient_fuel_baseline_failure_is_recorded_not_fatal(monkeypatch):
    monkeypatch.setattr(config, "CONJUNCTIONS", [(SAT, "DEB-DRY", 60, 0.15)])
    eng = engine.Engine("off", seed=42, duration=62)
    eng.sat(SAT).fuel_kg = 0.0
    log = eng.run()
    failed = [e for f in log.frames for e in f.events if e["type"] == "DODGE_FAILED"]
    kinds = {e["type"] for f in log.frames for e in f.events}
    assert "DODGE" not in kinds and log.frames[-1].metrics["dodges"] == 0
    assert all(e["data"]["infeasible_reason"] in ("insufficient_fuel", "propulsion_failed") for e in failed if "data" in e)


# ---- 7. multiple conjunctions ----------------------------------------------------------------- #
def test_multiple_conjunctions_are_ranked_by_risk_score():
    ph, sats = make_physics([(SAT, "DEB-A", 60, 0.01), (SAT, "DEB-B", 90, 0.20), (SAT, "DEB-C", 75, 0.05)])
    rows = ph.assess_conjunction(sat_of(sats), 10.0)
    assert [r["debris_id"] for r in rows][0] == "DEB-B"
    scores = [r["risk_score"] for r in rows]
    assert scores == sorted(scores, reverse=True)
    assert {r["sat_id"] for r in rows} == {SAT}
    assert debris.worst_tier(rows) == "HIGH"


# DEB-M0 has the higher collision likelihood (0.10) but DEB-T0 the higher risk score (likelihood x consequence): the
# brain's utility ranks M0 first, so only the fuel reservation can protect the riskier T0 when propellant is scarce.
TWO = [(SAT, "DEB-M0", 60, 0.10), (SAT, "DEB-T0", 85, 0.08)]


def test_scarce_fuel_is_reserved_for_the_riskier_conjunction():
    ph, sats = make_physics(TWO)
    s = sat_of(sats)
    rows = {r["debris_id"]: r for r in ph.assess_conjunction(s, 10.0)}
    assert rows["DEB-T0"]["risk_score"] > rows["DEB-M0"]["risk_score"]
    assert [d.action.target_id for d in brain_dodges(ph, sats, 10.0)] == ["DEB-M0"]      # ample fuel: utility order
    # propellant for exactly one burn above the reserve: the riskier encounter must get it
    s.fuel_kg = config.FUEL_RESERVE_KG + max(r["dodge_fuel_kg"] for r in rows.values()) + 0.005
    assert [d.action.target_id for d in brain_dodges(ph, sats, 10.0)] == ["DEB-T0"]


def test_ample_fuel_dodges_both_conjunctions_one_per_decision_round():
    ph, sats = make_physics(TWO)
    s = sat_of(sats)
    first = brain_dodges(ph, sats, 10.0)
    assert len(first) == 1                                        # one bus action per satellite per minute (existing rule)
    done = (SAT, first[0].action.target_id)
    ph.execute_dodge(s, 10.0, done[1])
    second = brain_dodges(ph, sats, 11.0, dodged=[done])
    assert len(second) == 1 and second[0].action.target_id != done[1]


# ---- 8. BRAIN ON vs BRAIN OFF ------------------------------------------------------------------ #
def _run_dodge_events(monkeypatch, mode):
    monkeypatch.setattr(config, "CONJUNCTIONS", [("SAT-02", "DEB-2210", 70, 0.08), ("SAT-04", "DEB-3341", 100, 0.15)])
    log = engine.run(mode, 42, 105)
    return [e["data"] for f in log.frames for e in f.events if e["type"] == "DODGE"], log


def test_brain_on_vs_off_dodge_quality(monkeypatch):
    on, log_on = _run_dodge_events(monkeypatch, "on")
    off, log_off = _run_dodge_events(monkeypatch, "off")
    assert len(on) == len(off) == 2
    assert min(d["lead_min"] for d in on) > max(d["lead_min"] for d in off)           # ON acts earlier
    assert sum(d["fuel_kg"] for d in on) < sum(d["fuel_kg"] for d in off)             # ... and more cheaply
    assert min(d["predicted_miss_after_km"] / d["miss_sigma_km"] for d in on) >= \
        min(d["predicted_miss_after_km"] / d["miss_sigma_km"] for d in off)
    assert all(d["improved"] for d in on)
    assert log_on.frames[-1].metrics["expected_sat_loss"] < log_off.frames[-1].metrics["expected_sat_loss"]


# ---- determinism, compatibility ----------------------------------------------------------------- #
def test_assessment_is_deterministic_and_read_only():
    ph, sats = make_physics([(SAT, "DEB-D", 80, 0.1)])
    s = sat_of(sats)
    before = (s.fuel_kg, copy.deepcopy(s.orbit.get("maneuvers")), list(s.orbit.get("dodged", [])))
    a1, a2 = ph.assess_conjunction(s, 5.0), ph.assess_conjunction(s, 5.0)
    assert a1 == a2
    assert (s.fuel_kg, s.orbit.get("maneuvers"), list(s.orbit.get("dodged", []))) == before


def test_engine_runs_are_repeatable(monkeypatch):
    a, _ = _run_dodge_events(monkeypatch, "on")
    b, _ = _run_dodge_events(monkeypatch, "on")
    assert a == b


def test_miss_after_grows_with_lead_time():
    prev = 0.0
    for lead in (0, 5, 10, 20, 40, 80):
        after, _ = debris.predicted_miss_after(1.0, lead)
        assert after >= prev
        prev = after
    assert debris.predicted_miss_after(1.0, 60, prop_ok=False)[0] == pytest.approx(1.0)


def test_brain_falls_back_to_original_logic_on_mock_physics():
    ph = mocks.MockPhysics()
    assert not hasattr(ph, "assess_conjunction")
    s = next(x for x in engine.build_platforms() if x.id == SAT)
    brain = TriageBrain(ph)
    big = Conjunction(SAT, "DEB-A", 70.0, 0.10)
    v = WorldView(10.0, [s], [], None, [], {SAT: [big]}, {SAT: []}, {"available": False, "eta_min": 25.0, "service_min": 15.0},
                  [], config.LINK_MB_PER_MIN, 42)
    ds = dodges(brain._bus_actions(v))
    assert len(ds) == 1 and "outcome" not in ds[0].action.params


def test_baseline_policy_unchanged_still_dodges_late():
    ph, sats = make_physics([(SAT, "DEB-B", 70, 0.10)])
    s = sat_of(sats)
    s.debris_risk = 0.02
    ds = dodges(BaselinePolicy(ph).decide(view(ph, sats, 62.0)))
    assert len(ds) == 1 and ds[0].action.params["lead"] == pytest.approx(8.0)
