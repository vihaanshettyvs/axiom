import unittest

import numpy as np

from sensing.telemetry import TelemetryState, advance_telemetry


class TestTelemetry(unittest.TestCase):

    def test_battery_degradation(self):
        state = TelemetryState(
            satellite_id="SAT-01",
            failure_mode="battery_degradation",
        )

        reading = advance_telemetry(
            state, 10, np.random.default_rng(42)
        )

        self.assertLess(reading.battery_health_pct, 100.0)
        self.assertLess(reading.battery_pct, 100.0)

    def test_solar_degradation(self):
        state = TelemetryState(
            satellite_id="SAT-02",
            failure_mode="solar_degradation",
        )

        reading = advance_telemetry(
            state, 10, np.random.default_rng(42)
        )

        self.assertLess(reading.solar_output_pct, 100.0)

    def test_thermal_stress(self):
        state = TelemetryState(
            satellite_id="SAT-03",
            failure_mode="thermal_stress",
        )

        reading = advance_telemetry(
            state, 10, np.random.default_rng(42)
        )

        self.assertGreater(reading.temperature_c, 22.0)

    def test_propulsion_failure(self):
        state = TelemetryState(
            satellite_id="SAT-04",
            failure_mode="propulsion_failure",
        )

        reading = advance_telemetry(
            state, 10, np.random.default_rng(42)
        )

        self.assertLess(reading.propulsion_health_pct, 100.0)

    def test_percentages_stay_in_range(self):
        state = TelemetryState(
            satellite_id="SAT-05",
            battery_pct=0.01,
            failure_mode="battery_degradation",
        )

        reading = advance_telemetry(
            state, 10000, np.random.default_rng(42)
        )

        for value in (
            reading.battery_pct,
            reading.battery_health_pct,
            reading.solar_output_pct,
            reading.propulsion_health_pct,
        ):
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 100.0)

    def test_same_seed_gives_same_reading(self):
        state_a = TelemetryState(
            satellite_id="SAT-06",
            failure_mode="thermal_stress",
        )
        state_b = TelemetryState(
            satellite_id="SAT-06",
            failure_mode="thermal_stress",
        )

        reading_a = advance_telemetry(
            state_a, 10, np.random.default_rng(123)
        )
        reading_b = advance_telemetry(
            state_b, 10, np.random.default_rng(123)
        )

        self.assertEqual(reading_a, reading_b)

    def test_zero_time_is_rejected(self):
        state = TelemetryState(satellite_id="SAT-07")

        with self.assertRaises(ValueError):
            advance_telemetry(
                state, 0, np.random.default_rng(42)
            )


if __name__ == "__main__":
    unittest.main()
