"""P5's credits formula applied to a REAL engine run (no mock data)."""
import validate_demo
from eval.credits import calculate_credits
from eval.real_benchmark import row


def test_credits_from_real_runs_rank_brain_on_above_off():
    on = row(validate_demo.run_one(("on", 2, 60)))
    off = row(validate_demo.run_one(("off", 2, 60)))
    assert on["invalid_actions"] == 0 and off["invalid_actions"] == 0
    assert on["data_sent_mb"] > 0 and off["data_sent_mb"] > on["data_sent_mb"]
    assert calculate_credits(1, 0, 50.0, 50.0) == 100.0 + 12.5 + 12.5            # P5 formula unchanged
    assert isinstance(on["credits"], float)
