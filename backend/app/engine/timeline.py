"""Timeline segment building and reason attribution adhering to docs/ROUTING_RULES.md."""
from datetime import datetime, timezone
from typing import Optional
from ..domain.models import Segment, Reason
from .time_utils import to_iso_utc, minutes_between
from .calendar import TravelChunk
from .events import DelayGroupResult

def build_handling_segment(
    segment_index: int,
    node_id: str,
    node_name: str,
    start_utc: datetime,
    end_utc: datetime,
    base_handling_minutes: int,
    delay_res: DelayGroupResult,
) -> Optional[Segment]:
    """Build a contiguous node handling segment with apportioned reasons."""
    duration = minutes_between(start_utc, end_utc)
    if duration <= 0:
        return None

    reasons: list[Reason] = []
    if base_handling_minutes > 0:
        reasons.append(
            Reason(
                code="NODE_HANDLING",
                minutes=base_handling_minutes,
                description=f"Standard handling at {node_name} ({node_id})",
                event_ids=[],
            )
        )

    for key, extra_mins in sorted(delay_res.group_maxima.items()):
        if extra_mins > 0:
            reasons.append(
                Reason(
                    code="EVENT_HANDLING_DELAY",
                    minutes=extra_mins,
                    description=f"Operational handling delay at {node_name}; event group {key}",
                    event_ids=[eid for eid in delay_res.selected_event_ids],
                )
            )

    # Sanity check: sum of reasons must equal duration
    reason_sum = sum(r.minutes for r in reasons)
    if reason_sum != duration:
        # If there's an adjustment, align to duration
        diff = duration - reason_sum
        if reasons:
            reasons[0].minutes += diff
        else:
            reasons.append(
                Reason(
                    code="NODE_HANDLING",
                    minutes=duration,
                    description=f"Handling at {node_name}",
                    event_ids=[],
                )
            )

    return Segment(
        segment_index=segment_index,
        type="handle",
        node_id=node_id,
        lane_id=None,
        start_at=to_iso_utc(start_utc),
        end_at=to_iso_utc(end_utc),
        duration_minutes=duration,
        reasons=reasons,
    )

def build_wait_segment(
    segment_index: int,
    node_id: str,
    node_name: str,
    start_utc: datetime,
    end_utc: datetime,
    missed_earlier_cutoff: bool,
) -> Optional[Segment]:
    """Build a departure waiting segment at a node."""
    duration = minutes_between(start_utc, end_utc)
    if duration <= 0:
        return None

    reason_code = "MISSED_CUTOFF" if missed_earlier_cutoff else "WAIT_DEPARTURE"
    desc = (
        f"Missed earlier cutoff; waiting for next departure at {node_name}"
        if missed_earlier_cutoff
        else f"Waiting for scheduled departure at {node_name}"
    )

    return Segment(
        segment_index=segment_index,
        type="wait",
        node_id=node_id,
        lane_id=None,
        start_at=to_iso_utc(start_utc),
        end_at=to_iso_utc(end_utc),
        duration_minutes=duration,
        reasons=[
            Reason(
                code=reason_code,
                minutes=duration,
                description=desc,
                event_ids=[],
            )
        ],
    )

def build_travel_segments(
    start_segment_index: int,
    lane_id: str,
    chunks: list[TravelChunk],
    base_duration_minutes: int,
    delay_res: DelayGroupResult,
) -> list[Segment]:
    """
    Build travel segments from TravelChunks.
    For split travel chunks, attributes base work first, then additive event work
    ordered by correlation key; calendar pause minutes have their own wait reason.
    """
    segments: list[Segment] = []
    curr_idx = start_segment_index

    # Track remaining work pools to allocate across travel chunks
    rem_base = base_duration_minutes
    # list of (correlation_key, minutes, selected_event_ids)
    rem_events = [
        (k, mins, delay_res.selected_event_ids)
        for k, mins in sorted(delay_res.group_maxima.items())
        if mins > 0
    ]

    for chunk in chunks:
        if chunk.duration_minutes <= 0:
            continue

        if chunk.is_calendar_pause:
            # Calendar pause wait segment
            seg = Segment(
                segment_index=curr_idx,
                type="wait",
                node_id=None,
                lane_id=lane_id,
                start_at=to_iso_utc(chunk.start_at),
                end_at=to_iso_utc(chunk.end_at),
                duration_minutes=chunk.duration_minutes,
                reasons=[
                    Reason(
                        code="CALENDAR_PAUSE",
                        minutes=chunk.duration_minutes,
                        description=f"Calendar travel pause on lane {lane_id}",
                        event_ids=[],
                    )
                ],
            )
            segments.append(seg)
            curr_idx += 1
            continue

        # Active travel chunk: allocate rem_base then rem_events
        chunk_rem = chunk.duration_minutes
        chunk_reasons: list[Reason] = []

        if rem_base > 0:
            take_base = min(rem_base, chunk_rem)
            chunk_reasons.append(
                Reason(
                    code="LANE_TRAVEL",
                    minutes=take_base,
                    description=f"Scheduled transit on lane {lane_id}",
                    event_ids=[],
                )
            )
            rem_base -= take_base
            chunk_rem -= take_base

        if chunk_rem > 0:
            for i in range(len(rem_events)):
                if chunk_rem <= 0:
                    break
                key, extra_mins, ev_ids = rem_events[i]
                if extra_mins > 0:
                    take_ev = min(extra_mins, chunk_rem)
                    chunk_reasons.append(
                        Reason(
                            code="EVENT_TRAVEL_DELAY",
                            minutes=take_ev,
                            description=f"Travel delay on lane {lane_id}; event group {key}",
                            event_ids=ev_ids,
                        )
                    )
                    rem_events[i] = (key, extra_mins - take_ev, ev_ids)
                    chunk_rem -= take_ev

        # Fallback if any unallocated
        if chunk_rem > 0:
            if chunk_reasons:
                chunk_reasons[0].minutes += chunk_rem
            else:
                chunk_reasons.append(
                    Reason(
                        code="LANE_TRAVEL",
                        minutes=chunk_rem,
                        description=f"Transit on lane {lane_id}",
                        event_ids=[],
                    )
                )

        seg = Segment(
            segment_index=curr_idx,
            type="travel",
            node_id=None,
            lane_id=lane_id,
            start_at=to_iso_utc(chunk.start_at),
            end_at=to_iso_utc(chunk.end_at),
            duration_minutes=chunk.duration_minutes,
            reasons=chunk_reasons,
        )
        segments.append(seg)
        curr_idx += 1

    return segments
