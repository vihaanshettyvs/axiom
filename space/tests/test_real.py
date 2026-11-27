"""Tests for RealPhysics (pytest or unittest). Run from the repo root:  python -m pytest -q space/tests"""
import copy
import unittest

import config
from contracts import Satellite, Status
from physics.api import RealPhysics
from space import decay_lifetime_days, density

SEED = 42


def make_sats():
    sats = []
    for d in config.SATELLITES:
        sats.append(Satellite(
            id=d["id"], kind="SAT", fuel_kg=d["fuel"], fuel_capacity_kg=config.SAT_FUEL_CAPACITY,
            health=d["health"], mission_importance=d["importance"], sensor_radius_km=12.0, slew_km=22.0,
            orbit=dict(A=d["A"], B=d["B"], period=d["period"], phase=d["phase"],
                       base_conf=0.8, degrade_rate=d["degrade"])))
    sats.append(Satellite(id="TUG-1", kind="TUG", status=Status.IDLE.value, orbit={"park": (0.0, -30.0)}))
    return sats


def run(phys, sats, n=180):
    sats = phys.reset(SEED, sats)
    for t in range(1, n + 1):
        phys.step(sats, float(t), 1.0)
    return sats


class TestRealPhysics(unittest.TestCase):
    def test_parity_with_mock(self):
        try:
            from mocks import MockPhysics
        except Exception:
            self.skipTest("mocks.py not importable")
        a, b = RealPhysics(), MockPhysics()
        sa, sb = a.reset(SEED, make_sats()), b.reset(SEED, make_sats())
        for t in range(1, 181):
            a.step(sa, float(t), 1.0)
            b.step(sb, float(t), 1.0)
            for x, y in zip(sa, sb):
                if x.kind != "SAT":
                    continue
                self.assertEqual(x.status, y.status, (t, x.id))
                for f in ("pos", "vel"):
                    self.assertEqual(getattr(x, f), getattr(y, f))
                for f in ("health", "sensor_confidence", "rul_min", "debris_risk", "view_left_min",
                          "next_view_min", "next_contact_min"):
                    self.assertAlmostEqual(getattr(x, f), getattr(y, f), 9, (t, x.id, f))
                self.assertEqual((x.in_view, x.in_contact), (y.in_view, y.in_contact))
        for s in sa:
            if s.kind == "SAT":
                self.assertEqual(a.coverage_windows(s, 0.0, 120), b.coverage_windows(s, 0.0, 120))
                self.assertEqual(a.upcoming_conjunctions(s, 0.0, 200), b.upcoming_conjunctions(s, 0.0, 200))

    def test_deterministic(self):
        r1 = [(s.health, s.status) for s in run(RealPhysics(), make_sats())]
        r2 = [(s.health, s.status) for s in run(RealPhysics(), make_sats())]
        self.assertEqual(r1, r2)

    def test_conjunction_report(self):
        p = RealPhysics()
        sats = p.reset(SEED, make_sats())
        s4 = next(s for s in sats if s.id == "SAT-04")
        rep = p.conjunction_reports(s4, 0.0)[0]
        self.assertAlmostEqual(rep["collision_probability"], 0.15)
        self.assertAlmostEqual(rep["risk"], rep["collision_probability"] * rep["consequence"])
        self.assertGreater(rep["relative_speed_kms"], 5)
        self.assertGreaterEqual(rep["closest_approach_km"], 0)

    def test_dodge_monotonic(self):
        p, s = RealPhysics(), make_sats()[0]
        costs = [p.dodge_fuel_cost(s, l) for l in (0, 10, 30, 60, 90)]
        effs = [p.dodge_effectiveness(s, l) for l in (0, 10, 30, 60, 90)]
        self.assertEqual(costs, sorted(costs, reverse=True))
        self.assertEqual(effs, sorted(effs))
        self.assertAlmostEqual(costs[0], 0.26, 2)
        s.orbit["prop_ok"] = False
        self.assertEqual(p.dodge_effectiveness(s, 60), 0.0)

    def test_retirement_options(self):
        p = RealPhysics()
        sats = p.reset(SEED, make_sats())
        s = next(x for x in sats if x.id == "SAT-05")
        names = [o["name"] for o in p.retirement_options(s, 0.0)]
        self.assertEqual(names, ["controlled_deorbit", "graveyard_orbit"])
        s.fuel_kg = 0.1
        self.assertEqual(p.retirement_options(s, 0.0), [])
        lab = {r["option"]: r for r in p.retirement_lab(next(x for x in sats if x.id == "SAT-01"), 0.0)}
        self.assertEqual(set(lab), {"controlled_deorbit", "drag_sail", "edt_tether", "do_nothing"})
        self.assertAlmostEqual(lab["controlled_deorbit"]["fuel_kg"], 0.30, 2)

    def test_space_weather_changes_decay_and_life(self):
        p = RealPhysics()
        sats = p.reset(SEED, make_sats())
        s = next(x for x in sats if x.id == "SAT-01")
        quiet = {r["option"]: r["reentry_days"] for r in (p.set_space_weather(0.0) or p.retirement_lab(s, 0.0))}
        storm = {r["option"]: r["reentry_days"] for r in (p.set_space_weather(1.0) or p.retirement_lab(s, 0.0))}
        for k in ("drag_sail", "edt_tether", "do_nothing"):
            self.assertLess(storm[k], quiet[k], k)
        self.assertGreater(density(550, 1.0), density(550, 0.0))
        self.assertLess(decay_lifetime_days(550, 0.01, 1.0), decay_lifetime_days(550, 0.01, 0.0))
        p.set_space_weather(0.5)
        p.step(sats, 1.0, 1.0)
        r_nom = s.rul_min
        p.set_space_weather(1.0)
        p.step(sats, 2.0, 0.0)
        self.assertLess(s.rul_min, r_nom)

    def test_last_breath(self):
        p = RealPhysics()
        sats = p.reset(SEED, make_sats())
        s = next(x for x in sats if x.id == "SAT-05")
        s.fuel_kg, s.health = 0.05, 0.12
        p.step(sats, 1.0, 0.0)
        lb = s.orbit["last_breath"]
        self.assertEqual(lb["verdict"], "RETIRE")
        self.assertIn("SAT-05", lb["reason"])
        self.assertEqual(lb["point_of_no_return_min"], 0.0)
        good = next(x for x in sats if x.id == "SAT-01")
        self.assertEqual(good.orbit["last_breath"]["verdict"], "SAVE")

    def test_tug_servicing_and_contention(self):
        p = RealPhysics()
        sats = p.reset(SEED, make_sats())
        s3 = next(x for x in sats if x.id == "SAT-03")
        s8 = next(x for x in sats if x.id == "SAT-05")
        r = p.request_tug(s3, 10.0)
        self.assertTrue(r["accepted"])
        self.assertFalse(p.request_tug(s8, 11.0)["accepted"])        # one tug at a time
        self.assertFalse(p.tug_status(11.0)["available"])
        f0, h0 = s3.fuel_kg, s3.health
        p.step(sats, r["arrival_t"], 1.0)
        self.assertEqual(s3.status, Status.SERVICING.value)
        p.step(sats, r["complete_t"], 1.0)
        self.assertEqual(s3.status, Status.ACTIVE.value)
        self.assertTrue(s3.orbit["serviced"])
        self.assertGreater(s3.fuel_kg, f0 + 0.9)
        self.assertGreater(s3.health, h0)
        self.assertFalse(p.tug_status(r["complete_t"] + 1)["available"])   # cool-down
        self.assertTrue(p.tug_status(r["complete_t"] + 61)["available"])
        pick = p.tug_rank([
            {"sat_id": "SAT-03", "op": "REFUEL", "urgency": 0.4, "mission_value": 0.9, "travel_min": 25},
            {"sat_id": "SAT-08", "op": "REPAIR", "urgency": 0.95, "mission_value": 0.5, "travel_min": 25}])
        self.assertEqual(pick["chosen"], "SAT-08")

    def test_known_failure_and_death(self):
        config.KNOWN_FAILURES = {"SAT-01": {"t": 20, "mode": "battery"}}
        try:
            sats = run(RealPhysics(), make_sats(), 40)
        finally:
            del config.KNOWN_FAILURES
        s1 = next(x for x in sats if x.id == "SAT-01")
        self.assertEqual(s1.orbit["failure_mode"], "battery")
        p = RealPhysics()
        sats = p.reset(SEED, make_sats())
        d = sats[0]
        d.health = 0.015
        p.step(sats, 1.0, 1.0)
        self.assertEqual(d.status, Status.DEAD.value)

    def test_retire_completion(self):
        p = RealPhysics()
        sats = p.reset(SEED, make_sats())
        s = sats[0]
        s.status = Status.RETIRING.value
        s.orbit["retire_done_t"] = 5.0
        p.step(sats, 4.0, 1.0)
        self.assertEqual(s.status, Status.RETIRING.value)
        p.step(sats, 5.0, 1.0)
        self.assertEqual(s.status, Status.RETIRED.value)


if __name__ == "__main__":
    unittest.main()
