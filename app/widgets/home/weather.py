"""
Live weather card — Open-Meteo (free, no API key).
Location is detected from your IP on first run; click the city to change it,
click the temperature to switch °C / °F.
"""
import json
from datetime import datetime
from urllib.parse import quote

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel, QInputDialog, QPushButton

from app.widgets.home.common import (
    GlassCard, label, hpix, icon_button, http_get, load_setting, save_setting,
    TEXT_SOFT, MUTED
)

REFRESH_MS = 15 * 60 * 1000

# WMO weather code → (description, day icon, night icon)
WMO = {
    0: ("Clear", "sun", "moon"), 1: ("Mainly clear", "sun", "moon"),
    2: ("Partly cloudy", "cloud_sun", "cloud"), 3: ("Overcast", "cloud", "cloud"),
    45: ("Fog", "cloud_fog", "cloud_fog"), 48: ("Rime fog", "cloud_fog", "cloud_fog"),
    51: ("Light drizzle", "cloud_drizzle", "cloud_drizzle"), 53: ("Drizzle", "cloud_drizzle", "cloud_drizzle"),
    55: ("Heavy drizzle", "cloud_drizzle", "cloud_drizzle"), 56: ("Freezing drizzle", "cloud_drizzle", "cloud_drizzle"),
    57: ("Freezing drizzle", "cloud_drizzle", "cloud_drizzle"),
    61: ("Light rain", "cloud_rain", "cloud_rain"), 63: ("Rain", "cloud_rain", "cloud_rain"),
    65: ("Heavy rain", "cloud_rain", "cloud_rain"), 66: ("Freezing rain", "cloud_rain", "cloud_rain"),
    67: ("Freezing rain", "cloud_rain", "cloud_rain"),
    71: ("Light snow", "cloud_snow", "cloud_snow"), 73: ("Snow", "cloud_snow", "cloud_snow"),
    75: ("Heavy snow", "cloud_snow", "cloud_snow"), 77: ("Snow grains", "cloud_snow", "cloud_snow"),
    80: ("Rain showers", "cloud_rain", "cloud_rain"), 81: ("Rain showers", "cloud_rain", "cloud_rain"),
    82: ("Violent showers", "cloud_rain", "cloud_rain"),
    85: ("Snow showers", "cloud_snow", "cloud_snow"), 86: ("Snow showers", "cloud_snow", "cloud_snow"),
    95: ("Thunderstorm", "cloud_lightning", "cloud_lightning"),
    96: ("Thunderstorm, hail", "cloud_lightning", "cloud_lightning"),
    99: ("Thunderstorm, hail", "cloud_lightning", "cloud_lightning"),
}

# Card tint per condition: (day, night)
TINTS = {
    "clear": ("rgba(30,90,150,0.55)", "rgba(16,24,52,0.66)"),
    "cloud": ("rgba(52,66,82,0.60)", "rgba(22,28,38,0.66)"),
    "rain": ("rgba(36,52,72,0.64)", "rgba(18,26,38,0.70)"),
    "snow": ("rgba(80,98,122,0.58)", "rgba(36,46,62,0.66)"),
    "storm": ("rgba(46,38,72,0.66)", "rgba(26,20,44,0.72)"),
}


def describe(code: int, is_day: bool):
    desc, day_icon, night_icon = WMO.get(code, ("—", "cloud", "cloud"))
    return desc, day_icon if is_day else night_icon


def tint_key(code: int) -> str:
    if code in (0, 1):
        return "clear"
    if code >= 95:
        return "storm"
    if code in (71, 73, 75, 77, 85, 86):
        return "snow"
    if code >= 51:
        return "rain"
    return "cloud"


