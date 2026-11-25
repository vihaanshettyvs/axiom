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


DISCLAIMER = ("HEURISTIC risk score from a simplified Gaussian model; not a validated orbital "
              "collision probability and not an operational conjunction-assessment tool.")
LEVEL_P = {"LOW": (0.004, 0.02), "MEDIUM": (0.03, 0.08), "HIGH": (0.10, 0.30)}


def make_encounter(seed: int, sat_id: str, deb_id: str, tca: float, p: float) -> dict:
    rng = make_rng(seed, "deb", deb_id)
    sigma = float(rng.uniform(0.5, 1.0))
    rel_v = float(rng.uniform(7.0, 14.0))
    size = float(rng.uniform(0.05, 0.5))
    p = float(p)
    miss = 0.0 if p >= P_PEAK else sigma * math.sqrt(2.0 * math.log(P_PEAK / p))
    return {"sat_id": sat_id, "debris_id": deb_id, "tca": float(tca), "p": p,
            "miss_km": miss, "sigma_km": sigma, "rel_speed_kms": rel_v, "size_m": size}


def build_encounters(seed: int, conj_list) -> dict:
    out = {}
    for sat_id, deb_id, tca, p in conj_list:
        out.setdefault(sat_id, []).append(make_encounter(seed, sat_id, deb_id, tca, p))
    return out


def generate_threat(seed: int, sat_id: str, t_now: float, level: str = "HIGH", serial: int = 0) -> dict:
    """Create an approaching-debris encounter aimed at `sat_id` (deterministic for the arguments).

    TCA is 35-90 min after t_now; Pc is drawn from the LOW / MEDIUM / HIGH band. Register it with
    RealPhysics.inject_threat() (standalone sims / scenario setup). The engine's scripted
    config.CONJUNCTIONS is unaffected unless you call that.
    """
    rng = make_rng(seed, "threat", sat_id, level, serial)
    lo, hi = LEVEL_P[level]
    tca = float(t_now + rng.uniform(35.0, 90.0))
    p = float(rng.uniform(lo, hi))
    deb_id = f"DEB-T{serial:02d}-{int(rng.integers(1000, 9999))}"
    return make_encounter(seed, sat_id, deb_id, tca, p)


def recommend(e: dict, sat, t: float) -> dict:
    """Dodge recommendation + estimated resource cost for one encounter. Heuristic, see DISCLAIMER.

    Dodge if expected loss avoided (risk * effectiveness * LOSS_VALUE) exceeds fuel cost * FUEL_VALUE
    and the satellite can afford the burn (propulsion OK, fuel above reserve).
    """
    import config
    loss_v = getattr(config, "LOSS_VALUE", 400.0)
    fuel_v = getattr(config, "FUEL_VALUE", 60.0)
    reserve = getattr(config, "FUEL_RESERVE_KG", 0.05)
    lead = max(0.0, e["tca"] - t)
    a = assess(e, sat.mission_importance, sat.health, t)
    cost = dodge_fuel_cost(lead)
    eff = dodge_effectiveness(lead) if sat.orbit.get("prop_ok", True) else 0.0
    benefit = a["risk"] * eff * loss_v
    affordable = sat.orbit.get("prop_ok", True) and sat.fuel_kg - cost >= reserve
    do = bool(affordable and benefit > cost * fuel_v)
    why = (f"{'DODGE' if do else 'HOLD'} {sat.id} vs {e['debris_id']}: risk {a['risk']:.3f} "
           f"(likelihood {e['p']:.3f} x consequence {a['consequence']:.2f}), burn {lead:.0f} min before TCA "
           f"costs {cost:.3f} kg and removes {eff:.0%}; benefit {benefit:.1f} vs cost {cost * fuel_v:.1f}"
           + ("" if affordable else "; cannot afford (propulsion/fuel)"))
    return {"debris_id": e["debris_id"], "sat_id": sat.id, "threatened": sat.id, "tca": e["tca"],
            "lead_min": lead, "risk": a["risk"], "collision_likelihood": e["p"],
            "consequence": a["consequence"], "recommend_dodge": do, "dodge_fuel_kg": cost,
            "dodge_effectiveness": eff, "residual_likelihood": e["p"] * (1.0 - eff),
            "benefit": benefit, "cost": cost * fuel_v, "reason": why, "disclaimer": DISCLAIMER}


def upcoming(encs, sat_id: str, t: float, horizon_min: float):
    return [Conjunction(e["sat_id"], e["debris_id"], e["tca"], e["p"])
            for e in encs.get(sat_id, []) if t <= e["tca"] < t + horizon_min]


def instantaneous_risk(evs, t: float, width: float) -> float:
    return max([e["p"] * math.exp(-((t - e["tca"]) / width) ** 2) for e in evs] or [0.0])


def assess(e: dict, importance: float, health: float, t: float) -> dict:
    """Structured result the brain can use to decide whether to dodge."""
    severity = min(1.0, (e["rel_speed_kms"] / 14.0) * (0.4 + e["size_m"]))
    consequence = importance * (0.5 + 0.5 * health) * severity
    return {"debris_id": e["debris_id"], "sat_id": e["sat_id"], "disclaimer": DISCLAIMER,
            "relative_speed_kms": e["rel_speed_kms"], "closest_approach_km": e["miss_km"],
            "time_to_closest_approach_min": e["tca"] - t, "collision_probability": e["p"],
            "consequence": consequence, "risk": e["p"] * consequence}


def relative_state(e: dict, t: float) -> dict:
    """Debris position relative to its target satellite (straight-line relative motion).

    Along-track separation closes at the encounter's relative speed and reaches zero at TCA;
    cross-track offset is the miss distance. Used for explainability and visualisation only.
    -> {along_km, cross_km, range_km, closing_speed_kms, time_to_tca_min}
    """
    along = e["rel_speed_kms"] * 60.0 * (e["tca"] - t)
    rng_km = (along ** 2 + e["miss_km"] ** 2) ** 0.5
    return {"debris_id": e["debris_id"], "sat_id": e["sat_id"], "along_km": along,
            "cross_km": e["miss_km"], "range_km": rng_km,
            "closing_speed_kms": e["rel_speed_kms"] if t <= e["tca"] else -e["rel_speed_kms"],
            "time_to_tca_min": e["tca"] - t}


def dodge_fuel_cost(lead_min: float) -> float:
    dv = DODGE_SHIFT_M / (3.0 * (max(lead_min, 0.0) + THRUSTER_ARC_MIN) * 60.0)   # m/s
    return DODGE_FLOOR_KG + SAT_MASS_KG * dv / (ISP_S * G0)


def dodge_effectiveness(lead_min: float) -> float:
    return 1.0 - math.exp(-max(lead_min, 0.0) / EFFECT_TAU_MIN)
