"""Tests the AUDITOR itself on tiny hand-made RunLog dicts (not a simulation, not an engine result)."""
import json
import os
import tempfile
import unittest

from space.tests import audit_runlog


def sat(i, status="ACTIVE", fuel=1.0, pos=(0, 0), **orb):
    return {"id": i, "kind": "SAT", "status": status, "fuel_kg": fuel, "health": 0.8, "pos": list(pos),
            "in_view": True, "orbit": orb}


def write(frames):
    fd, p = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w") as fh:
        json.dump({"frames": frames, "meta": {}, "scenario": {}}, fh)
    return p


class TestAuditor(unittest.TestCase):
    def test_downlink_while_retiring_is_allowed_but_observe_is_not(self):
        dec = lambda t, typ: {"action": {"type": typ, "actor_id": "S1"}, "reason": "x", "t": t}
        base = lambda t, status, decs, x: {"t": t, "satellites": [sat("S1", status=status, pos=(x, 0))],
                                           "decisions": decs, "events": []}
        ok = [base(0, "RETIRING", [], 0), base(1, "RETIRING", [dec(1, "DOWNLINK")], 1),
              base(2, "RETIRED", [], 2)]
        self.assertEqual(audit_runlog.audit(write(ok))["fails"], [])
        bad = [base(0, "RETIRING", [], 0), base(1, "RETIRING", [dec(1, "OBSERVE")], 1),
               base(2, "RETIRED", [dec(2, "DOWNLINK")], 2)]
        self.assertIn("after retirement", " | ".join(audit_runlog.audit(write(bad))["fails"]))

    def test_clean_log_passes(self):
        fr = [{"t": 0, "satellites": [sat("S1", pos=(0, 0))], "decisions": [], "events": []},
              {"t": 1, "satellites": [sat("S1", pos=(1, 0))], "decisions": [], "events": []}]
        self.assertEqual(audit_runlog.audit(write(fr))["fails"], [])

    def test_detects_bad_cases(self):
        dec = lambda t, typ, actor, reason="x": {"action": {"type": typ, "actor_id": actor}, "reason": reason, "t": t}
        fr = [{"t": 0, "satellites": [sat("S1", pos=(0, 0)), sat("S2", status="SERVICING"), sat("S3", status="SERVICING")],
               "decisions": [dec(0, "RETIRE", "S1"), dec(0, "RETIRE", "S1", reason="")], "events": []},
              {"t": 1, "satellites": [sat("S1", status="RETIRED", fuel=-0.1, pos=(1, 0)), sat("S2"), sat("S3")],
               "decisions": [], "events": []},
              {"t": 2, "satellites": [sat("S1", status="ACTIVE", pos=(2, 0)), sat("S2"), sat("S3")],
               "decisions": [dec(2, "OBSERVE", "S1")], "events": []}]
        text = " | ".join(audit_runlog.audit(write(fr))["fails"])
        for needle in ("simultaneously", "empty reason", "negative fuel_kg", "after retirement",
                       "repeated RETIRE", "came back to life"):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
