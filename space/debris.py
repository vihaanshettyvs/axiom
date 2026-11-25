"""debris.py - conjunction risk and dodge economics (REAL, prototype fidelity).

SIMPLIFIED PROTOTYPE MODEL - NOT an operational collision-prediction system.

Each scripted conjunction (config.CONJUNCTIONS) is given a physical encounter:
    Pc = P_PEAK * exp(-0.5 * (miss_km / sigma_km)^2)      (2D Gaussian, small hard-body limit)
The miss distance is back-solved from the scripted Pc so every call, and every
seed, reproduces the identical event list (engine requirement #3). Relative
speed, object size and covariance come from make_rng(seed, "deb", debris_id).

    Risk = Pc * consequence,  consequence = importance * (0.5 + 0.5*health) * severity(rel_speed, size)

Dodge economics (along-track phasing): a burn Δv applied `lead` minutes before
TCA shifts the miss by ~3*Δv*t, so required Δv = shift / (3*(lead + arc)).
Fuel follows the rocket equation, hence cost FALLS and effectiveness RISES with lead.
"""
import math

from contracts import Conjunction, make_rng

P_PEAK = 0.5                 # max Pc at zero miss for these covariances (assumed)
DODGE_SHIFT_M = 2400.0       # miss-distance shift the manoeuvre must achieve
SAT_MASS_KG = 200.0
ISP_S = 50.0                 # cold-gas smallsat thruster
G0 = 9.81
THRUSTER_ARC_MIN = 21.0      # effective burn delay: command latency + slew + finite burn
DODGE_FLOOR_KG = 0.0         # calibrated to match the mock curve within ~10% over 0-90 min lead
EFFECT_TAU_MIN = 9.0         # first-order response of achieved shift vs lead


def build_encounters(seed: int, conj_list) -> dict:
    out = {}
    for sat_id, deb_id, tca, p in conj_list:
        rng = make_rng(seed, "deb", deb_id)
        sigma = float(rng.uniform(0.5, 1.0))
        rel_v = float(rng.uniform(7.0, 14.0))
        size = float(rng.uniform(0.05, 0.5))
        p = float(p)
        miss = 0.0 if p >= P_PEAK else sigma * math.sqrt(2.0 * math.log(P_PEAK / p))
        out.setdefault(sat_id, []).append({
            "sat_id": sat_id, "debris_id": deb_id, "tca": float(tca), "p": p,
            "miss_km": miss, "sigma_km": sigma, "rel_speed_kms": rel_v, "size_m": size})
    return out


def upcoming(encs, sat_id: str, t: float, horizon_min: float):
    return [Conjunction(e["sat_id"], e["debris_id"], e["tca"], e["p"])
            for e in encs.get(sat_id, []) if t <= e["tca"] < t + horizon_min]


def instantaneous_risk(evs, t: float, width: float) -> float:
    return max([e["p"] * math.exp(-((t - e["tca"]) / width) ** 2) for e in evs] or [0.0])


def assess(e: dict, importance: float, health: float, t: float) -> dict:
    """Structured result the brain can use to decide whether to dodge."""
    severity = min(1.0, (e["rel_speed_kms"] / 14.0) * (0.4 + e["size_m"]))
    consequence = importance * (0.5 + 0.5 * health) * severity
    return {"debris_id": e["debris_id"], "sat_id": e["sat_id"],
            "relative_speed_kms": e["rel_speed_kms"], "closest_approach_km": e["miss_km"],
            "time_to_closest_approach_min": e["tca"] - t, "collision_probability": e["p"],
            "consequence": consequence, "risk": e["p"] * consequence}


def dodge_fuel_cost(lead_min: float) -> float:
    dv = DODGE_SHIFT_M / (3.0 * (max(lead_min, 0.0) + THRUSTER_ARC_MIN) * 60.0)   # m/s
    return DODGE_FLOOR_KG + SAT_MASS_KG * dv / (ISP_S * G0)


def dodge_effectiveness(lead_min: float) -> float:
    return 1.0 - math.exp(-max(lead_min, 0.0) / EFFECT_TAU_MIN)
