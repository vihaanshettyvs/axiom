
import unittest

from sensing.hazardvalue import (
    score_estimate,
    rank_estimates,
    analyze_final_estimates,
)


class TestHazardValue(unittest.TestCase):

    def setUp(self):
        self.estimate = {
            "id": "TEST-01",
            "kind": "wildfire",
            "existence": 0.8,
            "confidence": 0.9,
            "intensity_est": 0.5,
            "growth_est": 0.01,
            "uncertainty_km": 2.0,
            "confirmed": False,
        }

    def test_score_uses_evidence_weighted_intensity(self):
        result = score_estimate(self.estimate)
        self.assertEqual(result["score"], 36.0)

    def test_ranking_is_highest_first(self):
        low = dict(self.estimate, id="LOW", existence=0.2)
        high = dict(self.estimate, id="HIGH", existence=1.0)

        ranked = rank_estimates([low, high])

        self.assertEqual(ranked[0]["id"], "HIGH")
        self.assertEqual(ranked[1]["id"], "LOW")

    def test_invalid_probability_is_rejected(self):
        invalid = dict(self.estimate, confidence=1.5)

        with self.assertRaises(ValueError):
            score_estimate(invalid)

    def test_negative_uncertainty_is_rejected(self):
        invalid = dict(self.estimate, uncertainty_km=-1)

        with self.assertRaises(ValueError):
            score_estimate(invalid)

    def test_missing_field_is_rejected(self):
        invalid = dict(self.estimate)
        del invalid["intensity_est"]

        with self.assertRaises(ValueError):
            score_estimate(invalid)

    def test_final_estimates_are_ranked(self):
        runlog = {
            "frames": [
                {"estimates": []},
                {"estimates": [self.estimate]},
            ]
        }

        result = analyze_final_estimates(runlog)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "TEST-01")

    def test_empty_runlog_is_rejected(self):
        with self.assertRaises(ValueError):
            analyze_final_estimates({"frames": []})


if __name__ == "__main__":
    unittest.main()
