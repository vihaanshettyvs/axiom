
import json
from pathlib import Path
from typing import Any


REQUIRED_KEYS = {"meta", "scenario", "frames", "summary"}


def load_runlog(path: str | Path) -> dict[str, Any]:
    """Load and validate an ORBITA RunLog JSON file."""

    file_path = Path(path)

    if not file_path.exists():
        raise FileNotFoundError(f"RunLog not found: {file_path}")

    with file_path.open("r", encoding="utf-8") as file:
        runlog = json.load(file)

    if not isinstance(runlog, dict):
        raise ValueError("RunLog must contain a JSON object.")

    missing = REQUIRED_KEYS - runlog.keys()
    if missing:
        raise ValueError(f"RunLog is missing required sections: {sorted(missing)}")

    if not isinstance(runlog["frames"], list):
        raise ValueError("RunLog 'frames' must be a list.")

    if not runlog["frames"]:
        raise ValueError("RunLog contains no simulation frames.")

    return runlog


def get_final_metrics(runlog: dict[str, Any]) -> dict[str, Any]:
    """Return cumulative metrics from the final simulation frame."""

    frames = runlog["frames"]
    return frames[-1].get("metrics", {})


def get_brain_estimates(runlog: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the brain's estimates from the final frame.

    Deliberately does not read ground-truth hazards.
    """

    frames = runlog["frames"]
    return frames[-1].get("estimates", [])


def get_run_summary(runlog: dict[str, Any]) -> dict[str, Any]:
    """Return the simulation summary."""

    return runlog.get("summary", {})
