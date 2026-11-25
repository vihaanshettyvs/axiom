"""degradation.py - satellite wear-out (REAL, prototype fidelity).

Failure modes (all seeded; all optional random modes default to probability 0):
  1. BATTERY       - steady wear: health and orbit["battery"] fall by degrade_rate * radiation(w) * dt
  2. PROPULSION    - orbit["prop_ok"] = False (config.PROP_FAIL_PROB or scripted): no dodges, no burns
  3. COMMUNICATION - orbit["comm_ok"] = False (config.COMM_FAIL_PROB or scripted): in_contact forced False
  4. SENSOR        - orbit["sensor_factor"] cut (config.SENSOR_GLITCH_PROB or scripted)
  plus structural shocks (config.SHOCK_PROB) and fuel depletion (engine debits fuel_kg;
  below FUEL_RESERVE the sat is propulsion-limited).
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
    wear = o["degrade_rate"] * radiation_factor(weather) * dt
    s.health -= wear
    o["battery"] = max(0.0, o.get("battery", s.health + wear) - wear)   # battery wears, but is not hit by shocks
    if rng.random() < config.SHOCK_PROB:
        s.health -= rng.uniform(0.03, 0.10)               # structural shock
    p_glitch = getattr(config, "SENSOR_GLITCH_PROB", 0.0)
    if p_glitch > 0 and make_rng(seed, "sens", s.id, int(t)).random() < p_glitch:
        o["sensor_factor"] = min(o.get("sensor_factor", 1.0), 0.5)
    p_comm = getattr(config, "COMM_FAIL_PROB", 0.0)
    if p_comm > 0 and make_rng(seed, "comm", s.id, int(t)).random() < p_comm:
        o["comm_ok"] = False
    p_prop = getattr(config, "PROP_FAIL_PROB", 0.0)
    if p_prop > 0 and make_rng(seed, "prop", s.id, int(t)).random() < p_prop:
        o["prop_ok"] = False
    kf = known_failure(o, s.id)
    if kf and t >= kf["t"] and not o.get("kf_done"):
        o["kf_done"] = True
        mode = kf.get("mode", "battery")
        if mode == "battery":
            o["degrade_rate"] *= 5.0
            o["battery"] = max(0.0, o.get("battery", s.health) - 0.2)
        elif mode == "sensor":
            o["sensor_factor"] = 0.3
        elif mode == "structural":
            s.health -= 0.4
        elif mode == "propulsion":
            o["prop_ok"] = False
        elif mode in ("communication", "comm"):
            o["comm_ok"] = False
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


def failure_severity(o: dict) -> float:
    """0 (nominal) .. 1 (crippled): propulsion lost 0.5, comms lost 0.35, sensor loss up to 0.25."""
    return min(1.0, 0.5 * (not o.get("prop_ok", True)) + 0.35 * (not o.get("comm_ok", True))
               + 0.25 * (1.0 - o.get("sensor_factor", 1.0)))


def active_failures(o: dict) -> list:
    out = []
    if not o.get("prop_ok", True):
        out.append("propulsion")
    if not o.get("comm_ok", True):
        out.append("communication")
    if o.get("sensor_factor", 1.0) < 1.0:
        out.append("sensor")
    if o.get("failure_mode") == "battery" or o.get("battery", 1.0) < 0.3:
        out.append("battery")
    return out


def telemetry(s, o: dict) -> dict:
    """Flat telemetry block the engine/brain may read (also stored in sat.orbit['telemetry'])."""
    return {"fuel_kg": s.fuel_kg, "fuel_frac": s.fuel_kg / max(s.fuel_capacity_kg, 1e-9),
            "battery": o.get("battery", s.health), "health": s.health,
            "sensor_performance": o.get("sensor_factor", 1.0), "sensor_confidence": s.sensor_confidence,
            "comm_ok": o.get("comm_ok", True), "propulsion_ok": o.get("prop_ok", True),
            "failure_severity": failure_severity(o), "active_failures": active_failures(o),
            "failure_prob_60m": o.get("failure_prob_60m", 0.0)}


def failure_prob(rul_min: float, horizon_min: float = 60.0) -> float:
    return 1.0 - math.exp(-horizon_min / max(rul_min, 1e-6))
