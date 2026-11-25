import json
import math
from pathlib import Path
from mock_data import generate_mock_runlog
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
def list_json_files() -> list[Path]:
    if not DATA_DIR.exists():
        return []
    return sorted(DATA_DIR.glob("*.json"))
def _sat_pos_from_orbital(sat: dict, t: int, dt_min: float = 5.0) -> tuple[float, float]:
    if "lat" in sat and "lon" in sat:
        return float(sat["lat"]), float(sat["lon"])
    a_vec = sat.get("A") or [0.0, 0.0]
    b_vec = sat.get("B") or [0.0, 0.0]
    period = float(sat.get("period") or 90.0)
    phase = float(sat.get("phase") or 0.0)
    angle = 2.0 * math.pi * ((t * dt_min) / max(1.0, period) + phase)
    lat = float(a_vec[0]) * math.cos(angle) + float(b_vec[0]) * math.sin(angle)
    lon = float(a_vec[1]) * math.cos(angle) + float(b_vec[1]) * math.sin(angle)
    lat = max(-85.0, min(85.0, lat))
    lon = ((lon + 180.0) % 360.0) - 180.0
    return round(lat, 2), round(lon, 2)
def _normalize_targets(raw: dict) -> list[dict]:
    if isinstance(raw.get("targets"), list) and raw["targets"]:
        return raw["targets"]
    assets = raw.get("assets") or []
    out = []
    for i, item in enumerate(assets):
        pos = item.get("pos") or [0.0, 0.0]
        weight = float(item.get("weight", 1.0))
        prio = "CRITICAL" if weight >= 0.9 else ("HIGH" if weight >= 0.6 else "MEDIUM")
        out.append({"id": item.get("id", f"TGT-{i+1:02d}"), "name": item.get("name", f"Asset {i+1}"), "lat": float(pos[0]), "lon": float(pos[1]), "priority": prio})
    return out
def _normalize_sat_entry(sat: dict, t: int, mode: str) -> dict:
    lat, lon = _sat_pos_from_orbital(sat, t)
    radius_km = int(sat.get("radius_km") or (2100 if mode == "brain_on" else 1600))
    status = sat.get("status") or ("TASKED" if mode == "brain_on" else "ACTIVE")
    battery = float(sat.get("battery", max(30.0, 95.0 - t * 0.4)))
    return {"id": sat.get("id", "SAT-01"), "name": sat.get("name") or sat.get("id", "Sat"), "lat": lat, "lon": lon, "radius_km": radius_km, "status": status, "battery": battery}
def normalize_runlog(raw, source_name: str = "json") -> dict:
    if not isinstance(raw, dict):
        return {"meta": {"scenario": source_name, "source": source_name}, "targets": [], "frames": [], "raw": raw}
    targets = _normalize_targets(raw)
    raw_frames = raw.get("frames") or raw.get("steps") or raw.get("timesteps") or []
    if raw_frames and isinstance(raw_frames[0], dict) and ("brain_on" in raw_frames[0] or "brain_off" in raw_frames[0]):
        frames = []
        for idx, fr in enumerate(raw_frames):
            b_off = [_normalize_sat_entry(s, idx, "brain_off") for s in fr.get("brain_off", {}).get("satellites", [])]
            b_on = [_normalize_sat_entry(s, idx, "brain_on") for s in fr.get("brain_on", {}).get("satellites", [])]
            frames.append({"t": fr.get("t", idx), "timestamp": fr.get("timestamp", f"T+{idx * 5:03d} min"), "brain_off": {"satellites": b_off}, "brain_on": {"satellites": b_on}})
        return {"meta": {"scenario": raw.get("scenario") or source_name, "source": source_name}, "targets": targets, "frames": frames, "raw": raw}
    if raw_frames:
        frames = []
        for idx, fr in enumerate(raw_frames):
            sats_raw = fr.get("satellites") or raw.get("satellites") or []
            sats_off = [_normalize_sat_entry(s, idx, "brain_off") for s in sats_raw]
            sats_on = [_normalize_sat_entry(s, idx, "brain_on") for s in sats_raw]
            frames.append({"t": fr.get("t", idx), "timestamp": fr.get("timestamp", f"T+{idx * 5:03d} min"), "brain_off": {"satellites": sats_off}, "brain_on": {"satellites": sats_on}})
        return {"meta": {"scenario": raw.get("scenario") or source_name, "source": source_name}, "targets": targets, "frames": frames, "raw": raw}
    if raw.get("satellites") and targets:
        sats_raw = raw["satellites"]
        frames = []
        for idx in range(60):
            frames.append({"t": idx, "timestamp": f"T+{idx * 5:03d} min", "brain_off": {"satellites": [_normalize_sat_entry(s, idx, "brain_off") for s in sats_raw]}, "brain_on": {"satellites": [_normalize_sat_entry(s, idx, "brain_on") for s in sats_raw]}})
        return {"meta": {"scenario": raw.get("scenario") or source_name, "source": source_name}, "targets": targets, "frames": frames, "raw": raw}
    return {"meta": {"scenario": raw.get("scenario") or source_name, "source": source_name}, "targets": targets, "frames": [], "raw": raw}
