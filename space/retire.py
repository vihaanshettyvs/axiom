"""retire.py - Retirement Lab: burn vs drag sail vs electrodynamic tether.

SIMPLIFIED PROTOTYPE MODELS (see ASSUMPTIONS.md). Frontend-ready dict rows.

A. CONTROLLED DEORBIT  Hohmann-style perigee lowering to ~80 km. Fuel scales with Δv
   (calibrated so the nominal-altitude burn costs 0.30 kg of the sim's propellant).
B. DRAG SAIL           A=10 m^2 extra area -> ballistic coefficient up -> density-driven
   decay (so space weather changes the answer). Deployment succeeds with p = 0.97*(0.5+0.5*health).
C. ELECTRODYNAMIC TETHER  I*L*B drag force F, I = I0*(0.7+0.6*w) (plasma density tracks
   space weather), L = 3 km. Deployment p = 0.85*(0.5+0.5*health), needs health >= 0.15.
Engine contract (PhysicsAPI.retirement_options) is a subset: name, fuel_kg, duration_min.
"""
import math

from . import MU_KM3_S2, NOMINAL_ALT_KM, R_EARTH_KM, decay_lifetime_days

REF_FUEL_BURN_KG = 0.30
REF_FUEL_GRAVEYARD_KG = 0.18
BURN_MIN, GRAVEYARD_MIN = 15.0, 25.0
SAIL_AREA_M2, SAIL_MASS_KG, SAIL_DEPLOY_MIN = 10.0, 3.0, 10.0
TETHER_L_M, TETHER_I0_A, TETHER_B_T, TETHER_MASS_KG, TETHER_DEPLOY_MIN = 3000.0, 1.0, 3.0e-5, 5.0, 30.0
SAT_AREA_M2, SAT_MASS_KG, CD = 1.0, 150.0, 2.2


def _vc(alt):
    return math.sqrt(MU_KM3_S2 / (R_EARTH_KM + alt))


def burn_dv_ms(alt_km: float, perigee_km: float = 80.0) -> float:
    r1, r2 = R_EARTH_KM + alt_km, R_EARTH_KM + perigee_km
    v = math.sqrt(MU_KM3_S2 * (2 / r1 - 2 / (r1 + r2)))
    return (_vc(alt_km) - v) * 1000.0


def graveyard_dv_ms(alt_km: float, raise_km: float = 300.0) -> float:
    r1, r2 = R_EARTH_KM + alt_km, R_EARTH_KM + alt_km + raise_km
    v1 = math.sqrt(MU_KM3_S2 * (2 / r1 - 2 / (r1 + r2)))
    v2 = math.sqrt(MU_KM3_S2 * (2 / r2 - 2 / (r1 + r2)))
    return ((v1 - _vc(alt_km)) + (_vc(alt_km + raise_km) - v2)) * 1000.0


def _fuel(dv, ref_dv_fn, ref_kg):
    return ref_kg * dv / ref_dv_fn(NOMINAL_ALT_KM)


def engine_options(s, o: dict) -> list:
    """PhysicsAPI.retirement_options: [] if not enough fuel or propulsion is dead."""
    alt = o.get("alt_km", NOMINAL_ALT_KM)
    if not o.get("prop_ok", True) or not o.get("comm_ok", True):
        return []          # burns need working propulsion AND a command link
    opts = [{"name": "controlled_deorbit", "duration_min": BURN_MIN,
             "fuel_kg": _fuel(burn_dv_ms(alt), burn_dv_ms, REF_FUEL_BURN_KG)},
            {"name": "graveyard_orbit", "duration_min": GRAVEYARD_MIN,
             "fuel_kg": _fuel(graveyard_dv_ms(alt), graveyard_dv_ms, REF_FUEL_GRAVEYARD_KG)}]
    return [x for x in opts if s.fuel_kg >= x["fuel_kg"] + 0.02]


def _row(name, fuel, resource, dur, reentry_d, p_ok, risk, feasible, why):
    life_ok = reentry_d <= 25 * 365.0
    return {"option": name, "fuel_kg": round(fuel, 3), "resource_cost": resource,
            "duration_min": dur, "reentry_days": round(reentry_d, 2),
            "effectiveness": round(p_ok * (1.0 if life_ok else 0.4), 3),
            "risk": round(min(1.0, risk), 3), "feasible": feasible, "note": why}


def lab(s, o: dict, weather: float) -> list:
    """Compare the three disposal options at the given space-weather index."""
    alt = o.get("alt_km", NOMINAL_ALT_KM)
    b0 = CD * SAT_AREA_M2 / SAT_MASS_KG
    base_d = decay_lifetime_days(alt, b0, weather, mass_kg=SAT_MASS_KG)

    f_burn = _fuel(burn_dv_ms(alt), burn_dv_ms, REF_FUEL_BURN_KG)
    comm = o.get("comm_ok", True)
    can_burn = o.get("prop_ok", True) and comm and s.fuel_kg >= f_burn + 0.02
    period_min = 2 * math.pi * math.sqrt((R_EARTH_KM + alt) ** 3 / MU_KM3_S2) / 60.0
    burn_d = (BURN_MIN + 1.5 * period_min) / 1440.0
    burn = _row("controlled_deorbit", f_burn, f"propellant {f_burn:.2f} kg", BURN_MIN, burn_d, 0.95, 0.05,
                can_burn, "ok" if can_burn else "insufficient propellant, propulsion failed or no command link")

    auto = 1.0 if comm else 0.6      # without a command link, passive devices rely on a pre-set autonomous timer
    p_sail = 0.97 * (0.5 + 0.5 * s.health) * auto
    b_sail = CD * (SAT_AREA_M2 + SAIL_AREA_M2) / (SAT_MASS_KG + SAIL_MASS_KG)
    sail_d = decay_lifetime_days(alt, b_sail, weather, mass_kg=SAT_MASS_KG + SAIL_MASS_KG)
    sail = _row("drag_sail", 0.0, f"sail {SAIL_MASS_KG:.0f} kg, no propellant", SAIL_DEPLOY_MIN, sail_d, p_sail,
                (1 - p_sail) + min(0.5, sail_d / 365 * 0.004), True,
                "passive; slower at low drag (quiet space weather)")

    p_edt = 0.85 * (0.5 + 0.5 * s.health) * auto
    can_edt = s.health >= 0.15
    force = TETHER_I0_A * (0.7 + 0.6 * weather) * TETHER_L_M * TETHER_B_T
    edt_d = decay_lifetime_days(alt, b0, weather, tether_force_n=force, mass_kg=SAT_MASS_KG + TETHER_MASS_KG)
    edt = _row("edt_tether", 0.0, f"tether {TETHER_L_M / 1000:.0f} km, {TETHER_MASS_KG:.0f} kg", TETHER_DEPLOY_MIN,
               edt_d, p_edt, (1 - p_edt) + min(0.5, edt_d / 365 * 0.004) + 0.1, can_edt,
               "needs working deployer (health >= 0.15); drag ~ I*L*B" if can_edt else "deployer too degraded")
    out = [burn, sail, edt]
    out.append({"option": "do_nothing", "fuel_kg": 0.0, "resource_cost": "none", "duration_min": 0.0,
                "reentry_days": round(base_d, 1), "effectiveness": 0.0 if base_d > 25 * 365 else 1.0,
                "risk": round(min(1.0, base_d / 365 * 0.004), 3), "feasible": True,
                "note": "natural decay (becomes uncontrolled debris if the sat dies)"})
    return out
