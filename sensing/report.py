
from typing import Any

from sensing.hazardvalue import analyze_final_estimates
from sensing.insight import analyze_observations, compare_bandwidth


COMPARISON_METRICS = (
    "mean_loc_error_km",
    "mean_time_to_detect_min",
    "mean_time_to_localize_min",
    "mean_detection_latency_min",
    "false_alarm_tracks",
    "fuel_used_kg",
    "bandwidth_mb",
    "attention_alerts",
    "sats_lost",
    "expected_sat_loss",
    "uncontrolled_dead",
    "retired",
    "serviced",
    "dodges",
    "observations",
    "final_entropy_bits",
)


def build_run_report(runlog: dict[str, Any]) -> dict[str, Any]:
    """Build a P4 analysis report for one ORBITA RunLog."""

    if not runlog.get("frames"):
        raise ValueError("RunLog contains no frames.")

    summary = runlog.get("summary", {})

    return {
        "mode": summary.get("mode", runlog.get("meta", {}).get("mode")),
        "seed": summary.get("seed", runlog.get("meta", {}).get("seed")),
        "completed": summary.get("completed", False),
        "summary": summary,
        "hazard_estimates": analyze_final_estimates(runlog),
        "observation_analysis": analyze_observations(runlog),
    }


def compare_runs(
    brain_on: dict[str, Any],
    brain_off: dict[str, Any],
) -> dict[str, Any]:
    """Compare selected summary metrics between BRAIN ON and OFF."""

    on_summary = brain_on.get("summary", {})
    off_summary = brain_off.get("summary", {})

    metrics = {}

    for metric in COMPARISON_METRICS:
        on_value = on_summary.get(metric)
        off_value = off_summary.get(metric)

        if (
            isinstance(on_value, (int, float))
            and not isinstance(on_value, bool)
            and isinstance(off_value, (int, float))
            and not isinstance(off_value, bool)
        ):
            metrics[metric] = {
                "brain_on": on_value,
                "brain_off": off_value,
                "difference_on_minus_off": round(
                    on_value - off_value, 5
                ),
            }

    return {
        "bandwidth": compare_bandwidth(brain_on, brain_off),
        "metrics": metrics,
        "detection_times_min": {
            "brain_on": on_summary.get("time_to_detect_min", {}),
            "brain_off": off_summary.get("time_to_detect_min", {}),
        },
        "localization_times_min": {
            "brain_on": on_summary.get("time_to_localize_min", {}),
            "brain_off": off_summary.get("time_to_localize_min", {}),
        },
    }


def generate_p4_report(
    brain_on: dict[str, Any],
    brain_off: dict[str, Any],
) -> dict[str, Any]:
    """Generate the complete P4 report from two ORBITA RunLogs."""

    return {
        "project": "ORBITA",
        "module": "P4 - Data and Sensing",
        "runs": {
            "brain_on": build_run_report(brain_on),
            "brain_off": build_run_report(brain_off),
        },
        "comparison": compare_runs(brain_on, brain_off),
    }
