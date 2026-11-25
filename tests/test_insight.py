
import unittest
from pathlib import Path

from sensing.runlog import load_runlog
from sensing.insight import analyze_observations, compare_bandwidth


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNLOG_DIR = PROJECT_ROOT / "data" / "runlogs"


class TestInsight(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.brain_on = load_runlog(
            RUNLOG_DIR / "runlog_brain_on.json"
        )
        cls.brain_off = load_runlog(
            RUNLOG_DIR / "runlog_brain_off.json"
        )

    def test_brain_on_observation_analysis(self):
        result = analyze_observations(self.brain_on)

        self.assertEqual(result["observation_count"], 1577)
        self.assertEqual(result["total_detections"], 495)
        self.assertEqual(result["undelivered_count"], 521)

    def test_brain_off_observation_analysis(self):
        result = analyze_observations(self.brain_off)

        self.assertEqual(result["observation_count"], 1821)
        self.assertEqual(result["total_detections"], 142)
        self.assertEqual(result["undelivered_count"], 444)

    def test_bandwidth_comparison(self):
        result = compare_bandwidth(
            self.brain_on,
            self.brain_off
        )

        self.assertAlmostEqual(result["brain_on_mb"], 428.8)
        self.assertAlmostEqual(result["brain_off_mb"], 24840.0)
        self.assertAlmostEqual(result["savings_pct"], 98.27, places=2)

    def test_undelivered_observations_are_excluded_from_latency(self):
        sample = {
            "frames": [
                {
                    "observations": [
                        {"t": 2, "delivered_t": 5},
                        {"t": 3, "delivered_t": None},
                    ]
                }
            ]
        }

        result = analyze_observations(sample)

        self.assertEqual(result["delivered_count"], 1)
        self.assertEqual(result["undelivered_count"], 1)
        self.assertEqual(result["mean_delivery_latency_min"], 3.0)


    def test_negative_observation_size_is_rejected(self):
        sample = {
            "frames": [{
                "observations": [
                    {
                        "size_raw_mb": -1,
                        "size_comp_mb": 0.5,
                        "detections": [],
                    }
                ]
            }]
        }

        with self.assertRaises(ValueError):
            analyze_observations(sample)


if __name__ == "__main__":
    unittest.main()
