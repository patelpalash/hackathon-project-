"""Provider-neutral weather thresholds. Delays are explicit prototype assumptions."""
from datetime import timedelta

THRESHOLDS = {"high_wind_kmh": 60, "low_visibility_m": 1000, "heavy_precipitation_mm": 5, "high_delay_minutes": 120, "medium_delay_minutes": 45}

def evaluate(record):
    high = record["severity"] == "HIGH" or record["wind_kmh"] >= THRESHOLDS["high_wind_kmh"] or record["visibility_m"] < THRESHOLDS["low_visibility_m"] or "heavy snow" in record["condition"].lower()
    medium = record["severity"] == "MEDIUM" or record["rain_mm"] >= THRESHOLDS["heavy_precipitation_mm"] or record["snow_cm"] > 0 or record["wind_kmh"] >= 35
    level = "HIGH" if high else "MEDIUM" if medium else "LOW"
    return {**record, "alert": level != "LOW", "level": level, "delay_minutes": 120 if high else 45 if medium else 0,
            "message": f"{record['condition']} · visibility {record['visibility_m']} m · wind {record['wind_kmh']} km/h",
            "action": "Review route / consider rerouting" if level != "LOW" else "No action required", "source": "MANUAL SAMPLE"}

def at_hub(operations, node, start, end=None):
    end = end or start + timedelta(minutes=1)
    return [evaluate(r) for r in operations.data["weather"] if r["node"] == node and operations.overlaps(r, start, end)]
