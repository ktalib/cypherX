import os
import shutil
import tempfile
import unittest
from pathlib import Path
from app.home3d.energy import EnergyLog

H = 3600.0
DAY = 86400.0


class TestEnergyLog(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="cyberops_test_energy_")
        self.path = Path(self.test_dir) / "energy.json"
        self.log = EnergyLog(self.path)
        self.t0 = 1_800_000_000.0

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_empty_log_has_no_estimates(self):
        self.assertIsNone(self.log.burn_rate(self.t0))
        self.assertIsNone(self.log.units_left(self.t0))
        self.assertIsNone(self.log.days_left(self.t0))
        self.assertIsNone(self.log.price_per_kwh())

    def test_burn_rate_from_readings(self):
        self.log.add_reading(100, ts=self.t0)
        self.log.add_reading(94, ts=self.t0 + DAY)
        self.assertAlmostEqual(self.log.burn_rate(self.t0 + DAY), 6.0)
        self.assertAlmostEqual(self.log.days_left(self.t0 + DAY), 94 / 6.0)

    def test_tokens_between_readings_count_as_added_units(self):
        self.log.add_reading(10, ts=self.t0)
        self.log.add_token(5000, 24, ts=self.t0 + 12 * H)
        self.log.add_reading(28, ts=self.t0 + DAY)
        # 10 + 24 - 28 = 6 kWh used in a day
        self.assertAlmostEqual(self.log.burn_rate(self.t0 + DAY), 6.0)

    def test_units_left_counts_down_and_adds_new_tokens(self):
        self.log.add_reading(100, ts=self.t0)
        self.log.add_reading(94, ts=self.t0 + DAY)
        self.log.add_token(2000, 10, ts=self.t0 + 1.25 * DAY)
        # half a day after the last reading: 94 + 10 - 3
        self.assertAlmostEqual(self.log.units_left(self.t0 + 1.5 * DAY), 101.0)

    def test_short_span_gives_no_rate(self):
        self.log.add_reading(100, ts=self.t0)
        self.log.add_reading(99.5, ts=self.t0 + H)
        self.assertIsNone(self.log.burn_rate(self.t0 + H))

    def test_price_per_kwh(self):
        self.log.add_token(5000, 20)
        self.log.add_token(3000, 12)
        self.assertAlmostEqual(self.log.price_per_kwh(), 250.0)

    def test_outages_open_close_and_hours(self):
        self.assertEqual(self.log.grid_changed(True, self.t0), None)
        self.assertEqual(self.log.grid_changed(False, self.t0 + H), "off")
        self.assertEqual(self.log.grid_changed(False, self.t0 + 2 * H), None)
        self.assertEqual(self.log.grid_changed(True, self.t0 + 3 * H), "on")
        self.assertAlmostEqual(self.log.outage_hours(self.t0, self.t0 + 4 * H), 2.0)
        # an outage still open counts up to now
        self.log.grid_changed(False, self.t0 + 5 * H)
        self.assertAlmostEqual(self.log.outage_hours(self.t0, self.t0 + 6 * H), 3.0)

    def test_persists_and_removes(self):
        self.log.add_token(1000, 4, ts=self.t0)
        self.log.add_battery(pct=80, volts=25.4, ts=self.t0)
        self.log.grid_detect = True
        again = EnergyLog(self.path)
        self.assertEqual(len(again.tokens), 1)
        self.assertEqual(again.last_battery()["volts"], 25.4)
        self.assertTrue(again.grid_detect)
        again.remove("tokens", again.tokens[0])
        self.assertEqual(EnergyLog(self.path).tokens, [])

    def test_corrupt_file_starts_empty(self):
        self.path.write_text("{not json")
        self.assertEqual(EnergyLog(self.path).tokens, [])


if __name__ == "__main__":
    unittest.main()
