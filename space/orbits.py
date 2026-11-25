"""orbits.py - ground tracks, visibility, coverage (REAL, prototype fidelity).

Model: each satellite follows a straight ground-track segment A->B (km, local
2D frame) that repeats every `period` minutes, offset by `phase`. This is a
locally-linearised nadir track over the 100x100 km region; the in-region
period is time-compressed for the demo, so physical altitude is a separate
parameter (orbit["alt_km"], default 550 km) used by drag/retirement models.
Visibility = footprint (sensor radius + slew) can reach the region.
"""
import math

import numpy as np

import config
from contracts import AREA_KM, dist
from . import MU_KM3_S2, NOMINAL_ALT_KM, R_EARTH_KM

HORIZON_MIN = 240


def init_orbit(o: dict, sat_id: str) -> dict:
    """Fill any missing private orbit fields from config.SATELLITES (never overwrites)."""
    spec = next((d for d in config.SATELLITES if d["id"] == sat_id), {})
    for k_src, k_dst in (("A", "A"), ("B", "B"), ("period", "period"), ("phase", "phase")):
        if k_dst not in o and k_src in spec:
            o[k_dst] = spec[k_src]
    o.setdefault("base_conf", config.SENSOR_SPECS["SAT"]["pd"])
    o.setdefault("degrade_rate", spec.get("degrade", 0.0005))
    o.setdefault("alt_km", NOMINAL_ALT_KM)
    return o


def frac(o: dict, t: float) -> float:
    return ((t + o["phase"]) % o["period"]) / o["period"]


def pos_at(o: dict, t: float):
    s = frac(o, t)
    return (o["A"][0] + (o["B"][0] - o["A"][0]) * s, o["A"][1] + (o["B"][1] - o["A"][1]) * s)


def keplerian_period_min(alt_km: float) -> float:
    a = R_EARTH_KM + alt_km
    return 2 * math.pi * math.sqrt(a ** 3 / MU_KM3_S2) / 60.0


def in_view_at(o: dict, t: float, reach: float) -> bool:
    p = pos_at(o, t)
    cx, cy = min(max(p[0], 0.0), AREA_KM), min(max(p[1], 0.0), AREA_KM)
    return dist(p, (cx, cy)) < reach


def _view_array(o: dict, ts: np.ndarray, reach: float) -> np.ndarray:
    s = ((ts + o["phase"]) % o["period"]) / o["period"]
    x = o["A"][0] + (o["B"][0] - o["A"][0]) * s
    y = o["A"][1] + (o["B"][1] - o["A"][1]) * s
    return np.hypot(x - np.clip(x, 0.0, AREA_KM), y - np.clip(y, 0.0, AREA_KM)) < reach


def view_times(o: dict, t: float, reach: float, in_view: bool):
    """-> (view_left_min, next_view_min); one of them is always 0."""
    v = _view_array(o, t + 1 + np.arange(HORIZON_MIN), reach)
    if in_view:
        idx = int(np.argmin(v)) if not v.all() else HORIZON_MIN
        return float(idx + 1), 0.0
    idx = int(np.argmax(v)) if v.any() else HORIZON_MIN
    return 0.0, float(idx + 1)


def in_contact_at(o: dict, t: float) -> bool:
    lo, hi = config.CONTACT_S_RANGE
    return lo <= frac(o, t) <= hi


def next_contact_min(o: dict, t: float) -> float:
    if in_contact_at(o, t):
        return 0.0
    ts = t + 1 + np.arange(HORIZON_MIN)
    s = ((ts + o["phase"]) % o["period"]) / o["period"]
    lo, hi = config.CONTACT_S_RANGE
    c = (s >= lo) & (s <= hi)
    return float((int(np.argmax(c)) if c.any() else HORIZON_MIN) + 1)


def coverage_windows(o: dict, t: float, horizon_min: float, reach: float):
    """[(t_start, t_end)] minute-sampled windows where the footprint reaches the region."""
    ks = np.arange(int(horizon_min) + 1)
    v = _view_array(o, t + ks, reach)
    out, start = [], None
    for k, vis in zip(ks, v):
        if vis and start is None:
            start = t + float(k)
        if not vis and start is not None:
            out.append((start, t + float(k)))
            start = None
    if start is not None:
        out.append((start, t + horizon_min))
    return out
