"""Customer business policy, separate from the existing holiday calendar."""
from datetime import timedelta, timezone
from .restrictions import BERLIN

def hub_release(arrival, ready, intermediate=True):
    local = arrival.astimezone(BERLIN)
    # A Saturday arrival at an intermediate station waits through Sunday.
    if (intermediate and local.weekday() == 5) or local.weekday() == 6:
        monday = (local + timedelta(days=7-local.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        return max(ready, monday.astimezone(timezone.utc))
    return ready
