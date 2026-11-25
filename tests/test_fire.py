import tempfile
import unittest

from datetime import datetime, timezone
from pathlib import Path

from sensing.fire import (
    FireReplay,
    geographic_to_local_km,
    load_fire_detections,
    parse_acquisition_time,
)


class TestFireSensing(unittest.TestCase):

    def test_origin_converts_to_zero(self):
        x, y = geographic_to_local_km(0, 0, 0, 0)

        self.assertAlmostEqual(x, 0)
        self.assertAlmostEqual(y, 0)

    def test_one_degree_north(self):
        x, y = geographic_to_local_km(1, 0, 0, 0)

        self.assertAlmostEqual(x, 0, places=5)
        self.assertAlmostEqual(y, 111.2, delta=0.2)

    def test_invalid_latitude_is_rejected(self):
        with self.assertRaises(ValueError):
            geographic_to_local_km(95, 0, 0, 0)

    def test_acquisition_time_is_utc(self):
        result = parse_acquisition_time("2023-07-12", "3")

        self.assertEqual(
            result,
            datetime(2023, 7, 12, 0, 3, tzinfo=timezone.utc),
        )

    def test_load_real_sample(self):
        sample = Path("data/firms/sample_viirs_snpp.csv")

        detections = load_fire_detections(
            sample,
            origin_latitude=0,
            origin_longitude=0,
        )

        self.assertGreater(len(detections), 0)
        self.assertTrue(all(d.frp_mw is None or d.frp_mw >= 0
                            for d in detections))

    def test_replay_respects_elapsed_time(self):
        csv_text = (
            "latitude,longitude,acq_date,acq_time,"
            "satellite,instrument,confidence,frp,daynight\n"
            "0,0,2023-07-12,3,N,VIIRS,n,0.83,N\n"
            "1,1,2023-07-12,103,N,VIIRS,h,1.20,D\n"
        )

        with tempfile.TemporaryDirectory() as folder:
            csv_path = Path(folder) / "sample.csv"
            csv_path.write_text(csv_text, encoding="utf-8")

            detections = load_fire_detections(csv_path, 0, 0)

        replay = FireReplay(
            detections=detections,
            start_time_utc=detections[0].timestamp_utc,
        )

        self.assertEqual(len(replay.at(0)), 1)
        self.assertEqual(len(replay.at(59)), 1)
        self.assertEqual(len(replay.at(60)), 2)


if __name__ == "__main__":
    unittest.main()
