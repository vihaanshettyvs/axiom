from __future__ import annotations

from typing import Any


def analyze_observations(runlog: dict[str, Any]) -> dict[str, Any]:
    """Analyse observation volume, compression and delivery performance."""

    observations = [
        observation
        for frame in runlog["frames"]
        for observation in frame.get("observations", [])
    ]

    total_raw_mb = 0.0
    total_comp_mb = 0.0
    total_detections = 0
    negative_scans = 0
    delivered_count = 0
    undelivered_count = 0
    latencies = []
    sources = {}

    for observation in observations:
        raw_mb = float(observation.get("size_raw_mb", 0))
        comp_mb = float(observation.get("size_comp_mb", 0))

        if raw_mb < 0 or comp_mb < 0:
            raise ValueError("Observation sizes cannot be negative.")

        total_raw_mb += raw_mb
        total_comp_mb += comp_mb

        detections = observation.get("detections", [])
        total_detections += len(detections)

        if not detections:
            negative_scans += 1

        source = observation.get("source", "UNKNOWN")
        sources[source] = sources.get(source, 0) + 1

        delivered_t = observation.get("delivered_t")

        if delivered_t is None:
            undelivered_count += 1
            continue

        delivered_count += 1

        if observation.get("t") is not None:
            latency = float(delivered_t) - float(observation["t"])

            if latency < 0:
                raise ValueError(
                    "Delivery time cannot precede observation time."
                )

            latencies.append(latency)

    saved_mb = total_raw_mb - total_comp_mb
    savings_pct = (
        (saved_mb / total_raw_mb) * 100
        if total_raw_mb > 0
        else 0.0
    )

    return {
        "observation_count": len(observations),
        "total_raw_mb": round(total_raw_mb, 4),
        "total_comp_mb": round(total_comp_mb, 4),
        "saved_mb": round(saved_mb, 4),
        "savings_pct": round(savings_pct, 2),
        "total_detections": total_detections,
        "negative_scans": negative_scans,
        "delivered_count": delivered_count,
        "undelivered_count": undelivered_count,
        "mean_delivery_latency_min": (
            round(sum(latencies) / len(latencies), 4)
            if latencies else None
        ),
        "max_delivery_latency_min": (
            round(max(latencies), 4)
            if latencies else None
        ),
        "observations_by_source": sources,
    }


def compare_bandwidth(
    brain_on: dict[str, Any],
    brain_off: dict[str, Any],
) -> dict[str, Any]:
    """Compare final cumulative bandwidth usage between two runs."""

    on_metrics = brain_on["frames"][-1].get("metrics", {})
    off_metrics = brain_off["frames"][-1].get("metrics", {})

    on_mb = float(on_metrics.get("bandwidth_mb", 0))
    off_mb = float(off_metrics.get("bandwidth_mb", 0))

    if on_mb < 0 or off_mb < 0:
        raise ValueError("Bandwidth values cannot be negative.")

    saved_mb = off_mb - on_mb
    savings_pct = (saved_mb / off_mb) * 100 if off_mb > 0 else 0.0

    return {
        "brain_on_mb": round(on_mb, 4),
        "brain_off_mb": round(off_mb, 4),
        "saved_mb": round(saved_mb, 4),
        "savings_pct": round(savings_pct, 2),
    }
