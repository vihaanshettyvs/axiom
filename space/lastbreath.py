"""lastbreath.py - remaining useful life, point of no return, SAVE / WAIT / RETIRE.

SIMPLIFIED PROTOTYPE MODEL. Inputs: fuel, health (battery/structure wear), orbital
stability (decay lifetime under current space weather), mission importance.

  rul_min          = min( health / (wear_rate * radiation(w) + shock_rate),  orbital_life_min )
  point of no return = last minute a controlled retirement can still start and finish:
                       rul - duration(cheapest affordable option) - SAFETY ; 0 if none affordable.
  verdict thresholds scale with importance: important sats are kept longer.
"""
import config
from . import NOMINAL_ALT_KM, clamp01, decay_lifetime_days, radiation_factor
from .retire import CD, SAT_AREA_M2, SAT_MASS_KG

SAFETY_MIN = 5.0


def rul_min(s, o: dict, weather: float) -> float:
    rate = o["degrade_rate"] * radiation_factor(weather) + config.SHOCK_PROB * 0.065 + 1e-9
    health_rul = s.health / rate
    orbital = decay_lifetime_days(o.get("alt_km", NOMINAL_ALT_KM), CD * SAT_AREA_M2 / SAT_MASS_KG,
                                  weather, mass_kg=SAT_MASS_KG) * 1440.0
    return min(health_rul, orbital)


def assess(s, o: dict, weather: float, options: list) -> dict:
    rul = s.rul_min
    thr = config.RETIRE_RUL_MIN * (2.0 - s.mission_importance)
    dur = min((x["duration_min"] for x in options), default=None)
    ponr = max(0.0, rul - dur - SAFETY_MIN) if dur is not None else 0.0
    urgency = clamp01(1.0 - (rul - thr) / (6.0 * thr))
    fuel_note = ("propulsion reserves are insufficient for safe maneuvering" if not options
                 else f"controlled retirement still possible for {ponr:.0f} more min")
    if rul <= thr or (not options and s.health < 0.5):
        verdict = "RETIRE"
        why = (f"{fuel_note}, and remaining useful life is {rul:.0f} min "
               f"(limit {thr:.0f} min at importance {s.mission_importance:.1f})")
    elif rul <= 4.0 * thr or s.health < 0.6:
        verdict = "WAIT"
        why = (f"health {s.health:.2f} and {rul:.0f} min of life left: not yet at the limit, "
               f"re-check as telemetry arrives ({fuel_note})")
    else:
        verdict = "SAVE"
        why = f"healthy ({s.health:.2f}) with {rul:.0f} min of useful life; {fuel_note}"
    return {"verdict": verdict, "reason": f"{verdict} {s.id}: {why}.", "rul_min": rul,
            "point_of_no_return_min": ponr, "urgency": urgency,
            "failure_prob_60m": 1.0 - 2.718281828 ** (-60.0 / max(rul, 1e-6)),
            "options_available": [x["name"] for x in options]}
