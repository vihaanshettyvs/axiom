"""At least one standalone test per space module + the integrated demo. Run: python -m pytest -q space/tests"""
import unittest

import config
from contracts import Satellite, Status
from physics.api import RealPhysics
from space import debris, degradation, demo, lastbreath, orbits, retire, tug
from space.tests.test_real import make_sats

SEED = 42


def fresh():
    p = RealPhysics()
    return p, p.reset(SEED, make_sats())


class TestOrbits(unittest.TestCase):
    def test_constellation_of_twelve_is_deterministic_and_unique(self):
        a, b = orbits.make_constellation(12, 7), orbits.make_constellation(12, 7)
        self.assertEqual(a, b)
        self.assertEqual(len({d["id"] for d in a}), 12)
        self.assertEqual(len({round(d["phase"], 3) for d in a}), 12)
        self.assertTrue(all(500 < d["alt_km"] < 600 and d["speed_kms"] > 7 for d in a))

    def test_observation_opportunities_and_windows(self):
        sats = demo.build_sats(12, SEED)
        p = RealPhysics()
        sats = p.reset(SEED, sats)
        ops = p.observation_opportunities(sats, (50.0, 50.0), 0.0, 240.0)
        self.assertTrue(ops)
        self.assertEqual(ops, sorted(ops, key=lambda r: (r["start"], r["sat_id"])))
        self.assertTrue(all(r["duration_min"] >= 0 for r in ops))

    def test_route_change_shifts_phase_and_track(self):
        o = {"A": (0.0, 0.0), "B": (100.0, 0.0), "period": 100.0, "phase": 10.0}
        orbits.apply_route_change(o, 5.0, dphase_min=2.0, dcross_km=10.0)
        self.assertEqual(o["phase"], 12.0)
        self.assertAlmostEqual(o["A"][1], 10.0)          # left of travel (+y for an eastward track)
        self.assertEqual(o["maneuvers"][0]["kind"], "route_change")
        orbits.schedule_route_change(o, 20.0, dphase_min=1.0)
        orbits.apply_due_route_changes(o, 19.0)
        self.assertEqual(o["phase"], 12.0)
        orbits.apply_due_route_changes(o, 20.0)
        self.assertEqual(o["phase"], 13.0)


class TestDebris(unittest.TestCase):
    def test_threat_levels_and_recommendation(self):
        p, sats = fresh()
        s = next(x for x in sats if x.id == "SAT-01")
        p.enc.clear()
        lv = {}
        for level in ("LOW", "MEDIUM", "HIGH"):
            e = p.inject_threat(s, 0.0, level)
            lv[level] = e["p"]
            self.assertGreaterEqual(e["tca"], 35.0)
        self.assertLess(lv["LOW"], lv["MEDIUM"])
        self.assertLess(lv["MEDIUM"], lv["HIGH"])
        recs = {r["debris_id"]: r for r in p.recommend_dodge(s, 0.0)}
        self.assertEqual(len(recs), 3)
        r = max(recs.values(), key=lambda r: r["collision_likelihood"])
        self.assertTrue(r["recommend_dodge"])
        self.assertIn("HEURISTIC", r["disclaimer"])
        self.assertAlmostEqual(r["risk"], r["collision_likelihood"] * r["consequence"])

    def test_threat_generation_is_deterministic(self):
        self.assertEqual(debris.generate_threat(1, "SAT-01", 0.0, "HIGH", 0),
                         debris.generate_threat(1, "SAT-01", 0.0, "HIGH", 0))

    def test_execute_dodge_debits_fuel_and_logs(self):
        p, sats = fresh()
        s = next(x for x in sats if x.id == "SAT-04")          # scripted DEB-3341 at t=120
        f0, ph0 = s.fuel_kg, s.orbit["phase"]
        r = p.execute_dodge(s, 30.0, "DEB-3341", debit_fuel=True)
        self.assertTrue(r["executed"])
        self.assertLess(s.fuel_kg, f0)
        self.assertNotEqual(s.orbit["phase"], ph0)
        self.assertEqual(s.orbit["maneuvers"][-1]["kind"], "collision_avoidance")
        # the deterministic conjunction list is NOT modified by a manoeuvre
        self.assertEqual(len(p.upcoming_conjunctions(s, 0.0, 200)), 1)
        s.orbit["prop_ok"] = False
        self.assertFalse(p.execute_dodge(s, 31.0, "DEB-3341")["executed"])

    def test_relative_state_closes_to_miss_distance(self):
        e = debris.make_encounter(SEED, "SAT-01", "DEB-X", 100.0, 0.05)
        early, at_tca = debris.relative_state(e, 40.0), debris.relative_state(e, 100.0)
        self.assertGreater(early["range_km"], at_tca["range_km"])
        self.assertAlmostEqual(at_tca["range_km"], e["miss_km"])


