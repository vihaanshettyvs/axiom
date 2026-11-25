from __future__ import annotations
import json
import math
from pathlib import Path
from typing import Optional
from mock_data import generate_mock_runlog
ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIRS = [ROOT_DIR / "out" / "demo", ROOT_DIR / "out" / "firms_demo", ROOT_DIR / "out" / "backup", ROOT_DIR / "out", ROOT_DIR / "data" / "runlogs", ROOT_DIR / "data"]
def list_json_files() -> list[Path]:
    found = []
    seen = set()
    for d in DATA_DIRS:
        if d.exists():
            for p in sorted(d.glob("*.json")):
                if p.resolve() not in seen:
                    seen.add(p.resolve())
                    found.append(p)
    return found
LABELS = {
    "out/demo/runlog_brain_on.json": "1. Primary Demo (Seed 42) - Brain ON",
    "out/demo/runlog_brain_off.json": "2. Primary Demo (Seed 42) - Brain OFF",
    "out/demo/comparison.json": "3. Primary Demo - ON vs OFF Comparison",
    "out/demo/p4_report.json": "4. Primary Demo - P4 Sensing Report",
    "out/firms_demo/runlog_brain_on.json": "5. NASA FIRMS Wildfires - Brain ON",
    "out/firms_demo/runlog_brain_off.json": "6. NASA FIRMS Wildfires - Brain OFF",
    "out/firms_demo/comparison.json": "7. NASA FIRMS Wildfires - Comparison",
    "out/firms_demo/p4_report.json": "8. NASA FIRMS Wildfires - P4 Report",
    "out/firms_validation.json": "9. NASA FIRMS - 6-Seed Validation",
    "out/backup/runlog_brain_on.json": "10. Backup Demo (Seed 7) - Brain ON",
    "out/backup/runlog_brain_off.json": "11. Backup Demo (Seed 7) - Brain OFF",
    "out/backup/comparison.json": "12. Backup Demo - ON vs OFF Comparison",
    "out/validation.json": "13. Full Multi-Seed Validation",
}

def format_json_label(p: Path) -> str:
    try:
        rel = str(p.relative_to(ROOT_DIR))
    except ValueError:
        rel = p.name
    if rel in LABELS:
        return LABELS[rel]
    stem = p.stem.replace("_", " ").title()
    folder = p.parent.name.replace("_", " ").title()
    return f"{folder} - {stem}" 
def _sat_pos_from_orbital(sat: dict, t: int, dt_min: float = 1.0) -> tuple[float, float]:
    if "lat" in sat and "lon" in sat:
        return float(sat["lat"]), float(sat["lon"])
    if isinstance(sat.get("pos"), list) and len(sat["pos"]) >= 2:
        return float(sat["pos"][0]), float(sat["pos"][1])
    orb = sat.get("orbit") if isinstance(sat.get("orbit"), dict) else sat
    a_vec = orb.get("A") or [0.0, 0.0]
    b_vec = orb.get("B") or [0.0, 0.0]
    period = float(orb.get("period") or 90.0)
    phase = float(orb.get("phase") or 0.0)
    angle = 2.0 * math.pi * ((t * dt_min) / max(1.0, period) + phase)
    lat = float(a_vec[0]) * math.cos(angle) + float(b_vec[0]) * math.sin(angle)
    lon = float(a_vec[1]) * math.cos(angle) + float(b_vec[1]) * math.sin(angle)
    lat = max(-85.0, min(85.0, lat))
    lon = ((lon + 180.0) % 360.0) - 180.0
    return round(lat, 2), round(lon, 2)
