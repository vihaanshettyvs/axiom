"""Loading and light processing of real RunLog JSON (contract 1.x, see data/runlogs/)."""
import json
from pathlib import Path

import streamlit as st

RUNLOG_DIR = Path(__file__).resolve().parent.parent / "data" / "runlogs"


def list_runlogs() -> list[Path]:
    return sorted(RUNLOG_DIR.glob("*.json")) if RUNLOG_DIR.exists() else []


def _validate(log: dict, name: str) -> dict:
    for key in ("meta", "scenario", "frames"):
        if key not in log:
            raise ValueError(f"{name}: not a RunLog (missing '{key}')")
    if not log["frames"]:
        raise ValueError(f"{name}: RunLog has 0 frames")
    return log


@st.cache_data(show_spinner="Loading RunLog...")
def load_path(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        log = _validate(json.load(f), Path(path).name)
    log["_name"] = Path(path).name
    return log


@st.cache_data(show_spinner="Loading RunLog...")
def load_bytes(data: bytes, name: str) -> dict:
    log = _validate(json.loads(data), name)
    log["_name"] = name
    return log


def mode_of(log: dict) -> str:
    return str(log["meta"].get("mode", "")).upper()


def pick_default(paths: list[Path], mode: str) -> int:
    for i, p in enumerate(paths):
        if mode.lower().replace("_", "") in p.stem.lower().replace("_", ""):
            return i
    return 0


def frame_at(log: dict, t_idx: int) -> dict:
    frames = log["frames"]
    return frames[min(t_idx, len(frames) - 1)]


def sat_trail(log: dict, sat_id: str, t_idx: int, back: int = 40) -> tuple[list, list]:
    xs, ys = [], []
    for f in log["frames"][max(0, t_idx - back): t_idx + 1]:
        for s in f["satellites"]:
            if s["id"] == sat_id:
                xs.append(s["pos"][0])
                ys.append(s["pos"][1])
                break
    return xs, ys


def decisions_upto(log: dict, t_idx: int, limit: int = 60, hide: tuple = ("OBSERVE",)) -> list[dict]:
    rows = []
    for f in reversed(log["frames"][: t_idx + 1]):
        for d in f.get("decisions", []):
            a = d["action"]
            if a["type"] in hide:
                continue
            rows.append({
                "t": f["t"], "Actor": a["actor_id"], "Action": a["type"],
                "Benefit": d.get("expected_benefit"), "Why": d.get("reason", ""),
            })
            if len(rows) >= limit:
                return rows
    return rows


def events_upto(log: dict, t_idx: int, limit: int = 60) -> list[dict]:
    rows = []
    for f in reversed(log["frames"][: t_idx + 1]):
        for e in f.get("events", []):
            rows.append({"t": e["t"], "Type": e["type"], "Actor": e.get("actor", ""), "Message": e["msg"]})
            if len(rows) >= limit:
                return rows
    return rows


@st.cache_data(show_spinner=False)
def metric_series(_log: dict, key: str, metric: str) -> list[float]:
    return [float(f.get("metrics", {}).get(metric, 0.0)) for f in _log["frames"]]


TIMELINE_TYPES = ("DODGE", "TUG_REQUEST", "SERVICING", "SERVICED", "RETIRE", "RETIRED", "ALERT", "CONFIRMED")


@st.cache_data(show_spinner=False)
def timeline_events(_log: dict, key: str) -> list[dict]:
    out, seen = [], set()
    for f in _log["frames"]:
        for e in f.get("events", []):
            if e["type"] in TIMELINE_TYPES and (e["type"], e.get("actor"), e["t"]) not in seen:
                seen.add((e["type"], e.get("actor"), e["t"]))
                out.append({"t": e["t"], "type": e["type"], "actor": e.get("actor", ""), "msg": e["msg"]})
    return out
