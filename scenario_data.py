"""scenario_data.py -- where the engine's hazards come from.

Priority (first that works wins; a failure falls back to the next and is reported, never fatal):
  1. config.HAZARD_SOURCE   "module:function" -> list of hazard spec dicts (P4/anyone can plug in here)
  2. config.WILDFIRE_DATA_PATH   a NASA FIRMS active-fire CSV (VIIRS/MODIS) -> real wildfires,
                                 methane leaks still come from config.HAZARDS
  3. config.HAZARDS   built-in synthetic scenario

A hazard spec is a dict: id, kind("wildfire"|"methane"), pos(x,y km), t_start(min), radius0, rmax, expansion,
wind(vx,vy km/min), wind_turn, int0, int_rate.

FIRMS columns used: latitude, longitude, frp (or bright_ti4/brightness), acq_date (YYYY-MM-DD), acq_time (HHMM).
NOTE: no real FIRMS file ships with this repo (needs an API key and network). Download one for your region and
set config.WILDFIRE_DATA_PATH.  The 100x100 km region is centred on the fire cluster centroid.
"""
from __future__ import annotations

import csv
import datetime as dt
import importlib
import math
from typing import Any, Dict, List, Tuple

import config
from contracts import AREA_KM, dist


def select_dense_region(lats, lons, half_km: float = 50.0):
    """Pick the centre (lat, lon) of the densest 100x100 km window among the detections.

    FIRMS files can be GLOBAL (one overpass day, tens of thousands of fires); centring on the global median would
    put the grid in the middle of nowhere. Coarse 1-degree bins find the busiest area, then candidate centres
    (actual detections in the 3x3 bins around it) are scored by how many detections fall inside +-half_km.
    Deterministic (ties broken by lowest lat, then lon). config.FIRMS_REGION=(lat, lon) overrides the choice.
    """
    forced = getattr(config, "FIRMS_REGION", None)
    if forced:
        return float(forced[0]), float(forced[1])
    from collections import Counter
    bins = Counter((math.floor(a), math.floor(b)) for a, b in zip(lats, lons))
    (ba, bb), _ = max(sorted(bins.items()), key=lambda kv: kv[1])
    cand = [(a, b) for a, b in zip(lats, lons) if abs(math.floor(a) - ba) <= 1 and abs(math.floor(b) - bb) <= 1]
    if len(cand) > 400:                                              # keep it fast and deterministic
        step = len(cand) / 400.0
        cand = [cand[int(i * step)] for i in range(400)]
    best, bc = None, -1
    for ca, cb in sorted(cand):
        kx, ky = 111.32 * math.cos(math.radians(ca)), 110.57
        n = sum(1 for a, b in zip(lats, lons) if abs(a - ca) * ky <= half_km and abs(b - cb) * kx <= half_km)
        if n > bc:
            best, bc = (ca, cb), n
    return best


def _pts_from_p4(path: str):
    """Preferred reader: P4's sensing.fire.load_fire_detections (strict FIRMS schema, UTC timestamps, km offsets)."""
    from sensing.fire import load_fire_detections
    lats, lons = [], []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            try:
                lats.append(float(r["latitude"]))
                lons.append(float(r["longitude"]))
            except (KeyError, ValueError):
                continue
    if not lats:
        raise ValueError(f"no usable FIRMS rows in {path}")
    lat0, lon0 = select_dense_region(lats, lons)
    global FIRMS_REGION_USED
    FIRMS_REGION_USED = (round(lat0, 4), round(lon0, 4))
    dets = load_fire_detections(path, lat0, lon0)
    inside = [d for d in dets if 3.0 <= d.x_km + AREA_KM / 2 <= AREA_KM - 3.0 and 3.0 <= d.y_km + AREA_KM / 2 <= AREA_KM - 3.0]
    if not inside:
        return []
    t0 = min(d.timestamp_utc for d in inside)                        # sim clock starts at the first detection IN the region
    return [(d.x_km + AREA_KM / 2, d.y_km + AREA_KM / 2, max(d.frp_mw if d.frp_mw is not None else 1.0, 0.1),
             (d.timestamp_utc - t0).total_seconds() / 60.0) for d in inside]


