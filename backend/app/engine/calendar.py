"""Calendar rules and pause-aware travel execution adhering to docs/ROUTING_RULES.md."""
from datetime import datetime, date, time, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import NamedTuple, Optional
from ..domain.models import CalendarRule, Lane

class TravelChunk(NamedTuple):
    kind: str  # 'travel' or 'wait'
    start_at: datetime
    end_at: datetime
    duration_minutes: int
    is_calendar_pause: bool

def is_departure_during_calendar_pause(
    departure_utc: datetime,
    lane: Lane,
    rules: list[CalendarRule],
) -> bool:
    """Check if departure falls during a recurring calendar pause for this lane."""
    if lane.mode != "road":
        return False

    for rule in rules:
        if rule.lane_id != lane.id or rule.action != "pause_travel":
            continue
        zone = ZoneInfo(rule.timezone)
        local_dt = departure_utc.astimezone(zone)
        # Check weekday (1=Mon ... 7=Sun)
        if local_dt.isoweekday() == rule.weekday:
            start_h, start_m = map(int, rule.start_local_time.split(":"))
            end_h, end_m = map(int, rule.end_next_day_local_time.split(":"))
            # If start_local_time is 00:00 and end_next_day_local_time is 00:00,
            # then the entire day (from 00:00 Sunday to 00:00 Monday) is blocked.
            return True
    return False

def get_blocked_intervals_for_range(
    lane_id: str,
    lane_mode: str,
    start_utc: datetime,
    end_utc: datetime,
    rules: list[CalendarRule],
) -> list[tuple[datetime, datetime]]:
    """
    Expand recurring calendar pause intervals in UTC between start_utc and end_utc.
    Merges any overlapping intervals.
    """
    if lane_mode != "road":
        return []

    intervals: list[tuple[datetime, datetime]] = []
    applicable_rules = [r for r in rules if r.lane_id == lane_id and r.action == "pause_travel"]
    if not applicable_rules:
        return []

    # Iterate day by day in UTC range (with safety buffer)
    start_date = (start_utc - timedelta(days=2)).date()
    end_date = (end_utc + timedelta(days=2)).date()

    curr_date = start_date
    while curr_date <= end_date:
        for rule in applicable_rules:
            zone = ZoneInfo(rule.timezone)
            # Find the date corresponding to rule.weekday
            if curr_date.isoweekday() == rule.weekday:
                start_h, start_m = map(int, rule.start_local_time.split(":"))
                end_h, end_m = map(int, rule.end_next_day_local_time.split(":"))
                
                block_start_local = datetime.combine(curr_date, time(start_h, start_m, 0), tzinfo=zone)
                # Next day local time
                next_day = curr_date + timedelta(days=1)
                block_end_local = datetime.combine(next_day, time(end_h, end_m, 0), tzinfo=zone)

                block_start_utc = block_start_local.astimezone(timezone.utc)
                block_end_utc = block_end_local.astimezone(timezone.utc)

                intervals.append((block_start_utc, block_end_utc))
        curr_date += timedelta(days=1)

    # Sort and merge overlapping intervals
    intervals.sort(key=lambda x: x[0])
    merged: list[tuple[datetime, datetime]] = []
    for start, end in intervals:
        if not merged:
            merged.append((start, end))
        else:
            last_start, last_end = merged[-1]
            if start <= last_end:
                merged[-1] = (last_start, max(last_end, end))
            else:
                merged.append((start, end))
    return merged

def simulate_pause_aware_travel(
    lane: Lane,
    departure_utc: datetime,
    total_work_minutes: int,
    rules: list[CalendarRule],
    max_horizon_utc: datetime,
) -> list[TravelChunk]:
    """
    Simulate pause-aware travel according to algorithm in Section 5 of ROUTING_RULES.md:
    1. Let remaining be base travel plus matched delay work; current be departure.
    2. Expand relevant recurring blocked intervals into UTC and merge overlapping intervals.
    3. If current lies inside a blocked interval, emit a wait until its end; consume no remaining travel work.
    4. Otherwise consume min(remaining, minutes until next block), emitting a travel chunk.
    5. Continue until remaining=0, or search horizon exceeded. Arrival exactly at block start needs no wait if remaining is already zero.
    """
    remaining = total_work_minutes
    current = departure_utc
    chunks: list[TravelChunk] = []

    if remaining <= 0:
        return chunks

    # Estimate end time for expanding blocked intervals
    est_end = current + timedelta(minutes=remaining + 14 * 24 * 60)
    blocked_intervals = get_blocked_intervals_for_range(lane.id, lane.mode, current, est_end, rules)

    iteration_guard = 0
    while remaining > 0 and current <= max_horizon_utc:
        iteration_guard += 1
        if iteration_guard > 10000:
            raise RuntimeError("Exceeded iteration limit during pause-aware travel calculation")

        # Check if current is inside a blocked interval
        current_block: Optional[tuple[datetime, datetime]] = None
        for b_start, b_end in blocked_intervals:
            if b_start <= current < b_end:
                current_block = (b_start, b_end)
                break

        if current_block is not None:
            # Emit a wait until its end; consume no remaining travel work
            wait_end = current_block[1]
            duration = int((wait_end - current).total_seconds() // 60)
            if duration > 0:
                chunks.append(
                    TravelChunk(
                        kind="wait",
                        start_at=current,
                        end_at=wait_end,
                        duration_minutes=duration,
                        is_calendar_pause=True,
                    )
                )
            current = wait_end
            continue

        # Find minutes until next block
        next_block_start: Optional[datetime] = None
        for b_start, b_end in blocked_intervals:
            if b_start > current:
                next_block_start = b_start
                break

        if next_block_start is not None:
            mins_to_block = int((next_block_start - current).total_seconds() // 60)
            consume = min(remaining, mins_to_block)
        else:
            consume = remaining

        travel_end = current + timedelta(minutes=consume)
        if consume > 0:
            chunks.append(
                TravelChunk(
                    kind="travel",
                    start_at=current,
                    end_at=travel_end,
                    duration_minutes=consume,
                    is_calendar_pause=False,
                )
            )
        remaining -= consume
        current = travel_end

    return chunks
