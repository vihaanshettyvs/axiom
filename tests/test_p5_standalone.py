from types import SimpleNamespace
from baseline.policies_off import decide_off
from eval.metrics import compute_metrics

def test_p5():
    s1 = SimpleNamespace(id="s1", fuel=100.0, collision_prob=0.12, has_detection=False, status="active")
    s2 = SimpleNamespace(id="s2", fuel=80.0, collision_prob=0.0, has_detection=True, status="debris")
    dec = decide_off(SimpleNamespace(time_min=10, satellites=[s1, s2], haps=SimpleNamespace(id="h1")))
    assert len(dec) == 3 and dec[1]["action"] == "DODGE" and dec[2]["action"] == "DOWNLINK_RAW"
    log = SimpleNamespace(frames=[SimpleNamespace(time_min=0, satellites=[s1, s2], bytes_sent=500), SimpleNamespace(time_min=15, satellites=[s1, s2], bytes_sent=1200, leak_localized=True, fire_detected=True)])
    r = compute_metrics(log)
    assert r["leak_localization_min"] == 15 and r["total_bytes_sent"] == 1700 and r["uncontrolled_debris"] == 1
