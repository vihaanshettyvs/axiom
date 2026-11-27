
import unittest
from pathlib import Path

from sensing.runlog import (
    load_runlog,
    get_final_metrics,
    get_brain_estimates,
    get_run_summary,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNLOG_DIR = PROJECT_ROOT / "data" / "runlogs"


class TestRunLog(unittest.TestCase):

    def test_load_brain_on(self):
        runlog = load_runlog(RUNLOG_DIR / "runlog_brain_on.json")
        self.assertEqual(len(runlog["frames"]), 180)
        self.assertEqual(runlog["meta"]["mode"], "BRAIN_ON")

    def test_load_brain_off(self):
        runlog = load_runlog(RUNLOG_DIR / "runlog_brain_off.json")
        self.assertEqual(len(runlog["frames"]), 180)
        self.assertEqual(runlog["meta"]["mode"], "BRAIN_OFF")

    def test_final_metrics_are_from_last_frame(self):
        runlog = load_runlog(RUNLOG_DIR / "runlog_brain_on.json")
        metrics = get_final_metrics(runlog)

        self.assertAlmostEqual(metrics["bandwidth_mb"], 428.8)
        self.assertAlmostEqual(metrics["fuel_used_kg"], 0.968)

    def test_brain_estimates_are_separate_from_ground_truth(self):
        runlog = load_runlog(RUNLOG_DIR / "runlog_brain_on.json")
        estimates = get_brain_estimates(runlog)

        self.assertEqual(len(estimates), 4)
        self.assertNotIn("hazards", estimates[0])

    def test_summary_is_available(self):
        runlog = load_runlog(RUNLOG_DIR / "runlog_brain_off.json")
        summary = get_run_summary(runlog)

        self.assertEqual(summary["mode"], "BRAIN_OFF")
        self.assertTrue(summary["completed"])


if __name__ == "__main__":
    unittest.main()
