from __future__ import annotations
"""Load and replay historical NASA FIRMS active-fire detections."""

import csv
import math

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path


EARTH_RADIUS_KM = 6371.0088


@dataclass(frozen=True)
class FireDetection:
    """One historical active-fire observation."""

    latitude: float
    longitude: float
    x_km: float
    y_km: float
    timestamp_utc: datetime
    confidence: str
    frp_mw: float | None
    satellite: str
    instrument: str
    daynight: str


def geographic_to_local_km(
    latitude: float,
    longitude: float,
    origin_latitude: float,
    origin_longitude: float,
) -> tuple[float, float]:
    """Convert geographic coordinates to local east/north kilometres."""

    if not -90 <= latitude <= 90:
        raise ValueError("Latitude must be between -90 and 90")

    if not -180 <= longitude <= 180:
        raise ValueError("Longitude must be between -180 and 180")

    if not -90 <= origin_latitude <= 90:
        raise ValueError("Origin latitude must be between -90 and 90")

    if not -180 <= origin_longitude <= 180:
        raise ValueError("Origin longitude must be between -180 and 180")

    delta_lat = math.radians(latitude - origin_latitude)

    delta_lon_degrees = (
        (longitude - origin_longitude + 180) % 360
    ) - 180

    delta_lon = math.radians(delta_lon_degrees)

    x_km = (
        EARTH_RADIUS_KM
        * math.cos(math.radians(origin_latitude))
        * delta_lon
    )

    y_km = EARTH_RADIUS_KM * delta_lat

    return x_km, y_km


def parse_acquisition_time(date_text: str, time_text: str) -> datetime:
    """Parse FIRMS date and HHMM acquisition time as UTC."""

    acquired_date = date.fromisoformat(date_text.strip())

    acquisition_time = int(time_text.strip())

    if not 0 <= acquisition_time <= 2359:
        raise ValueError("Acquisition time must be between 0000 and 2359")

    hour = acquisition_time // 100
    minute = acquisition_time % 100

    if minute > 59:
        raise ValueError("Invalid acquisition minute")

    return datetime.combine(
        acquired_date,
        time(hour, minute),
        tzinfo=timezone.utc,
    )


def load_fire_detections(
    csv_path: str | Path,
    origin_latitude: float,
    origin_longitude: float,
) -> tuple[FireDetection, ...]:
    """Load FIRMS CSV records and convert them into local coordinates."""

    detections = []

    required_columns = {
        "latitude",
        "longitude",
        "acq_date",
        "acq_time",
        "satellite",
        "instrument",
        "confidence",
        "frp",
        "daynight",
    }

    with Path(csv_path).open(
        "r", newline="", encoding="utf-8-sig"
    ) as csv_file:

        reader = csv.DictReader(csv_file)

        if reader.fieldnames is None:
            raise ValueError("CSV file has no header")

        available_columns = {
            column.strip() for column in reader.fieldnames
        }

        missing = required_columns - available_columns

        if missing:
            raise ValueError(
                f"CSV is missing required columns: {sorted(missing)}"
            )

        for row_number, row in enumerate(reader, start=2):
            try:
                latitude = float(row["latitude"])
                longitude = float(row["longitude"])

                x_km, y_km = geographic_to_local_km(
                    latitude,
                    longitude,
                    origin_latitude,
                    origin_longitude,
                )

                timestamp = parse_acquisition_time(
                    row["acq_date"],
                    row["acq_time"],
                )

                frp_text = row["frp"].strip()
                frp_mw = float(frp_text) if frp_text else None

                if frp_mw is not None and frp_mw < 0:
                    raise ValueError("FRP cannot be negative")

                detections.append(
                    FireDetection(
                        latitude=latitude,
                        longitude=longitude,
                        x_km=x_km,
                        y_km=y_km,
                        timestamp_utc=timestamp,
                        confidence=row["confidence"].strip(),
                        frp_mw=frp_mw,
                        satellite=row["satellite"].strip(),
                        instrument=row["instrument"].strip(),
                        daynight=row["daynight"].strip(),
                    )
                )

            except (ValueError, TypeError) as error:
                raise ValueError(
                    f"Invalid FIRMS record at CSV row {row_number}: {error}"
                ) from error

    detections.sort(key=lambda detection: detection.timestamp_utc)

    return tuple(detections)


@dataclass(frozen=True)
class FireReplay:
    """Replay historical detections against elapsed simulation minutes."""

    detections: tuple[FireDetection, ...]
    start_time_utc: datetime

    def __post_init__(self):
        if self.start_time_utc.tzinfo is None:
            raise ValueError("Replay start time must include a timezone")

        if self.start_time_utc.utcoffset() != timedelta(0):
            raise ValueError("Replay start time must be in UTC")

    def at(self, elapsed_min: float) -> tuple[FireDetection, ...]:
        """Return all detections observed by the requested simulation time."""

        if elapsed_min < 0:
            raise ValueError("Elapsed simulation time cannot be negative")

        cutoff = self.start_time_utc + timedelta(minutes=elapsed_min)

        return tuple(
            detection
            for detection in self.detections
            if detection.timestamp_utc <= cutoff
        )
