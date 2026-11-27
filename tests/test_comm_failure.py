import config
import engine


def test_comm_dead_satellite_is_not_retasked(monkeypatch):
    monkeypatch.setattr(config, "KNOWN_FAILURES", {"SAT-07": {"t": 15, "mode": "communication"}}, raising=False)
    lg = engine.Engine("on", 42, 60).run()
    dead_t = next((f.t for f in lg.frames
                   for s in f.satellites if s.id == "SAT-07" and s.orbit.get("telemetry", {}).get("comm_ok") is False), None)
    assert dead_t is not None, "failure was not injected by physics"
    later = [d for f in lg.frames if f.t > dead_t for d in f.decisions
             if d.action.actor_id == "SAT-07" and d.action.type.value == "OBSERVE"]
    assert not later and lg.meta["completed"]