def _pts_legacy(path: str):
    """Fallback reader (lenient: skips malformed rows, accepts bright_ti4/brightness instead of frp)."""
    rows = []
    with open(path, newline="") as fh:
        for r in csv.DictReader(fh):
            try:
                lat, lon = float(r["latitude"]), float(r["longitude"])
                frp = float(r.get("frp") or r.get("bright_ti4") or r.get("brightness") or 1.0)
                hhmm = str(r.get("acq_time", "0000")).zfill(4)
                t = dt.datetime.strptime(f"{r['acq_date']} {hhmm}", "%Y-%m-%d %H%M")
            except (KeyError, ValueError):
                continue                                           # skip malformed rows
            rows.append((lat, lon, max(frp, 0.1), t))
    if not rows:
        raise ValueError(f"no usable FIRMS rows in {path}")
    lat0, lon0 = select_dense_region([r[0] for r in rows], [r[1] for r in rows])
    global FIRMS_REGION_USED
    FIRMS_REGION_USED = (round(lat0, 4), round(lon0, 4))
    kx, ky = 111.32 * math.cos(math.radians(lat0)), 110.57
    cells = [((lon - lon0) * kx + AREA_KM / 2, (lat - lat0) * ky + AREA_KM / 2, frp, t) for lat, lon, frp, t in rows]
    cells = [c for c in cells if 3.0 <= c[0] <= AREA_KM - 3.0 and 3.0 <= c[1] <= AREA_KM - 3.0]
    if not cells:
        return []
    t0 = min(c[3] for c in cells)
    return [(x, y, frp, (t - t0).total_seconds() / 60.0) for x, y, frp, t in cells]


FIRMS_READER_USED = "none"
FIRMS_REGION_USED = None          # (lat, lon) centre of the 100x100 km window actually simulated


def load_firms_csv(path: str, max_fires: int = 3, cluster_km: float = 8.0, max_start_min: float = 90.0) -> List[Dict[str, Any]]:
    """Convert FIRMS detections into wildfire hazard specs in the local 100x100 km frame."""
    global FIRMS_READER_USED
    try:
        pts = _pts_from_p4(path)
        FIRMS_READER_USED = "sensing.fire"
    except Exception:                                              # noqa: BLE001 - P4 reader missing/strict -> lenient fallback
        pts = _pts_legacy(path)
        FIRMS_READER_USED = "scenario_data (fallback)"
    if not pts:
        raise ValueError("no FIRMS detections inside the selected 100x100 km region")
    pts.sort(key=lambda p: -p[2])
    clusters: List[List[Tuple[float, float, float, float]]] = []
    for p in pts:
        for c in clusters:
            if dist((p[0], p[1]), (c[0][0], c[0][1])) < cluster_km:
                c.append(p)
                break
        else:
            if len(clusters) < max_fires:
                clusters.append([p])
    fmax = max(p[2] for p in pts)
    specs = []
    for i, c in enumerate(clusters):
        w = sum(p[2] for p in c)
        x, y = sum(p[0] * p[2] for p in c) / w, sum(p[1] * p[2] for p in c) / w
        specs.append(dict(id=f"FIRE-{i + 1}", kind="wildfire", pos=(round(x, 3), round(y, 3)),
                          t_start=round(min(max(min(p[3] for p in c), 0.0), max_start_min), 1),
                          radius0=round(1.5 + 0.5 * math.sqrt(len(c)), 2), rmax=8.0, expansion=0.03,
                          wind=(0.08, 0.04), wind_turn=0.003 * (1 if i % 2 == 0 else -1),
                          int0=round(0.25 + 0.6 * max(p[2] for p in c) / fmax, 3), int_rate=0.006))
    return specs


def build_hazard_specs() -> Tuple[List[Dict[str, Any]], str, List[str]]:
    """Returns (specs, source description, warnings)."""
    warns: List[str] = []
    if config.HAZARD_SOURCE:
        try:
            mod, fn = config.HAZARD_SOURCE.split(":")
            specs = getattr(importlib.import_module(mod), fn)()
            if specs:
                return list(specs), f"extension:{config.HAZARD_SOURCE}", warns
            warns.append(f"HAZARD_SOURCE {config.HAZARD_SOURCE} returned nothing")
        except Exception as e:                                     # noqa: BLE001 - optional module must never crash the run
            warns.append(f"HAZARD_SOURCE {config.HAZARD_SOURCE} failed: {e!r}")
    if config.WILDFIRE_DATA_PATH:
        try:
            fires = load_firms_csv(config.WILDFIRE_DATA_PATH)
            leaks = [h for h in config.HAZARDS if h.get("kind") == "methane"]
            return fires + leaks, f"firms:{config.WILDFIRE_DATA_PATH}", warns   # reader: see FIRMS_READER_USED
        except Exception as e:                                     # noqa: BLE001
            warns.append(f"WILDFIRE_DATA_PATH {config.WILDFIRE_DATA_PATH} failed: {e!r}")
    return list(config.HAZARDS), "synthetic", warns
