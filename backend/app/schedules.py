"""Optional user-entered service timetables; no inferred carrier availability."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from .restrictions import restriction_at
from .operations import parse


def next_departure(ready, origin, destination, schedules, holidays, events=()):
    matching=[s for s in schedules if s["origin"]==origin and s["destination"]==destination]
    if not matching: return ready, None
    candidates=[]
    for service in matching:
        tz=ZoneInfo(service["timezone"])
        first=ready.astimezone(tz).date()
        hour,minute=map(int,service["departure_time"].split(":"))
        for offset in range(60):
            day=first+timedelta(days=offset)
            if day.weekday() not in service["weekdays"]: continue
            local=datetime(day.year,day.month,day.day,hour,minute,tzinfo=tz)
            departure=local.astimezone(timezone.utc)
            # Skip nonexistent DST wall times; repeated times use the first occurrence.
            if departure.astimezone(tz).replace(tzinfo=None)!=local.replace(tzinfo=None): continue
            if departure-timedelta(minutes=service["cutoff_minutes"])<ready: continue
            if restriction_at(departure,holidays)[0]: continue
            if any(e["kind"]=="closure" and e.get("node")==origin and parse(e["start"])<=departure<parse(e["end"]) for e in events): continue
            candidates.append((departure,service)); break
    if not candidates: raise ValueError("No eligible service departure within 60 days; change the schedule or readiness time")
    return min(candidates,key=lambda item:item[0])