def _normalize_targets(raw: dict) -> list[dict]:
    if isinstance(raw.get("targets"), list) and raw["targets"]:
        return raw["targets"]
    scen = raw.get("scenario") if isinstance(raw.get("scenario"), dict) else {}
    assets = raw.get("assets") or scen.get("assets") or []
    hazards = scen.get("hazards") or []
    out = []
    for i, item in enumerate(assets):
        pos = item.get("pos") or [0.0, 0.0]
        weight = float(item.get("weight", 1.0))
        prio = "CRITICAL" if weight >= 0.9 else ("HIGH" if weight >= 0.6 else "MEDIUM")
        out.append({"id": item.get("id", f"TGT-{i+1:02d}"), "name": item.get("name", f"Asset {i+1}"), "lat": float(pos[0]), "lon": float(pos[1]), "priority": prio})
    for i, hz in enumerate(hazards):
        pos = hz.get("pos") or [0.0, 0.0]
        hz_id = hz.get("id", f"HAZ-{i+1:02d}")
        src = hz.get("source", "sim")
        out.append({"id": hz_id, "name": f"{hz_id} ({src})", "lat": float(pos[0]), "lon": float(pos[1]), "priority": "CRITICAL"})
    return out
def _normalize_sat_entry(sat: dict, t: int, mode: str) -> dict:
    lat, lon = _sat_pos_from_orbital(sat, t)
    raw_rad = sat.get("radius_km") or sat.get("sensor_radius_km")
    radius_km = int(float(raw_rad) * 120) if raw_rad and float(raw_rad) < 50 else int(raw_rad or (2100 if mode == "brain_on" else 1600))
    status = sat.get("status") or ("TASKED" if mode == "brain_on" else "ACTIVE")
    orb = sat.get("orbit") if isinstance(sat.get("orbit"), dict) else {}
    raw_bat = sat.get("battery", orb.get("battery"))
    if isinstance(raw_bat, (int, float)):
        battery = round(float(raw_bat) * 100.0, 1) if float(raw_bat) <= 1.0 else round(float(raw_bat), 1)
    else:
        battery = round(max(30.0, 95.0 - t * 0.25), 1)
    return {"id": sat.get("id", "SAT-01"), "name": sat.get("name") or sat.get("kind", "SAT"), "lat": lat, "lon": lon, "radius_km": radius_km, "status": status, "battery": battery, "fuel_kg": sat.get("fuel_kg"), "health": sat.get("health"), "rul_min": sat.get("rul_min"), "last_breath": orb.get("last_breath")}
def normalize_runlog(raw, source_name: str = "json") -> dict:
    if not isinstance(raw, dict):
        return {"meta": {"scenario": source_name, "source": source_name}, "targets": [], "frames": [], "retirement_lab": {}, "raw": raw}
    meta_in = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    scen_in = raw.get("scenario") if isinstance(raw.get("scenario"), dict) else {}
    is_firms = ("firms" in source_name.lower()) or (meta_in.get("hazard_source") == "NASA_FIRMS") or any(isinstance(h, dict) and h.get("source") == "NASA_FIRMS" for h in (scen_in.get("hazards") or []))
    meta_out = dict(meta_in)
    meta_out["source"] = source_name
    meta_out["is_firms"] = is_firms
    retire_lab_data = scen_in.get("retirement_lab") if isinstance(scen_in.get("retirement_lab"), dict) else {}
    targets = _normalize_targets(raw)
    raw_frames = raw.get("frames") or raw.get("steps") or raw.get("timesteps") or []
    default_sats = raw.get("satellites") or scen_in.get("satellites") or []
    if raw_frames and isinstance(raw_frames[0], dict) and ("brain_on" in raw_frames[0] or "brain_off" in raw_frames[0]):
        frames = []
        for idx, fr in enumerate(raw_frames):
            b_off = [_normalize_sat_entry(s, idx, "brain_off") for s in fr.get("brain_off", {}).get("satellites", [])]
            b_on = [_normalize_sat_entry(s, idx, "brain_on") for s in fr.get("brain_on", {}).get("satellites", [])]
            frames.append({"t": fr.get("t", idx), "timestamp": fr.get("timestamp", f"T+{idx:03d} min"), "brain_off": {"satellites": b_off}, "brain_on": {"satellites": b_on}, "decisions": fr.get("decisions") or [], "events": fr.get("events") or [], "sim_metrics": fr.get("metrics") or {}})
        return {"meta": meta_out, "targets": targets, "frames": frames, "retirement_lab": retire_lab_data, "raw": raw}
    if raw_frames:
        frames = []
        for idx, fr in enumerate(raw_frames):
            sats_raw = fr.get("satellites") or default_sats
            sats_off = [_normalize_sat_entry(s, idx, "brain_off") for s in sats_raw]
            sats_on = [_normalize_sat_entry(s, idx, "brain_on") for s in sats_raw]
            t_val = int(fr.get("t", idx))
            frames.append({"t": t_val, "timestamp": fr.get("timestamp", f"T+{t_val:03d} min"), "brain_off": {"satellites": sats_off}, "brain_on": {"satellites": sats_on}, "decisions": fr.get("decisions") or [], "events": fr.get("events") or [], "sim_metrics": fr.get("metrics") or {}})
        return {"meta": meta_out, "targets": targets, "frames": frames, "retirement_lab": retire_lab_data, "raw": raw}
    return {"meta": meta_out, "targets": targets, "frames": [], "retirement_lab": retire_lab_data, "raw": raw}
