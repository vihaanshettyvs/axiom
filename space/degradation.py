"""degradation.py - satellite wear-out (REAL, prototype fidelity).

Four failure modes:
  1. FUEL         - propellant is spent by dodges/retirement (engine debits fuel_kg);
                    below FUEL_RESERVE the sat is "propulsion-limited".
  2. BATTERY      - steady wear: health -= degrade_rate * radiation_factor(w) * dt
  3. SENSOR       - rare glitch that cuts sensor_factor (default prob 0 = off; config.SENSOR_GLITCH_PROB)
  4. STRUCTURAL / PROPULSION - random shocks (config.SHOCK_PROB) and scripted failures
Randomness: make_rng(seed, "deg", sat_id, int(t)) only. Demo failure time:
config.KNOWN_FAILURES = {"SAT-05": {"t": 60, "mode": "battery"|"sensor"|"structural"|"propulsion"}}
or sat.orbit["known_failure"] = {...}.
"""
import math

import config
from contracts import Status, make_rng
from . import radiation_factor

FUEL_RESERVE_KG = getattr(config, "FUEL_RESERVE_KG", 0.05)


def known_failure(o: dict, sat_id: str):
    return o.get("known_failure") or getattr(config, "KNOWN_FAILURES", {}).get(sat_id)


def step(s, o: dict, seed: int, t: float, dt: float, weather: float) -> None:
    """Advance wear by dt minutes; may set status DEGRADED / DEAD. Mutates s and o."""
    rng = make_rng(seed, "deg", s.id, int(t))
    s.health -= o["degrade_rate"] * radiation_factor(weather) * dt
    if rng.random() < config.SHOCK_PROB:
        s.health -= rng.uniform(0.03, 0.10)               # structural shock
    p_glitch = getattr(config, "SENSOR_GLITCH_PROB", 0.0)
    if p_glitch > 0 and make_rng(seed, "sens", s.id, int(t)).random() < p_glitch:
        o["sensor_factor"] = min(o.get("sensor_factor", 1.0), 0.5)
    kf = known_failure(o, s.id)
    if kf and t >= kf["t"] and not o.get("kf_done"):
        o["kf_done"] = True
        mode = kf.get("mode", "battery")
        if mode == "battery":
            o["degrade_rate"] *= 5.0
        elif mode == "sensor":
            o["sensor_factor"] = 0.3
        elif mode == "structural":
            s.health -= 0.4
        elif mode == "propulsion":
            o["prop_ok"] = False
        o["failure_mode"] = mode
    s.health = max(0.0, s.health)
    if s.health <= 0.02 and s.status in (Status.ACTIVE.value, Status.DEGRADED.value):
        s.status = Status.DEAD.value
    elif s.status == Status.ACTIVE.value and s.health < 0.5:
        s.status = Status.DEGRADED.value
    elif s.status == Status.DEGRADED.value and s.health >= 0.5:
        s.status = Status.ACTIVE.value


def sensor_confidence(s, o: dict) -> float:
    return o["base_conf"] * (0.55 + 0.45 * s.health) * o.get("sensor_factor", 1.0)


def propulsion_ok(s, o: dict) -> bool:
    return o.get("prop_ok", True) and s.fuel_kg > FUEL_RESERVE_KG


def failure_prob(rul_min: float, horizon_min: float = 60.0) -> float:
    return 1.0 - math.exp(-horizon_min / max(rul_min, 1e-6))
