"""Orbital Triage - space physics library (owner: P2).

Pure functions + small helpers used by physics/api.py::RealPhysics.
Conventions come from contracts.py (minutes, km, local 2D frame).

SIMPLIFIED PROTOTYPE MODELS - not operational tools. See ASSUMPTIONS.md.

Space weather
-------------
`w` in [0, 1]; 0.5 = nominal (all factors == 1.0 so the mock-parity run is unchanged).
  * density factor   10**(2*(w-0.5))  -> x0.1 (quiet) .. x10 (severe storm)
  * radiation factor 1 + (w-0.5)       -> x0.5 .. x1.5 on electronics/battery wear
"""
import math

R_EARTH_KM = 6371.0
MU_KM3_S2 = 398600.4418
MU_M3_S2 = MU_KM3_S2 * 1e9
NOMINAL_ALT_KM = 550.0          # physical altitude (ground-track periods are time-compressed for the demo)
NOMINAL_WEATHER = 0.5
REENTRY_ALT_KM = 120.0

# (altitude km, density kg/m^3) - rough mid-activity thermosphere, log-interpolated.
_RHO_TABLE = [(120, 2.2e-8), (200, 2.5e-10), (300, 2.0e-11), (400, 3.0e-12),
              (500, 6.0e-13), (600, 1.5e-13), (800, 1.5e-14), (1000, 3.0e-15)]


def clamp01(w: float) -> float:
    return min(1.0, max(0.0, float(w)))


def density_factor(w: float) -> float:
    return 10.0 ** (2.0 * (clamp01(w) - 0.5))


def radiation_factor(w: float) -> float:
    return 1.0 + (clamp01(w) - 0.5)


def density(h_km: float, w: float = NOMINAL_WEATHER) -> float:
    """Atmospheric density (kg/m^3) at altitude, scaled by space weather."""
    tab = _RHO_TABLE
    if h_km <= tab[0][0]:
        base = tab[0][1]
    elif h_km >= tab[-1][0]:
        base = tab[-1][1] * math.exp(-(h_km - tab[-1][0]) / 150.0)
    else:
        for (h0, r0), (h1, r1) in zip(tab, tab[1:]):
            if h0 <= h_km <= h1:
                f = (h_km - h0) / (h1 - h0)
                base = math.exp(math.log(r0) + f * (math.log(r1) - math.log(r0)))
                break
    return base * density_factor(w)


def decay_lifetime_days(alt_km: float, ballistic_m2_per_kg: float, w: float = NOMINAL_WEATHER,
                        tether_force_n: float = 0.0, mass_kg: float = 150.0,
                        step_km: float = 5.0, cap_days: float = 1e6) -> float:
    """Time to decay from alt_km to REENTRY_ALT_KM (days).

    da/dt (circular) = -rho * B * sqrt(mu*a)               [atmospheric drag, B = Cd*A/m]
                       - 2 * a^1.5 * F / (sqrt(mu) * m)    [constant tether drag force F]
    Integrated in `step_km` altitude steps.
    """
    total_s, h = 0.0, float(alt_km)
    while h > REENTRY_ALT_KM and total_s < cap_days * 86400.0:
        a = (R_EARTH_KM + h - step_km / 2) * 1000.0
        rate = density(h - step_km / 2, w) * ballistic_m2_per_kg * math.sqrt(MU_M3_S2 * a)
        rate += 2.0 * a ** 1.5 * tether_force_n / (math.sqrt(MU_M3_S2) * mass_kg)
        total_s += step_km * 1000.0 / max(rate, 1e-12)
        h -= step_km
    return min(cap_days, total_s / 86400.0)
