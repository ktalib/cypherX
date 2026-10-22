"""
Weather for the home dashboards — Open-Meteo (free, no API key).

Uses the same place as the Widget Screen weather card (set there, or found from
the internet address on first run); the Settings here can pin a place instead.
Besides temperature and conditions it gives a solar outlook for today from the
forecast sunshine energy (shortwave radiation, MJ/m²), so you know whether the
panels will fill the battery.

Fail-soft: without internet the last good reading is kept and the cards simply
hide the weather.
"""
import json
import time
import urllib.parse
import urllib.request

from app.server.services import ThreadService

API = "https://api.open-meteo.com/v1/forecast"
REFRESH_S = 15 * 60
DEFAULT_PLACE = {"name": "Lagos, NG", "lat": 6.6018, "lon": 3.3515}

# WMO weather code → (description, day icon, night icon); icons are in app/icons.py
WMO = {
    0: ("Clear", "sun", "moon"), 1: ("Mainly clear", "sun", "moon"), 2: ("Partly cloudy", "cloud_sun", "cloud"),
    3: ("Overcast", "cloud", "cloud"), 45: ("Fog", "cloud_fog", "cloud_fog"), 48: ("Fog", "cloud_fog", "cloud_fog"),
    51: ("Light drizzle", "cloud_drizzle", "cloud_drizzle"), 53: ("Drizzle", "cloud_drizzle", "cloud_drizzle"),
    55: ("Heavy drizzle", "cloud_drizzle", "cloud_drizzle"), 61: ("Light rain", "cloud_rain", "cloud_rain"),
    63: ("Rain", "cloud_rain", "cloud_rain"), 65: ("Heavy rain", "cloud_rain", "cloud_rain"),
    80: ("Showers", "cloud_rain", "cloud_rain"), 81: ("Showers", "cloud_rain", "cloud_rain"),
    82: ("Heavy showers", "cloud_rain", "cloud_rain"), 95: ("Thunderstorm", "cloud_lightning", "cloud_lightning"),
    96: ("Thunderstorm", "cloud_lightning", "cloud_lightning"), 99: ("Thunderstorm", "cloud_lightning", "cloud_lightning"),
}


def solar_outlook(mj_per_m2):
    """Today's sunshine energy → a word and a 0–1 score (Lagos clear-sky days reach about 20 MJ/m²)."""
    if mj_per_m2 is None:
        return None, None
    score = max(0.0, min(1.0, mj_per_m2 / 20.0))
    word = "great" if mj_per_m2 >= 18 else "good" if mj_per_m2 >= 12 else "fair" if mj_per_m2 >= 7 else "poor"
    return word, score


def parse(data, place):
    cur = data.get("current") or {}
    daily = data.get("daily") or {}
    code = int(cur.get("weather_code", 3))
    is_day = bool(cur.get("is_day", 1))
    desc, day_icon, night_icon = WMO.get(code, ("—", "cloud", "cloud"))

    def first(key):
        v = daily.get(key) or [None]
        return v[0]
    rad = first("shortwave_radiation_sum")
    word, score = solar_outlook(rad)
    return {
        "place": place["name"], "temp": cur.get("temperature_2m"), "feels": cur.get("apparent_temperature"),
        "humidity": cur.get("relative_humidity_2m"), "wind": cur.get("wind_speed_10m"),
        "cloud": cur.get("cloud_cover"), "code": code, "desc": desc, "is_day": is_day,
        "icon": day_icon if is_day else night_icon,
        "high": first("temperature_2m_max"), "low": first("temperature_2m_min"),
        "solar_mj": rad, "solar": word, "solar_score": score, "ts": time.time(),
    }


def fetch(place, get=None):
    q = {"latitude": f"{place['lat']:.4f}", "longitude": f"{place['lon']:.4f}", "timezone": "auto",
         "forecast_days": 1,
         "current": "temperature_2m,apparent_temperature,relative_humidity_2m,is_day,weather_code,"
                    "cloud_cover,wind_speed_10m",
         "daily": "temperature_2m_max,temperature_2m_min,shortwave_radiation_sum"}
    url = f"{API}?{urllib.parse.urlencode(q)}"
    if get is None:
        with urllib.request.urlopen(url, timeout=15) as r:
            raw = r.read()
    else:
        raw = get(url)
    return parse(json.loads(raw.decode("utf-8")), place)


class WeatherService(ThreadService):
    id = "weather"
    title = "Weather"
    description = "Temperature, conditions and today's solar outlook for the dashboards (Open-Meteo, free)."
    icon = "cloud_sun"
    default_enabled = True
    settings_schema = [
        ("place", "Place name", "str", "", "Leave empty to use the Widget Screen weather card's place"),
        ("lat", "Latitude", "str", "", "e.g. 6.6018"),
        ("lon", "Longitude", "str", "", "e.g. 3.3515"),
    ]

    def __init__(self, place_source=None, get=None):
        """place_source: callable → {"name", "lat", "lon"} or None (the Widget Screen card's place)."""
        super().__init__()
        self.place_source = place_source or (lambda: None)
        self.get = get
        self.now = None               # the last good reading (dict from parse)
        self.error = ""

    def place(self):
        try:
            lat, lon = float(self.setting("lat")), float(self.setting("lon"))
            return {"name": (self.setting("place") or "").strip() or f"{lat:.2f}, {lon:.2f}", "lat": lat, "lon": lon}
        except (TypeError, ValueError):
            pass
        try:
            p = self.place_source()
            if p and "lat" in p and "lon" in p:
                return {"name": p.get("name") or "Home", "lat": float(p["lat"]), "lon": float(p["lon"])}
        except Exception:
            pass
        return DEFAULT_PLACE

    def refresh_now(self):
        place = self.place()
        try:
            self.now = fetch(place, self.get)
            self.error = ""
        except Exception as e:
            if not self.error:
                self.log(f"No weather for {place['name']}: {e}", "warn")
            self.error = str(e)
        return self.now

    def run(self, stop):
        self.mark_running()
        while not stop.is_set():
            self.refresh_now()
            stop.wait(REFRESH_S if not self.error else 120)

    def info(self):
        w = self.now
        if not w:
            return [f"Place: {self.place()['name']}", "No reading yet" + (f" ({self.error})" if self.error else "")]
        lines = [f"{w['place']}: {w['temp']:.0f}°C, {w['desc'].lower()}, humidity {w['humidity']}%",
                 f"Today {w['low']:.0f}–{w['high']:.0f}°C" if w["high"] is not None else ""]
        if w["solar"]:
            lines.append(f"Solar today: {w['solar']} ({w['solar_mj']:.0f} MJ/m²)")
        return [ln for ln in lines if ln]

    def actions(self):
        def now():
            w = self.refresh_now()
            if not w:
                raise RuntimeError(self.error or "no answer")
            return f"{w['place']}: {w['temp']:.0f}°C, {w['desc'].lower()}"
        return [("Update now", now)]
