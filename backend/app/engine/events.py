"""Event matching, group-max composition, and fixed-point delay iteration adhering to docs/ROUTING_RULES.md."""
from datetime import datetime, timedelta, timezone
from typing import NamedTuple, Optional
from ..domain.models import Event, Lane, Node, CalendarRule
from .time_utils import parse_iso_dt, to_iso_utc
from .calendar import simulate_pause_aware_travel, TravelChunk

class DelayGroupResult(NamedTuple):
    total_extra_minutes: int
    group_maxima: dict[str, int]  # correlation_key -> max minutes
    selected_event_ids: list[str]
    suppressed_event_ids: list[str]

def is_event_applicable(
    event: Event,
    evaluation_clock_utc: datetime,
) -> bool:
    """
    Check if event is active and known at evaluation clock:
    verification accepted, lifecycle active, observed_at <= evaluation clock.
    """
    if event.verification_status != "accepted":
        return False
    if event.lifecycle_status != "active":
        return False
    obs_dt = parse_iso_dt(event.observed_at)
    if obs_dt > evaluation_clock_utc:
        return False
    return True

def interval_overlaps(
    start_utc: datetime,
    end_utc: datetime,
    event_valid_from_utc: datetime,
    event_valid_until_utc: Optional[datetime],
) -> bool:
    """
    Intervals are half-open [valid_from, valid_until).
    start_utc < valid_until (if present) and valid_from < end_utc.
    For zero-duration point (start_utc == end_utc):
    valid_from <= start_utc < valid_until.
    """
    if start_utc == end_utc:
        if event_valid_until_utc is not None:
            return event_valid_from_utc <= start_utc < event_valid_until_utc
        return event_valid_from_utc <= start_utc

    if event_valid_until_utc is not None and start_utc >= event_valid_until_utc:
        return False
    if event_valid_from_utc >= end_utc:
        return False
    return True

def compute_node_handling_delay(
    node: Node,
    outgoing_mode: str,
    arrival_utc: datetime,
    events: list[Event],
    evaluation_clock_utc: datetime,
) -> tuple[int, datetime, DelayGroupResult]:
    """
    Fixed-point iteration for node handling delay (Section 3 of ROUTING_RULES.md).
    Returns (total_handling_minutes, end_utc, delay_group_result).
    """
    base_handling = node.processing_minutes
    active_events = [e for e in events if is_event_applicable(e, evaluation_clock_utc)]
    
    # Filter candidates scoped to this node and mode
    candidates: list[Event] = []
    for e in active_events:
        if e.target_kind == "node" and e.target_id == node.id and e.effect_type == "additional_handling_minutes":
            if e.mode == outgoing_mode:
                candidates.append(e)

    current_group_maxima: dict[str, int] = {}
    current_end = arrival_utc + timedelta(minutes=base_handling)
    
    max_passes = len(candidates) + 5
    for _ in range(max_passes):
        # Find events overlapping [arrival_utc, current_end)
        matched_events: list[Event] = []
        for e in candidates:
            vf = parse_iso_dt(e.valid_from)
            vu = parse_iso_dt(e.valid_until) if e.valid_until else None
            if interval_overlaps(arrival_utc, current_end, vf, vu):
                matched_events.append(e)

        # Compute correlation_key -> max(effect_minutes)
        new_group_maxima: dict[str, int] = {}
        for e in matched_events:
            eff = e.effect_minutes or 0
            new_group_maxima[e.correlation_key] = max(new_group_maxima.get(e.correlation_key, 0), eff)

        new_total_extra = sum(new_group_maxima.values())
        new_end = arrival_utc + timedelta(minutes=base_handling + new_total_extra)

        if new_group_maxima == current_group_maxima and new_end == current_end:
            # Converged!
            break
        current_group_maxima = new_group_maxima
        current_end = new_end

    # Determine selected and suppressed events
    selected_event_ids: list[str] = []
    suppressed_event_ids: list[str] = []
    
    # Group matched events by correlation key
    events_by_key: dict[str, list[Event]] = {}
    for e in candidates:
        vf = parse_iso_dt(e.valid_from)
        vu = parse_iso_dt(e.valid_until) if e.valid_until else None
        if interval_overlaps(arrival_utc, current_end, vf, vu):
            events_by_key.setdefault(e.correlation_key, []).append(e)

    for key, evs in sorted(events_by_key.items()):
        max_val = current_group_maxima.get(key, 0)
        # Select first event that achieved max_val, suppress others
        chosen = False
        for e in sorted(evs, key=lambda x: (-(x.effect_minutes or 0), x.id)):
            if not chosen and (e.effect_minutes or 0) == max_val:
                selected_event_ids.append(e.id)
                chosen = True
            else:
                suppressed_event_ids.append(e.id)

    res = DelayGroupResult(
        total_extra_minutes=sum(current_group_maxima.values()),
        group_maxima=current_group_maxima,
        selected_event_ids=selected_event_ids,
        suppressed_event_ids=suppressed_event_ids,
    )
    total_minutes = base_handling + res.total_extra_minutes
    return total_minutes, current_end, res

