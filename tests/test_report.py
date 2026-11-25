
import unittest

from sensing.runlog import load_runlog
from sensing.report import (
    build_run_report,
    compare_runs,
    generate_p4_report,
)


class TestReport(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.brain_on = load_runlog(
            "data/runlogs/runlog_brain_on.json"
        )
        cls.brain_off = load_runlog(
            "data/runlogs/runlog_brain_off.json"
        )

    def test_build_run_report(self):
        report = build_run_report(self.brain_on)

        self.assertEqual(report["mode"], "BRAIN_ON")
        self.assertTrue(report["completed"])
        self.assertEqual(len(report["hazard_estimates"]), 4)
        self.assertIn("observation_analysis", report)

    def test_hazard_estimates_are_ranked(self):
        report = build_run_report(self.brain_on)
        scores = [
            item["score"]
            for item in report["hazard_estimates"]
        ]

        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_compare_runs_bandwidth(self):
        comparison = compare_runs(
            self.brain_on,
            self.brain_off,
        )

        bandwidth = comparison["bandwidth"]

        self.assertEqual(bandwidth["brain_on_mb"], 428.8)
        self.assertEqual(bandwidth["brain_off_mb"], 24840.0)
        self.assertEqual(bandwidth["savings_pct"], 98.27)

    def test_compare_runs_includes_metrics(self):
        comparison = compare_runs(
            self.brain_on,
            self.brain_off,
        )

        metrics = comparison["metrics"]

        self.assertIn("mean_loc_error_km", metrics)
        self.assertIn("fuel_used_kg", metrics)
        self.assertIn("attention_alerts", metrics)

        self.assertAlmostEqual(
            metrics["mean_loc_error_km"]["difference_on_minus_off"],
            -5.81981,
            places=5,
        )

    def test_generate_complete_report(self):
        report = generate_p4_report(
            self.brain_on,
            self.brain_off,
        )

        self.assertEqual(report["project"], "ORBITA")
        self.assertEqual(
            report["module"],
            "P4 - Data and Sensing",
        )

        self.assertEqual(
            report["runs"]["brain_on"]["mode"],
            "BRAIN_ON",
        )

        self.assertEqual(
            report["runs"]["brain_off"]["mode"],
            "BRAIN_OFF",
        )

        self.assertIn("comparison", report)


if __name__ == "__main__":
    unittest.main()
