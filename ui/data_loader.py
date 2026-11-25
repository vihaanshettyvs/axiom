import json
import math
from pathlib import Path
from mock_data import generate_mock_runlog

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def list_json_files() -> list[Path]:
    if not DATA_DIR.exists():
        return []
    return sorted(DATA_DIR.glob("*.json"))


def normalize_runlog(raw, source_name: str = "json") -> dict:
    if not isinstance(raw, dict):
        return {
            "meta": {"scenario": source_name, "source": source_name},
            "targets": [],
            "frames": [],
            "raw": raw,
        }

    if "frames" in raw and "targets" in raw:
        raw.setdefault("meta", {})
        raw["meta"]["source"] = source_name
        return raw

    frames = raw.get("frames") or raw.get("steps") or raw.get("timesteps") or []
    targets = raw.get("targets") or []
    return {
        "meta": {"scenario": raw.get("scenario", source_name), "source": source_name},
        "targets": targets,
        "frames": frames,
        "raw": raw,
    }


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
        covering_sats = [
            s["id"]
            for s in sats
            if s["status"] != "RETIRED"
            and haversine_km(s["lat"], s["lon"], tgt["lat"], tgt["lon"]) <= s["effective_radius_km"]
        ]
        is_covered = len(covering_sats) > 0
        if is_covered:
            covered_ids.add(tgt["id"])
        target_rows.append({
            "Target": tgt["name"],
            "Priority": tgt.get("priority", "MEDIUM"),
            "Status": "COVERED" if is_covered else "GAP",
            "Covered By": ", ".join(covering_sats) if covering_sats else "—",
        })

    active_sats = [s for s in sats if s["status"] != "RETIRED"]
    total_targets = max(1, len(targets))
    coverage_pct = round(100.0 * len(covered_ids) / total_targets, 1)
    avg_battery = round(sum(s.get("battery", 0) for s in active_sats) / max(1, len(active_sats)), 1)

    base_latency = 42.0 if mode == "brain_off" else 26.0
    avg_response_min = round(max(4.0, base_latency - (coverage_pct * 0.22) + (len(retired_sats) * 2.5)), 1)

    weights = {"CRITICAL": 3, "HIGH": 2, "MEDIUM": 1}
    max_weight = sum(weights.get(t.get("priority", "MEDIUM"), 1) for t in targets) or 1
    hit_weight = sum(
        weights.get(t.get("priority", "MEDIUM"), 1) for t in targets if t["id"] in covered_ids
    )
    triage_score = round(100.0 * hit_weight / max_weight, 1)

    return {
        "satellites": sats,
        "covered_ids": covered_ids,
        "target_rows": target_rows,
        "metrics": {
            "targets_covered_pct": coverage_pct,
            "targets_covered_count": len(covered_ids),
            "targets_total": len(targets),
            "avg_response_min": avg_response_min,
            "fleet_battery_pct": avg_battery,
            "triage_score": triage_score,
        },
    }
