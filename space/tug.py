"""tug.py - one shared servicing tug.

Operations: INSPECT, REFUEL, REPAIR, REBOOST. One satellite at a time, travel time
(config.TUG eta_min), service duration, cool-down. The operation set is chosen
from the sat's needs; REFUEL+REPAIR together equals config.TUG["service_min"].
"""
import config
from contracts import Status

# (fraction of service_min, human description)
OP_TIME = {"INSPECT": 0.4, "REFUEL": 0.7, "REPAIR": 0.8, "REBOOST": 0.5}


def plan_ops(s, o: dict) -> list:
    ops = []
    if s.fuel_kg < 0.95 * s.fuel_capacity_kg:
        ops.append("REFUEL")
    if s.health < 0.97 or o.get("sensor_factor", 1.0) < 1.0 or not o.get("prop_ok", True):
        ops.append("REPAIR")
    return ops or ["INSPECT"]


def service_minutes(ops: list) -> float:
    f = 1.0 if {"REFUEL", "REPAIR"} <= set(ops) else max(OP_TIME[x] for x in ops)
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
