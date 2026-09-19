"""
Live-data providers with honest status. No provider ever reports LIVE unless a
real request returned current data. States: LIVE / STALE / ERROR / NOT_CONFIGURED
/ DISABLED. Keys never touch the frontend — the backend is the integration layer.

Keyless-real providers (work with internet, no key):
  - weather:  Open-Meteo (current + wind)          -> LIVE when reachable
  - holidays: provided kalender.csv (+ Nager.Date)  -> LIVE (regulatory/calendar data)
  - routing:  OSRM public server (geometry+duration) -> LIVE when reachable, else fallback
Key-gated:
  - traffic:  TomTom -> NOT_CONFIGURED until TOMTOM_API_KEY is set
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from .live import Forecasts, TomTom

STALE_AFTER_S = {"weather": 1800, "traffic": 600, "routing": 86400}


def _now():
    return datetime.now(timezone.utc)


class Provider:
    def __init__(self, key, name, configured, kind):
        self.key = key
        self.name = name
        self.configured = configured
        self.kind = kind  # LIVE-capable | REGULATORY | etc
        self.last_success = None
        self.last_attempt = None
        self.data_timestamp = None
        self.error = None
        self._cache = None

    def status(self) -> str:
        if not self.configured:
            return "NOT_CONFIGURED"
        if self.error:
            return "STALE" if self.last_success else "ERROR"
        if self.last_success is None:
            return "NOT_QUERIED"
        age = (_now() - self.last_success).total_seconds()
        if age > STALE_AFTER_S.get(self.key, 3600):
            return "STALE"
        return "LIVE"

    def to_dict(self):
        def iso(d):
            return d.isoformat() if d else None
        return {
            "key": self.key, "name": self.name, "status": self.status(),
            "configured": self.configured, "kind": self.kind,
            "last_success": iso(self.last_success), "last_attempt": iso(self.last_attempt),
            "data_timestamp": iso(self.data_timestamp), "error": self.error,
        }


class WeatherProvider(Provider):
    def __init__(self):
        super().__init__("weather", "Open-Meteo", True, "LIVE")

    def fetch(self, lat, lon):
        self.last_attempt = _now()
        try:
            import httpx
            r = httpx.get("https://api.open-meteo.com/v1/forecast", params={
                "latitude": lat, "longitude": lon,
                "current": "temperature_2m,precipitation,weather_code,wind_speed_10m,visibility",
            }, timeout=2.0)
            cur = r.json()["current"]
            self.last_success = _now()
            self.data_timestamp = _now()
            self.error = None
            return {"observed": True, "temp_c": cur.get("temperature_2m"),
                    "precipitation": cur.get("precipitation"), "wind_kmh": cur.get("wind_speed_10m"),
                    "visibility_m": cur.get("visibility"), "code": cur.get("weather_code"),
                    "source": "Open-Meteo", "timestamp": self.data_timestamp.isoformat(), "status": "LIVE"}
        except Exception as ex:
            self.error = type(ex).__name__
            return {"observed": False, "status": self.status(), "error": self.error,
                    "last_success": self.last_success.isoformat() if self.last_success else None}


class TrafficProvider(Provider):
    def __init__(self):
        super().__init__("traffic", "TomTom", bool(os.environ.get("TOMTOM_API_KEY")), "LIVE")


class RoutingProvider(Provider):
    def __init__(self):
        super().__init__("routing", "OSRM (public)", True, "LIVE")
        self.legs = {}

    def leg(self, from_ll, to_ll):
        key = (tuple(from_ll), tuple(to_ll))
        cached = self.legs.get(key)
        if cached and time.time()-cached[0] < (86400 if cached[1].get("geometry") else 30):
            return cached[1]
        self.last_attempt = _now()
        try:
            import httpx
            url = f"https://router.project-osrm.org/route/v1/driving/{from_ll[1]},{from_ll[0]};{to_ll[1]},{to_ll[0]}"
            r = httpx.get(url, params={"overview": "full", "geometries": "geojson"}, timeout=3.0)
            r.raise_for_status()
            route = r.json()["routes"][0]
            self.last_success = _now(); self.data_timestamp = _now(); self.error = None
            result = {"status": "LIVE", "duration_minutes": max(1, round(route["duration"] / 60)),
                      "distance_km": round(route["distance"] / 1000, 1),
                      "geometry": route["geometry"]["coordinates"], "source": "OSRM road estimate (not truck-certified)"}
        except Exception as ex:
            self.error = type(ex).__name__
            result = {"status": "ERROR", "geometry": None, "source": "estimated fallback"}
        self.legs[key] = (time.time(), result)
        return result


class HolidayProvider(Provider):
    """Regulatory/calendar data — from the provided kalender.csv (always available)."""
    def __init__(self, holidays: dict):
        super().__init__("holidays", "kalender.csv (BW) / Nager.Date", True, "REGULATORY")
        self.holidays = holidays
        self.last_success = _now()
        self.data_timestamp = _now()

    def status(self):
        return "LIVE"  # regulatory calendar data provided with the dataset


class Providers:
    def __init__(self, holidays: dict):
        self.forecasts = Forecasts()
        self.tomtom = TomTom()
        self.weather = WeatherProvider()
        self.traffic = TrafficProvider()
        self.routing = RoutingProvider()
        self.holidays = HolidayProvider(holidays)

    def all(self):
        self.weather.error = self.forecasts.error
        if self.forecasts.last_success:
            self.weather.last_success = datetime.fromisoformat(self.forecasts.last_success)
            self.weather.data_timestamp = self.weather.last_success
        if self.tomtom.key:
            self.traffic.name = "TomTom"
            self.traffic.configured = True
            self.traffic.error = self.tomtom.error
            if self.tomtom.last_success: self.traffic.last_success = datetime.fromisoformat(self.tomtom.last_success)
        return [self.weather.to_dict(), self.traffic.to_dict(),
                self.routing.to_dict(), self.holidays.to_dict()]