class TestDegradation(unittest.TestCase):
    def test_communication_failure_blocks_contact_and_exposes_telemetry(self):
        config.KNOWN_FAILURES = {"SAT-01": {"t": 10, "mode": "communication"}}
        try:
            p, sats = fresh()
            for t in range(1, 121):
                p.step(sats, float(t), 1.0)
        finally:
            del config.KNOWN_FAILURES
        s = sats[0]
        tel = s.orbit["telemetry"]
        self.assertFalse(tel["comm_ok"])
        self.assertIn("communication", tel["active_failures"])
        self.assertFalse(s.in_contact)
        self.assertEqual(s.next_contact_min, 999.0)

    def test_all_four_modes_scriptable_and_reproducible(self):
        for mode, key, val in (("battery", "degrade_rate", None), ("propulsion", "prop_ok", False),
                               ("communication", "comm_ok", False), ("sensor", "sensor_factor", 0.3)):
            outs = []
            for _ in range(2):
                p, sats = fresh()
                sats[1].orbit["known_failure"] = {"t": 5, "mode": mode}
                for t in range(1, 11):
                    p.step(sats, float(t), 1.0)
                outs.append((sats[1].health, sats[1].orbit["telemetry"]["failure_severity"]))
                if val is not None:
                    self.assertEqual(sats[1].orbit[key], val, mode)
                else:
                    self.assertGreater(sats[1].orbit[key], 0.002)
            self.assertEqual(outs[0], outs[1])

    def test_battery_tracked_separately_from_health(self):
        p, sats = fresh()
        for t in range(1, 30):
            p.step(sats, float(t), 1.0)
        s = sats[0]
        self.assertLessEqual(s.orbit["battery"], 1.0)
        self.assertLess(s.orbit["battery"], 0.95)


class TestLastBreath(unittest.TestCase):
    def test_outputs_and_comm_loss_retires(self):
        p, sats = fresh()
        s = sats[0]
        p.step(sats, 1.0, 0.0)
        lb = s.orbit["last_breath"]
        for k in ("verdict", "reason", "rul_min", "point_of_no_return_min", "predicted_reentry_days",
                  "orbital_stability", "future_usefulness", "failure_severity", "fuel_kg", "battery"):
            self.assertIn(k, lb)
        self.assertEqual(lb["verdict"], "SAVE")
        s.orbit["comm_ok"] = False
        p.step(sats, 2.0, 0.0)
        lb2 = s.orbit["last_breath"]
        self.assertEqual(lb2["verdict"], "RETIRE")
        self.assertIn("communication", lb2["reason"])
        self.assertIn("passive", lb2["reason"])

    def test_storm_shortens_predicted_reentry_and_life(self):
        p, sats = fresh()
        s = sats[0]
        p.set_space_weather(0.0)
        p.step(sats, 1.0, 0.0)
        quiet = s.orbit["last_breath"]["predicted_reentry_days"]
        p.set_space_weather(1.0)
        p.step(sats, 2.0, 0.0)
        self.assertLess(s.orbit["last_breath"]["predicted_reentry_days"], quiet)


class TestRetire(unittest.TestCase):
    def test_lab_rows_have_frontend_fields(self):
        p, sats = fresh()
        rows = p.retirement_lab(sats[0], 0.0)
        for r in rows:
            for k in ("option", "fuel_kg", "resource_cost", "duration_min", "reentry_days",
                      "effectiveness", "risk", "feasible", "note"):
                self.assertIn(k, r)
        sats[0].orbit["comm_ok"] = False
        rows = {r["option"]: r for r in p.retirement_lab(sats[0], 0.0)}
        self.assertFalse(rows["controlled_deorbit"]["feasible"])
        self.assertTrue(rows["drag_sail"]["feasible"])
        self.assertEqual(p.retirement_options(sats[0], 0.0), [])


class TestTug(unittest.TestCase):
    def test_one_at_a_time_fuel_limit_and_reboost(self):
        p, sats = fresh()
        a, b = sats[0], sats[1]
        a.fuel_kg, b.fuel_kg = 0.2, 0.2
        a.orbit["needs_reboost"] = True
        r = p.request_tug(a, 0.0)
        self.assertTrue(r["accepted"])
        self.assertIn("REBOOST", r["ops"])
        self.assertFalse(p.request_tug(b, 1.0)["accepted"])                   # busy
        p.step(sats, r["complete_t"], 1.0)
        self.assertEqual(a.status, Status.ACTIVE.value)
        self.assertNotIn("needs_reboost", a.orbit)
        left = p.tug_fuel
        t = r["complete_t"] + config.TUG["cooldown_min"] + 1
        self.assertTrue(p.request_tug(b, t)["accepted"])
        self.assertLess(p.tug_fuel, left)
        p.tug_fuel = 0.01                                                      # propellant exhausted
        c = sats[2]
        c.fuel_kg = 0.1
        far = t + 500
        self.assertFalse(p.request_tug(c, far)["accepted"])

    def test_rank_explains_priority(self):
        pick = tug.rank_requests([
            {"sat_id": "SAT-03", "op": "REFUEL", "urgency": 0.3, "mission_value": 0.6, "travel_min": 25},
            {"sat_id": "SAT-08", "op": "REPAIR", "urgency": 0.9, "mission_value": 0.7, "travel_min": 25}])
        self.assertEqual(pick["chosen"], "SAT-08")
        self.assertIn("SAT-03", pick["reason"])


class TestDemo(unittest.TestCase):
    def test_standalone_demo_runs_and_is_reproducible(self):
        a = demo.run(seed=SEED, minutes=120, verbose=False)
        b = demo.run(seed=SEED, minutes=120, verbose=False)
        self.assertEqual(a["events"], b["events"])
        text = "\n".join(a["events"])
        for key in ("THREAT", "DODGE", "FAILURE", "TUG", "SERVICED", "RETIRE"):
            self.assertIn(key, text)
        self.assertEqual(len(a["final"]), 12)


if __name__ == "__main__":
    unittest.main()
