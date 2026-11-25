import math

TARGETS = [
    {"id": "TGT-01", "name": "Bengaluru Flood Zone", "lat": 12.97, "lon": 77.59, "priority": "CRITICAL"},
    {"id": "TGT-02", "name": "California Wildfire", "lat": 37.77, "lon": -122.42, "priority": "CRITICAL"},
    {"id": "TGT-03", "name": "Mediterranean Distress", "lat": 35.90, "lon": 14.51, "priority": "HIGH"},
    {"id": "TGT-04", "name": "Tokyo Seismic Watch", "lat": 35.68, "lon": 139.69, "priority": "HIGH"},
    {"id": "TGT-05", "name": "Amazon Deforestation", "lat": -3.12, "lon": -60.02, "priority": "MEDIUM"},
    {"id": "TGT-06", "name": "Nairobi Drought Grid", "lat": -1.29, "lon": 36.82, "priority": "HIGH"},
    {"id": "TGT-07", "name": "North Sea Storm", "lat": 56.00, "lon": 3.00, "priority": "MEDIUM"},
    {"id": "TGT-08", "name": "Sydney Bushfire", "lat": -33.87, "lon": 151.21, "priority": "CRITICAL"},
]

SAT_SPECS = [
    {"id": "SAT-01", "name": "Sentinel-Alpha", "lat0": 15.0, "lon0": 60.0, "dlat": 1.2, "dlon": 4.0, "radius_km": 1700},
    {"id": "SAT-02", "name": "Sentinel-Beta", "lat0": 38.0, "lon0": -135.0, "dlat": -0.8, "dlon": 4.2, "radius_km": 1700},
    {"id": "SAT-03", "name": "Sentinel-Gamma", "lat0": 40.0, "lon0": -5.0, "dlat": -1.1, "dlon": 3.8, "radius_km": 1650},
    {"id": "SAT-04", "name": "Sentinel-Delta", "lat0": -10.0, "lon0": -75.0, "dlat": 1.0, "dlon": 4.1, "radius_km": 1750},
    {"id": "SAT-05", "name": "Sentinel-Epsilon", "lat0": -25.0, "lon0": 120.0, "dlat": -0.6, "dlon": 3.9, "radius_km": 1800},
    {"id": "SAT-06", "name": "Sentinel-Zeta", "lat0": 5.0, "lon0": 20.0, "dlat": 0.9, "dlon": 3.5, "radius_km": 1600},
]


def _wrap_lon(lon: float) -> float:
    return ((lon + 180.0) % 360.0) - 180.0


def _bounce_lat(lat: float) -> float:
    if lat > 65.0:
        return 130.0 - lat
    if lat < -65.0:
        return -130.0 - lat
    return lat


def generate_mock_runlog(num_steps: int = 30) -> dict:
    frames = []
    for t in range(num_steps):
        sats_off = []
        sats_on = []
        for idx, spec in enumerate(SAT_SPECS):
            base_lat = _bounce_lat(spec["lat0"] + math.sin(t * 0.25 + idx) * 18.0)
            base_lon = _wrap_lon(spec["lon0"] + t * spec["dlon"])
            batt_off = max(25.0, round(95.0 - t * 1.4 - idx * 2.0, 1))
            batt_on = max(35.0, round(95.0 - t * 1.0 - idx * 1.5, 1))

            sats_off.append({
                "id": spec["id"],
                "name": spec["name"],
                "lat": round(base_lat, 2),
                "lon": round(base_lon, 2),
                "radius_km": spec["radius_km"],
                "status": "ACTIVE",
                "battery": batt_off,
            })

            sats_on.append({
                "id": spec["id"],
                "name": spec["name"],
                "lat": round(base_lat, 2),
                "lon": round(base_lon, 2),
                "radius_km": int(spec["radius_km"] * 1.35),
                "status": "TASKED" if (t + idx) % 2 == 0 else "ACTIVE",
                "battery": batt_on,
            })

        frames.append({
            "t": t,
            "timestamp": f"T+{t * 5:03d} min",
            "brain_off": {"satellites": sats_off},
            "brain_on": {"satellites": sats_on},
        })

    return {
        "meta": {
            "scenario": "Mock Orbital Triage (6 Sats, 8 Targets)",
            "source": "mock",
        },
        "targets": TARGETS,
        "frames": frames,
    }