def compute_lane_travel_delay_and_chunks(
    lane: Lane,
    departure_utc: datetime,
    events: list[Event],
    calendar_rules: list[CalendarRule],
    evaluation_clock_utc: datetime,
    max_horizon_utc: datetime,
) -> tuple[int, datetime, list[TravelChunk], DelayGroupResult]:
    """
    Fixed-point iteration for lane travel delay and calendar pause simulation (Sections 3, 4, 5 of ROUTING_RULES.md).
    Returns (total_work_minutes, final_arrival_utc, travel_chunks, delay_group_result).
    """
    base_work = lane.duration_minutes
    active_events = [e for e in events if is_event_applicable(e, evaluation_clock_utc)]
    dep_iso = to_iso_utc(departure_utc)

    candidates: list[Event] = []
    for e in active_events:
        if e.target_kind == "lane" and e.target_id == lane.id and e.effect_type == "additional_travel_minutes":
            if e.mode == lane.mode:
                if e.applies_to_departure_at is not None:
                    if e.applies_to_departure_at == dep_iso:
                        candidates.append(e)
                else:
                    candidates.append(e)

    current_group_maxima: dict[str, int] = {}
    current_work = base_work
    current_chunks = simulate_pause_aware_travel(lane, departure_utc, current_work, calendar_rules, max_horizon_utc)
    current_end = current_chunks[-1].end_at if current_chunks else departure_utc

    max_passes = len(candidates) + 5
    for _ in range(max_passes):
        matched_events: list[Event] = []
        for e in candidates:
            if e.applies_to_departure_at is not None:
                if e.applies_to_departure_at == dep_iso:
                    matched_events.append(e)
            else:
                vf = parse_iso_dt(e.valid_from)
                vu = parse_iso_dt(e.valid_until) if e.valid_until else None
                if interval_overlaps(departure_utc, current_end, vf, vu):
                    matched_events.append(e)

        new_group_maxima: dict[str, int] = {}
        for e in matched_events:
            eff = e.effect_minutes or 0
            new_group_maxima[e.correlation_key] = max(new_group_maxima.get(e.correlation_key, 0), eff)

        new_total_extra = sum(new_group_maxima.values())
        new_work = base_work + new_total_extra
        new_chunks = simulate_pause_aware_travel(lane, departure_utc, new_work, calendar_rules, max_horizon_utc)
        new_end = new_chunks[-1].end_at if new_chunks else departure_utc

        if new_group_maxima == current_group_maxima and new_end == current_end:
            current_chunks = new_chunks
            break
        current_group_maxima = new_group_maxima
        current_work = new_work
        current_chunks = new_chunks
        current_end = new_end

    # Selected & suppressed events
    selected_event_ids: list[str] = []
    suppressed_event_ids: list[str] = []
    events_by_key: dict[str, list[Event]] = {}
    for e in candidates:
        if e.applies_to_departure_at is not None:
            if e.applies_to_departure_at == dep_iso:
                events_by_key.setdefault(e.correlation_key, []).append(e)
        else:
            vf = parse_iso_dt(e.valid_from)
            vu = parse_iso_dt(e.valid_until) if e.valid_until else None
            if interval_overlaps(departure_utc, current_end, vf, vu):
                events_by_key.setdefault(e.correlation_key, []).append(e)

    for key, evs in sorted(events_by_key.items()):
        max_val = current_group_maxima.get(key, 0)
        chosen = False
        for e in sorted(evs, key=lambda x: (-(x.effect_minutes or 0), x.id)):
            if not chosen and (e.effect_minutes or 0) == max_val:
                selected_event_ids.append(e.id)
                chosen = True
            else:
                suppressed_event_ids.append(e.id)

    res = DelayGroupResult(
        total_extra_minutes=sum(current_group_maxima.values()),
        group_maxima=current_group_maxima,
        selected_event_ids=selected_event_ids,
        suppressed_event_ids=suppressed_event_ids,
    )
    total_work = base_work + res.total_extra_minutes
    return total_work, current_end, current_chunks, res

def is_lane_blocked_by_closure(
    lane: Lane,
    departure_utc: datetime,
    arrival_utc: datetime,
    events: list[Event],
    evaluation_clock_utc: datetime,
) -> bool:
    """
    Check if occurrence traversal is invalidated by a closure or departure_cancellation:
    - departure_cancellation: departure instant lies in event window [valid_from, valid_until)
    - closure: full projected traversal interval [departure, arrival) overlaps event window
    """
    active_events = [e for e in events if is_event_applicable(e, evaluation_clock_utc)]
    dep_iso = to_iso_utc(departure_utc)

    for e in active_events:
        if e.target_kind != "lane" or e.target_id != lane.id:
            continue
        vf = parse_iso_dt(e.valid_from)
        vu = parse_iso_dt(e.valid_until) if e.valid_until else None

        if e.effect_type == "departure_cancellation":
            if e.applies_to_departure_at is not None:
                if e.applies_to_departure_at == dep_iso:
                    return True
            elif interval_overlaps(departure_utc, departure_utc, vf, vu):
                return True

        elif e.effect_type == "closure":
            if e.applies_to_departure_at is not None:
                if e.applies_to_departure_at == dep_iso:
                    return True
            elif interval_overlaps(departure_utc, arrival_utc, vf, vu):
                return True

    return False
