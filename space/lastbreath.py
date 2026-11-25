"""lastbreath.py - remaining useful life, point of no return, SAVE / WAIT / RETIRE.

SIMPLIFIED PROTOTYPE MODEL. Inputs: fuel, health (battery/structure wear), orbital
stability (decay lifetime under current space weather), mission importance.

  rul_min          = min( health / (wear_rate * radiation(w) + shock_rate),  orbital_life_min )
  point of no return = last minute a controlled retirement can still start and finish:
                       rul - duration(cheapest affordable option) - SAFETY ; 0 if none affordable.
  verdict thresholds scale with importance: important sats are kept longer.
"""
from functools import lru_cache

import config
from . import NOMINAL_ALT_KM, clamp01, decay_lifetime_days, radiation_factor
from .degradation import active_failures, failure_severity
from .retire import CD, SAT_AREA_M2, SAT_MASS_KG

SAFETY_MIN = 5.0


@lru_cache(maxsize=512)
def _natural_life_days(alt_km: float, weather: float) -> float:
    return decay_lifetime_days(alt_km, CD * SAT_AREA_M2 / SAT_MASS_KG, weather, mass_kg=SAT_MASS_KG)


def predicted_reentry_days(o: dict, weather: float) -> float:
    """Natural (do-nothing) decay time from the current altitude at this space-weather index."""
    return _natural_life_days(round(float(o.get("alt_km", NOMINAL_ALT_KM)), 1), round(float(weather), 3))


def rul_min(s, o: dict, weather: float) -> float:
    rate = o["degrade_rate"] * radiation_factor(weather) + config.SHOCK_PROB * 0.065 + 1e-9
    health_rul = s.health / rate
    return min(health_rul, predicted_reentry_days(o, weather) * 1440.0)


def assess(s, o: dict, weather: float, options: list) -> dict:
    rul = s.rul_min
    thr = config.RETIRE_RUL_MIN * (2.0 - s.mission_importance)
    dur = min((x["duration_min"] for x in options), default=None)
    ponr = max(0.0, rul - dur - SAFETY_MIN) if dur is not None else 0.0
    urgency = clamp01(1.0 - (rul - thr) / (6.0 * thr))
    severity = failure_severity(o)
    failures = active_failures(o)
    usefulness = s.mission_importance * min(1.0, rul / (6.0 * thr)) * (1.0 - severity)
    if not o.get("comm_ok", True):
        usefulness *= 0.1          # data cannot reach the ground, so little mission value remains
    if options:
        fuel_note = f"controlled retirement still possible for {ponr:.0f} more min"
    elif not o.get("comm_ok", True):
        fuel_note = "no command link, so only passive disposal is possible"
    elif not o.get("prop_ok", True):
        fuel_note = "propulsion has failed, so no controlled maneuver is possible"
    else:
        fuel_note = "propulsion reserves are insufficient for safe maneuvering"
    crippled = severity >= 0.35 and usefulness < 0.1       # e.g. no downlink: data cannot reach the ground
    if rul <= thr or (not options and s.health < 0.5) or crippled:
        verdict = "RETIRE"
        why = (f"{fuel_note}, and remaining useful life is {rul:.0f} min "
               f"(limit {thr:.0f} min at importance {s.mission_importance:.1f})")
        if crippled:
            why += f"; failures ({', '.join(failures)}) leave little future usefulness ({usefulness:.2f})"
    elif rul <= 4.0 * thr or s.health < 0.6 or severity >= 0.5:
        verdict = "WAIT"
        why = (f"health {s.health:.2f} and {rul:.0f} min of life left: not yet at the limit, "
               f"re-check as telemetry arrives ({fuel_note})")
        if failures:
            why += f"; impaired by {', '.join(failures)}"
    else:
        verdict = "SAVE"
        why = f"healthy ({s.health:.2f}) with {rul:.0f} min of useful life; {fuel_note}"
    return {"verdict": verdict, "reason": f"{verdict} {s.id}: {why}.", "rul_min": rul,
            "point_of_no_return_min": ponr, "urgency": urgency,
            "predicted_reentry_days": predicted_reentry_days(o, weather),
            "fuel_kg": s.fuel_kg, "battery": o.get("battery", s.health), "health": s.health,
            "orbital_stability": clamp01(1.0 - min(1.0, 30.0 / max(predicted_reentry_days(o, weather), 1e-6))),
            "mission_importance": s.mission_importance, "failure_severity": severity,
            "active_failures": failures, "future_usefulness": usefulness,
            "failure_prob_60m": 1.0 - 2.718281828 ** (-60.0 / max(rul, 1e-6)),
            "options_available": [x["name"] for x in options]}
