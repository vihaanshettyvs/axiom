from __future__ import annotations

from typing import Any


def score_estimate(estimate: dict[str, Any]) -> dict[str, Any]:
    """Calculate an interpretable evidence-weighted intensity score."""

    required = (
        "id",
        "existence",
        "confidence",
        "intensity_est",
        "growth_est",
        "uncertainty_km",
        "confirmed",
    )

    missing = [key for key in required if key not in estimate]

    if missing:
        raise ValueError(f"Estimate is missing fields: {missing}")

    existence = float(estimate["existence"])
    confidence = float(estimate["confidence"])
    intensity = float(estimate["intensity_est"])
    growth = float(estimate["growth_est"])
    uncertainty = float(estimate["uncertainty_km"])

    for name, value in (
        ("existence", existence),
        ("confidence", confidence),
        ("intensity_est", intensity),
    ):
        if not 0 <= value <= 1:
            raise ValueError(f"{name} must be between 0 and 1.")

    if uncertainty < 0:
        raise ValueError("uncertainty_km cannot be negative.")

    score = 100 * existence * confidence * intensity

    return {
        "id": estimate["id"],
        "kind": estimate.get("kind", "unknown"),
        "score": round(score, 2),
        "existence": existence,
        "confidence": confidence,
        "intensity": intensity,
        "growth_est": growth,
        "uncertainty_km": uncertainty,
        "confirmed": bool(estimate["confirmed"]),
    }


def rank_estimates(
    estimates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Rank estimates by evidence-weighted intensity."""

    scored = [score_estimate(e) for e in estimates]

    return sorted(
        scored,
        key=lambda item: item["score"],
        reverse=True,
    )


def analyze_final_estimates(
    runlog: dict[str, Any],
) -> list[dict[str, Any]]:
    """Analyse estimates from the final frame, not ground-truth hazards."""

    if not runlog.get("frames"):
        raise ValueError("RunLog contains no frames.")

    final_frame = runlog["frames"][-1]

    return rank_estimates(final_frame.get("estimates", []))
