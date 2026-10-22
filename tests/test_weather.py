import json
import time
import unittest
from datetime import datetime, timedelta

from app.server.weather import WeatherService, fetch, parse, solar_outlook, DEFAULT_PLACE

SAMPLE = {"current": {"temperature_2m": 29.4, "apparent_temperature": 33.0, "relative_humidity_2m": 78, "is_day": 1,
                      "weather_code": 2, "cloud_cover": 40, "wind_speed_10m": 9.1},
          "daily": {"temperature_2m_max": [32.1], "temperature_2m_min": [24.0], "shortwave_radiation_sum": [16.2]}}


class TestWeather(unittest.TestCase):
    def test_parse_and_solar(self):
        w = parse(SAMPLE, {"name": "Lagos, NG", "lat": 6.6, "lon": 3.35})
        self.assertEqual((w["desc"], w["icon"], w["high"], w["solar"]), ("Partly cloudy", "cloud_sun", 32.1, "good"))
        night = parse({**SAMPLE, "current": {**SAMPLE["current"], "is_day": 0, "weather_code": 0}}, DEFAULT_PLACE)
        self.assertEqual(night["icon"], "moon")
        self.assertEqual(solar_outlook(19)[0], "great")
        self.assertEqual(solar_outlook(3)[0], "poor")
        self.assertEqual(solar_outlook(None), (None, None))

    def test_fetch_url_and_place_choice(self):
        seen = []

        def get(url):
            seen.append(url)
            return json.dumps(SAMPLE).encode()
        w = fetch({"name": "Home", "lat": 6.5, "lon": 3.4}, get)
        self.assertIn("latitude=6.5000", seen[0])
        self.assertIn("shortwave_radiation_sum", seen[0])
        self.assertEqual(w["place"], "Home")
        svc = WeatherService(lambda: {"name": "Ikeja, NG", "lat": 6.6, "lon": 3.3}, get=get)
        self.assertEqual(svc.place()["name"], "Ikeja, NG")              # the Widget Screen card's place
        self.assertEqual(WeatherService(lambda: None).place(), DEFAULT_PLACE)

        def broken(url):
            raise OSError("offline")
        svc.get = broken
        svc.now = w
        svc.refresh_now()                                                 # no internet: keep the last reading
        self.assertEqual(svc.now, w)
        self.assertIn("offline", svc.error)


class TestDailyOutages(unittest.TestCase):
    def test_hours_per_day(self):
        from app.home3d.energy import EnergyLog
        log = EnergyLog.__new__(EnergyLog)
        noon = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
        now = noon.timestamp()
        y_late = (noon - timedelta(days=1)).replace(hour=23).timestamp()
        log.data = {"outages": [
            {"start": y_late, "end": y_late + 2 * 3600},                  # 1 h yesterday, 1 h today
            {"start": now - 1800, "end": None},                           # still off: 0.5 h so far
        ]}
        days = log.daily_outage_hours(7, now)
        self.assertEqual(len(days), 7)
        self.assertAlmostEqual(days[-1][1], 1.5)
        self.assertAlmostEqual(days[-2][1], 1.0)
        self.assertEqual(sum(h for _, h in days[:-2]), 0)
        self.assertAlmostEqual(log.longest_outage_hours(now - 7 * 86400, now), 2.0)


if __name__ == "__main__":
    unittest.main()
