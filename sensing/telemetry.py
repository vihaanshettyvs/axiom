from __future__ import annotations
"""Deterministic simulated satellite health telemetry."""

from dataclasses import dataclass
from typing import Literal

import numpy as np


FailureMode = Literal[
    "battery_degradation",
    "solar_degradation",
    "thermal_stress",
    "propulsion_failure",
]


@dataclass
class TelemetryState:
    """Persistent health state for one simulated satellite."""

    satellite_id: str
    battery_pct: float = 100.0
    battery_health_pct: float = 100.0
    solar_output_pct: float = 100.0
    temperature_c: float = 22.0
    propulsion_health_pct: float = 100.0
    failure_mode: FailureMode | None = None
    elapsed_min: float = 0.0


@dataclass(frozen=True)
class TelemetryReading:
    """A snapshot of satellite health at one simulation time."""

    satellite_id: str
    elapsed_min: float
    battery_pct: float
    battery_health_pct: float
    solar_output_pct: float
    temperature_c: float
    propulsion_health_pct: float
    failure_mode: str | None


def advance_telemetry(
    state: TelemetryState,
    dt_min: float,
    rng: np.random.Generator,
) -> TelemetryReading:
    """Advance one satellite's telemetry by dt_min simulation minutes."""

    if dt_min <= 0:
        raise ValueError("dt_min must be greater than zero")

    mode = state.failure_mode

    # Normal operating changes: small, bounded fluctuations.
    state.battery_pct -= 0.015 * dt_min
    state.temperature_c += rng.normal(0.0, 0.08)
    state.solar_output_pct += rng.normal(0.0, 0.03)

    # Apply the selected simulated failure.
    if mode == "battery_degradation":
        state.battery_health_pct -= 0.025 * dt_min

    elif mode == "solar_degradation":
        state.solar_output_pct -= 0.04 * dt_min

    elif mode == "thermal_stress":
        state.temperature_c += 0.12 * dt_min

    elif mode == "propulsion_failure":
        state.propulsion_health_pct -= 0.035 * dt_min

    # Keep percentage-based measurements within sensible limits.
    state.battery_pct = float(np.clip(state.battery_pct, 0.0, 100.0))
    state.battery_health_pct = float(
        np.clip(state.battery_health_pct, 0.0, 100.0)
    )
    state.solar_output_pct = float(
        np.clip(state.solar_output_pct, 0.0, 100.0)
    )
    state.propulsion_health_pct = float(
        np.clip(state.propulsion_health_pct, 0.0, 100.0)
    )

    state.elapsed_min += dt_min

    return TelemetryReading(
        satellite_id=state.satellite_id,
        elapsed_min=state.elapsed_min,
        battery_pct=state.battery_pct,
        battery_health_pct=state.battery_health_pct,
        solar_output_pct=state.solar_output_pct,
        temperature_c=state.temperature_c,
        propulsion_health_pct=state.propulsion_health_pct,
        failure_mode=mode,
    )