class WeatherWidget(GlassCard):
    data_changed = Signal(object)     # parsed Open-Meteo payload, for skin widgets (sun arc, HUD wind)

    def __init__(self, parent=None):
        super().__init__("WeatherCard", parent=parent)
        self.loc = load_setting("weather_loc", None)          # {"name", "lat", "lon"}
        self.unit = load_setting("weather_unit", "C")
        self._data = load_setting("weather_cache", None)
        self._build_ui()

        if self._data:
            self._render()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(REFRESH_MS)
        QTimer.singleShot(400, self.refresh)

    # ---- UI ----

    def _build_ui(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(16, 12, 12, 12)
        lo.setSpacing(2)

        row = QHBoxLayout()
        row.setSpacing(5)
        pin = QLabel()
        pin.setPixmap(hpix("map_pin", TEXT_SOFT, 13))
        pin.setStyleSheet("background:transparent;border:none;")
        self._city = QPushButton("Locating…")
        self._city.setCursor(Qt.PointingHandCursor)
        self._city.setToolTip("Change location")
        self._city.setStyleSheet("""
            QPushButton { background: transparent; border: none; color: #f1f5f9; padding: 0;
                          font-size: 12px; font-weight: 700; text-align: left; }
            QPushButton:hover { color: #7dd3fc; }
        """)
        self._city.clicked.connect(self.change_city)
        refresh = icon_button("refresh", "Refresh weather", 22, 12, MUTED)
        refresh.clicked.connect(self.refresh)
        row.addWidget(pin)
        row.addWidget(self._city, 1)
        row.addWidget(refresh)
        lo.addLayout(row)

        tr = QHBoxLayout()
        self._temp = QPushButton("--°")
        self._temp.setCursor(Qt.PointingHandCursor)
        self._temp.setToolTip("Switch °C / °F")
        self._temp.setStyleSheet("""
            QPushButton { background: transparent; border: none; color: #ffffff; padding: 0;
                          font-size: 44px; font-weight: 200; text-align: left; }
            QPushButton:hover { color: #e0f2fe; }
        """)
        self._temp.clicked.connect(self.toggle_unit)
        self._icon = QLabel()
        self._icon.setStyleSheet("background:transparent;border:none;")
        self._icon.setPixmap(hpix("cloud", "#ffffff", 40, 1.6))
        tr.addWidget(self._temp)
        tr.addStretch()
        tr.addWidget(self._icon)
        lo.addLayout(tr)

        self._cond = label("Fetching forecast…", TEXT_SOFT, 12, 600, elide=True)
        lo.addWidget(self._cond)
        self._hilo = label("", MUTED, 11, 600, elide=True)
        lo.addWidget(self._hilo)
        lo.addStretch()

        # metrics: wind · humidity · sunrise · sunset
        mrow = QHBoxLayout()
        mrow.setSpacing(8)
        self._metrics = {}
        for key, icon in [("wind", "wind"), ("hum", "droplet"), ("rise", "sunrise"), ("set", "sunset")]:
            box = QHBoxLayout()
            box.setSpacing(3)
            ic = QLabel()
            ic.setPixmap(hpix(icon, MUTED, 12))
            ic.setStyleSheet("background:transparent;border:none;")
            val = label("--", TEXT_SOFT, 10, 700)
            box.addWidget(ic)
            box.addWidget(val)
            mrow.addLayout(box)
            self._metrics[key] = val
        mrow.addStretch()
        lo.addLayout(mrow)
        lo.addSpacing(6)

        # 4-day forecast strip
        frow = QHBoxLayout()
        frow.setSpacing(4)
        self._days = []
        for _ in range(4):
            col = QVBoxLayout()
            col.setSpacing(1)
            d = label("", MUTED, 10, 700)
            d.setAlignment(Qt.AlignCenter)
            ic = QLabel()
            ic.setAlignment(Qt.AlignCenter)
            ic.setStyleSheet("background:transparent;border:none;")
            t = label("", TEXT_SOFT, 10, 600)
            t.setAlignment(Qt.AlignCenter)
            col.addWidget(d)
            col.addWidget(ic)
            col.addWidget(t)
            frow.addLayout(col, 1)
            self._days.append((d, ic, t))
        lo.addLayout(frow)

    # ---- data ----

    def refresh(self):
        if not self.loc:
            self._locate()
            return
        unit = "&temperature_unit=fahrenheit&wind_speed_unit=mph" if self.unit == "F" else ""
        url = ("https://api.open-meteo.com/v1/forecast"
               f"?latitude={self.loc['lat']:.4f}&longitude={self.loc['lon']:.4f}"
               "&current=temperature_2m,relative_humidity_2m,apparent_temperature,is_day,"
               "weather_code,wind_speed_10m,wind_direction_10m"
               "&daily=weather_code,temperature_2m_max,temperature_2m_min,sunrise,sunset,uv_index_max"
               f"&timezone=auto&forecast_days=5{unit}")
        http_get(url, self._on_forecast)

    def _on_forecast(self, data, err):
        try:
            parsed = json.loads(data) if data else None
            if not parsed or "current" not in parsed:
                raise ValueError(err or "bad response")
        except ValueError:
            if not self._data:
                self._cond.setText("Weather offline — click refresh to retry")
            return
        parsed["_unit"] = self.unit
        parsed["_at"] = datetime.now().strftime("%H:%M")
        self._data = parsed
        save_setting("weather_cache", parsed)
        self._render()

    def _locate(self):
        self._city.setText("Locating…")

        def from_ipapi(data, err):
            try:
                j = json.loads(data)
                if j.get("status") != "success":
                    raise ValueError
                self._set_loc(f"{j['city']}, {j['countryCode']}", j["lat"], j["lon"])
            except (TypeError, ValueError, KeyError):
                http_get("https://ipapi.co/json/", from_ipco)

        def from_ipco(data, err):
            try:
                j = json.loads(data)
                self._set_loc(f"{j['city']}, {j['country_code']}", j["latitude"], j["longitude"])
            except (TypeError, ValueError, KeyError):
                self._set_loc("London, GB", 51.5072, -0.1276)

        http_get("http://ip-api.com/json/?fields=status,city,countryCode,lat,lon", from_ipapi)

    def _set_loc(self, name, lat, lon):
        self.loc = {"name": name, "lat": float(lat), "lon": float(lon)}
        save_setting("weather_loc", self.loc)
        self._city.setText(name)
        self.refresh()

    def change_city(self):
        current = self.loc["name"].split(",")[0] if self.loc else ""
        text, ok = QInputDialog.getText(self, "Weather Location",
                                        "City name (leave empty to auto-detect):", text=current)
        if not ok:
            return
        text = text.strip()
        if not text:
            self.loc = None
            self._locate()
            return
        self._city.setText("Searching…")

        def done(data, err):
            try:
                res = json.loads(data)["results"][0]
                name = f"{res['name']}, {res.get('country_code', '')}".rstrip(", ")
                self._set_loc(name, res["latitude"], res["longitude"])
            except (TypeError, ValueError, KeyError, IndexError):
                self._city.setText(self.loc["name"] if self.loc else "Unknown")
                self._cond.setText(f"Couldn't find “{text}”")

        http_get("https://geocoding-api.open-meteo.com/v1/search?count=1&language=en&name="
                 + quote(text), done)

    def toggle_unit(self):
        self.unit = "F" if self.unit == "C" else "C"
        save_setting("weather_unit", self.unit)
        self.refresh()

    # ---- render ----

    def _render(self):
        d = self._data
        cur, daily = d["current"], d.get("daily", {})
        is_day = bool(cur.get("is_day", 1))
        code = int(cur.get("weather_code", 3))
        desc, icon = describe(code, is_day)
        wind_unit = "mph" if d.get("_unit") == "F" else "km/h"

        if self.loc:
            self._city.setText(self.loc["name"])
        self._temp.setText(f"{round(cur['temperature_2m'])}°")
        self._icon.setPixmap(hpix(icon, "#ffffff", 40, 1.6))
        self._cond.setText(f"{desc}  ·  Feels {round(cur['apparent_temperature'])}°")
        try:
            hi, lo = round(daily["temperature_2m_max"][0]), round(daily["temperature_2m_min"][0])
            uv = daily.get("uv_index_max", [None])[0]
            self._hilo.setText(f"H {hi}°   L {lo}°" + (f"   UV {uv:.0f}" if uv is not None else ""))
        except (KeyError, IndexError, TypeError):
            self._hilo.setText("")
        self._metrics["wind"].setText(f"{round(cur['wind_speed_10m'])}{wind_unit}")
        self._metrics["hum"].setText(f"{cur['relative_humidity_2m']}%")
        try:
            self._metrics["rise"].setText(daily["sunrise"][0][-5:])
            self._metrics["set"].setText(daily["sunset"][0][-5:])
        except (KeyError, IndexError):
            pass
        self.setToolTip(f"Open-Meteo · updated {d.get('_at', '')}")

        for i, (dl, il, tl) in enumerate(self._days, start=1):
            try:
                day = datetime.strptime(daily["time"][i], "%Y-%m-%d")
                _, dicon = describe(int(daily["weather_code"][i]), True)
                dl.setText(day.strftime("%a").upper())
                il.setPixmap(hpix(dicon, TEXT_SOFT, 16))
                tl.setText(f"{round(daily['temperature_2m_max'][i])}° {round(daily['temperature_2m_min'][i])}°")
            except (KeyError, IndexError, ValueError):
                dl.setText("")

        day_tint, night_tint = TINTS[tint_key(code)]
        self.set_background(f"""qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 {day_tint if is_day else night_tint}, stop:1 rgba(14,20,28,0.62))""")
        self.data_changed.emit(d)
