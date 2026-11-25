"""tug.py - one shared servicing tug.

Operations: INSPECT, REFUEL, REPAIR, REBOOST. One satellite at a time, travel time
(config.TUG eta_min), service duration, cool-down. The operation set is chosen
from the sat's needs; REFUEL+REPAIR together equals config.TUG["service_min"].
"""
import config
from contracts import Status

# Fraction of config.TUG["service_min"] each operation takes.
OP_TIME = {"INSPECT": 0.4, "REFUEL": 0.7, "REPAIR": 0.8, "REBOOST": 0.5}
# Tug's own propellant per operation (kg). The tug has TUG_FUEL_KG in total, so it is a consumable resource.
OP_FUEL_KG = {"INSPECT": 0.05, "REFUEL": 0.30, "REPAIR": 0.25, "REBOOST": 0.20}
TUG_FUEL_KG = 1.5
REBOOST_ALT_GAIN_KM = 50.0
REBOOST_BELOW_ALT_KM = 500.0     # drag has pulled the orbit this low -> boost it back up
NOMINAL_ALT_KM = 550.0


def plan_ops(s, o: dict) -> list:
    ops = []
    if s.fuel_kg < 0.95 * s.fuel_capacity_kg:
        ops.append("REFUEL")
    if s.health < 0.97 or o.get("sensor_factor", 1.0) < 1.0 or not o.get("prop_ok", True):
        ops.append("REPAIR")
    if o.get("needs_reboost") or o.get("alt_km", NOMINAL_ALT_KM) < REBOOST_BELOW_ALT_KM:
        ops.append("REBOOST")
    return ops or ["INSPECT"]


def fuel_cost(ops: list) -> float:
    return sum(OP_FUEL_KG[x] for x in ops)


def service_minutes(ops: list) -> float:
    f = 1.0 if {"REFUEL", "REPAIR"} <= set(ops) else max(OP_TIME[x] for x in ops)
    if len(ops) > 2:
        f += 0.3 * (len(ops) - 2)          # extra operations lengthen the visit
    return config.TUG["service_min"] * f


def can_accept(s) -> bool:
    return (s.kind == "SAT" and s.status in (Status.ACTIVE.value, Status.DEGRADED.value)
            and "tug_arrival_t" not in s.orbit)


def update_servicing(s, o: dict, t: float) -> None:
    """Between arrival and done: SERVICING. On completion: apply the planned ops."""
    if "tug_arrival_t" not in o:
        return
    if o["tug_arrival_t"] <= t < o["tug_done_t"]:
        s.status = Status.SERVICING.value
    elif t >= o["tug_done_t"]:
        ops = o.get("tug_ops", ["REFUEL", "REPAIR"])
        if "REFUEL" in ops:
            s.fuel_kg = min(s.fuel_capacity_kg, s.fuel_kg + config.TUG["fuel_gain_kg"])
        if "REPAIR" in ops:
            s.health = min(1.0, s.health + config.TUG["health_gain"])
            o["degrade_rate"] *= 0.5
            o["sensor_factor"] = 1.0
            o["prop_ok"] = True
            o["battery"] = min(1.0, o.get("battery", s.health) + config.TUG["health_gain"])
        if "REBOOST" in ops:
            o["alt_km"] = min(NOMINAL_ALT_KM, o.get("alt_km", NOMINAL_ALT_KM) + REBOOST_ALT_GAIN_KM)
            o.pop("needs_reboost", None)
        s.status = Status.ACTIVE.value
        o["serviced"] = True
        o["serviced_ops"] = ops
        for k in ("tug_arrival_t", "tug_done_t", "tug_ops"):
            o.pop(k, None)


def rank_requests(requests: list) -> dict:
    """Competing requests -> who goes first and why.
    requests: [{sat_id, op, urgency 0..1, mission_value 0..1, travel_min}]"""
    if not requests:
        return {"chosen": None, "queue": [], "reason": "no requests"}
    score = lambda r: 0.6 * r["urgency"] + 0.4 * r["mission_value"] - 0.002 * r.get("travel_min", 0.0)
    order = sorted(requests, key=lambda r: -score(r))
    top, rest = order[0], order[1:]
    why = (f"{top['sat_id']} {top['op']} first (urgency {top['urgency']:.2f}, mission value "
           f"{top['mission_value']:.2f}); deferred: " + (", ".join(r["sat_id"] for r in rest) or "none"))
    return {"chosen": top["sat_id"], "queue": [r["sat_id"] for r in rest], "reason": why + "."}
