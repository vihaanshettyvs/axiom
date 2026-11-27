"""End-to-end check of the demo scenario on the real modules (seed 2, 130 min)."""
import validate_demo
import engine


def test_demo_scenario_sequence_and_validity():
    lg = engine.Engine("on", 2, 130).run()
    ev = [(e["type"], e["actor"], f.t) for f in lg.frames for e in f.events]
    types = {t for t, _, _ in ev}
    assert {"DODGE", "REASSIGN", "RETIRE", "RETIRED", "TUG_REQUEST", "SERVICED", "DISPATCH_DRONE", "ALERT"} <= types
    assert sum(1 for t, _, _ in ev if t == "TUG_REQUEST") == 2                      # SAT-03 first, SAT-10 queued behind it
    retire = next(e for f in lg.frames for e in f.events if e["type"] == "RETIRE")
    assert all(m in retire["msg"] for m in ("controlled_deorbit", "drag_sail", "edt_tether"))   # options were compared
    assert {h["source"] for h in lg.scenario["hazards"]} == {"SIMULATED"}           # no real FIRMS data in this build
    assert all(d.reason.strip() for f in lg.frames for d in f.decisions)
    assert validate_demo.audit(lg)["total"] == 0
    assert lg.meta["completed"] and len(lg.frames) == 130