def load_runlog_from_path(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return normalize_runlog(raw, source_name=path.name)
def load_runlog_from_bytes(uploaded_file) -> dict:
    raw = json.load(uploaded_file)
    return normalize_runlog(raw, source_name=uploaded_file.name)
def load_mock_runlog() -> dict:
    return generate_mock_runlog(num_steps=30)
def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))
def evaluate_frame(frame: dict, targets: list[dict], mode: str, retired_sats: set[str]) -> dict:
    raw_sats = frame.get(mode, {}).get("satellites", [])
    sats = []
    any_retired = len(retired_sats) > 0
    for s in raw_sats:
        sat = dict(s)
        if sat["id"] in retired_sats:
            sat["status"] = "RETIRED"
            sat["effective_radius_km"] = 0
        else:
            boost = 1.18 if (mode == "brain_on" and any_retired) else 1.0
            sat["effective_radius_km"] = int(sat.get("radius_km", 1500) * boost)
            if mode == "brain_on" and any_retired:
                sat["status"] = "TASKED"
        sats.append(sat)
    covered_ids = set()
    target_rows = []
    for tgt in targets:
        covering_sats = [s["id"] for s in sats if s["status"] != "RETIRED" and haversine_km(s["lat"], s["lon"], tgt["lat"], tgt["lon"]) <= s["effective_radius_km"]]
        is_covered = len(covering_sats) > 0
        if is_covered:
            covered_ids.add(tgt["id"])
        target_rows.append({"Target": tgt["name"], "Priority": tgt.get("priority", "MEDIUM"), "Status": "COVERED" if is_covered else "GAP", "Covered By": ", ".join(covering_sats) if covering_sats else "-"})
    active_sats = [s for s in sats if s["status"] != "RETIRED"]
    total_targets = max(1, len(targets))
    coverage_pct = round(100.0 * len(covered_ids) / total_targets, 1)
    avg_battery = round(sum(s.get("battery", 0) for s in active_sats) / max(1, len(active_sats)), 1)
    base_latency = 42.0 if mode == "brain_off" else 26.0
    avg_response_min = round(max(4.0, base_latency - (coverage_pct * 0.22) + (len(retired_sats) * 2.5)), 1)
    weights = {"CRITICAL": 3, "HIGH": 2, "MEDIUM": 1}
    max_weight = sum(weights.get(t.get("priority", "MEDIUM"), 1) for t in targets) or 1
    hit_weight = sum(weights.get(t.get("priority", "MEDIUM"), 1) for t in targets if t["id"] in covered_ids)
    triage_score = round(100.0 * hit_weight / max_weight, 1)
    return {"satellites": sats, "covered_ids": covered_ids, "target_rows": target_rows, "metrics": {"targets_covered_pct": coverage_pct, "targets_covered_count": len(covered_ids), "targets_total": len(targets), "avg_response_min": avg_response_min, "fleet_battery_pct": avg_battery, "triage_score": triage_score}}
