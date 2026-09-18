"""Time and timezone utilities adhering to docs/ROUTING_RULES.md."""
from datetime import datetime, date, time, timedelta, timezone
from zoneinfo import ZoneInfo
import hashlib
import json
from typing import Optional

def parse_iso_dt(dt_str: str) -> datetime:
    """Parse ISO8601/RFC3339 string into timezone-aware datetime."""
    # Handle trailing Z
    val = dt_str.replace("Z", "+00:00")
    d = datetime.fromisoformat(val)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d

def to_iso_utc(dt: datetime) -> str:
    """Format datetime as UTC ISO8601 string ending with Z and whole minutes."""
    utc_dt = dt.astimezone(timezone.utc)
    # Ensure seconds are zero or included as :00Z
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

def to_iso_date(d: date) -> str:
    """Format date as YYYY-MM-DD."""
    return d.isoformat()

def minutes_between(start: datetime, end: datetime) -> int:
    """Calculate whole minutes between two datetimes."""
    return int((end - start).total_seconds() // 60)

def validate_input_time_string(dt_str: str, node_timezone: str) -> tuple[datetime, Optional[str]]:
    """
    Validate input timestamp string:
    - Must be RFC3339 with explicit offset (Z or +HH:MM)
    - Seconds must be zero (or omitted)
    - If Z, accepted and normalized to node zone
    - If non-Z local offset, must match the node timezone's offset at that instant; else return error
    Returns (normalized_utc_dt, error_message)
    """
    try:
        dt = parse_iso_dt(dt_str)
    except Exception as e:
        return datetime.min.replace(tzinfo=timezone.utc), f"Invalid RFC3339 datetime: {e}"
    
    if dt.second != 0 or dt.microsecond != 0:
        return datetime.min.replace(tzinfo=timezone.utc), "Nonzero seconds are rejected"

    zone = ZoneInfo(node_timezone)
    # Check if dt_str used Z
    if dt_str.endswith("Z"):
        return dt.astimezone(timezone.utc), None

    # For non-Z, check offset agreement with node timezone at that instant
    dt_in_zone = dt.astimezone(zone)
    expected_offset = dt_in_zone.utcoffset()
    actual_offset = dt.utcoffset()
    if expected_offset != actual_offset:
        return datetime.min.replace(tzinfo=timezone.utc), (
            f"Offset {actual_offset} does not match {node_timezone} offset {expected_offset} at that instant (TIMEZONE_MISMATCH)"
        )

    return dt.astimezone(timezone.utc), None

def compute_route_id(lane_ids: list[str], departure_times: list[str]) -> str:
    """
    Compute route.id as first 24 lowercase hex characters of SHA-256
    of canonical JSON with fields lane_ids and departure_times (UTC Z),
    compact separators (',', ':') and sorted keys.
    """
    payload = {
        "departure_times": departure_times,
        "lane_ids": lane_ids,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]

def expand_departure(
    local_date: date,
    local_time_str: str,
    tz_name: str,
) -> Optional[datetime]:
    """
    Expand a schedule occurrence on local_date at local_time_str in tz_name.
    - Handles spring DST skip: returns None if time doesn't exist
    - Handles autumn DST fold: picks fold=0 (earlier UTC instant)
    Returns UTC datetime, or None if invalid/skipped.
    """
    zone = ZoneInfo(tz_name)
    hour, minute = map(int, local_time_str.split(":"))
    t = time(hour, minute, 0)
    naive = datetime.combine(local_date, t)
    
    # Try fold=0
    dt_fold0 = naive.replace(fold=0, tzinfo=zone)
    # Check if spring DST gap occurred
    # In python zoneinfo, if a time does not exist, astimezone / roundtrip or utcoffset shifts it
    utc_dt = dt_fold0.astimezone(timezone.utc)
    local_roundtrip = utc_dt.astimezone(zone)
    if (
        local_roundtrip.date() != local_date
        or local_roundtrip.hour != hour
        or local_roundtrip.minute != minute
    ):
        # Nonexistent local time during spring DST
        return None

    return utc_dt