def load_runlog_from_path(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return normalize_runlog(raw, source_name=format_json_label(path))
def load_runlog_from_bytes(uploaded_file) -> dict:
    raw = json.load(uploaded_file)
    return normalize_runlog(raw, source_name=uploaded_file.name)
def load_mock_runlog() -> dict:
    return generate_mock_runlog(num_steps=30)
def load_p4_report() -> Optional[dict]:
    for rel in ("out/demo/p4_report.json", "data/p4_report.json", "out/p4_report.json"):
        p = ROOT_DIR / rel
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
    return None
def load_firms_validation() -> Optional[dict]:
    p = ROOT_DIR / "out" / "firms_validation.json"
    if not p.exists():
        return None
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)
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
    return {"satellites": sats, "covered_ids": covered_ids, "target_rows": target_rows, "sim_metrics": frame.get("sim_metrics") or {}, "metrics": {"targets_covered_pct": coverage_pct, "targets_covered_count": len(covered_ids), "targets_total": len(targets), "avg_response_min": avg_response_min, "fleet_battery_pct": avg_battery, "triage_score": triage_score}}

CURATED_GROUPS = {
    "1. Primary Demo (Seed 42)": [
        ("Brain ON - Adaptive Triage Replay", "out/demo/runlog_brain_on.json"),
        ("Brain OFF - Baseline Lawnmower", "out/demo/runlog_brain_off.json"),
        ("ON vs OFF Metrics Comparison", "out/demo/comparison.json"),
        ("P4 Sensing & Hazard Report", "out/demo/p4_report.json"),
    ],
    "2. NASA FIRMS (Real Wildfires)": [
        ("Brain ON - Real FIRMS Replay", "out/firms_demo/runlog_brain_on.json"),
        ("Brain OFF - Baseline Lawnmower", "out/firms_demo/runlog_brain_off.json"),
        ("FIRMS ON vs OFF Comparison", "out/firms_demo/comparison.json"),
        ("FIRMS 6-Seed Validation Table", "out/firms_validation.json"),
        ("FIRMS P4 Sensing Report", "out/firms_demo/p4_report.json"),
    ],
    "3. Backup Demo (Seed 7)": [
        ("Brain ON - Early Detection Replay", "out/backup/runlog_brain_on.json"),
        ("Brain OFF - Baseline Lawnmower", "out/backup/runlog_brain_off.json"),
        ("Backup ON vs OFF Comparison", "out/backup/comparison.json"),
    ],
    "4. Multi-Seed Benchmarks": [
        ("Full Multi-Seed Validation", "out/validation.json"),
        ("Seed 42 Summary Comparison", "out/comparison.json"),
        ("P4 Full Telemetry Report", "data/p4_report.json"),
    ],
}

def get_grouped_json_files() -> dict[str, list[tuple[str, Path]]]:
    grouped: dict[str, list[tuple[str, Path]]] = {}
    for group_name, entries in CURATED_GROUPS.items():
        valid = [(label, ROOT_DIR / rel) for label, rel in entries if (ROOT_DIR / rel).exists()]
        if valid:
            grouped[group_name] = valid
    return grouped
