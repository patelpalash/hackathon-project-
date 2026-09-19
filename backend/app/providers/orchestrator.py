"""Provider orchestration coordinator managing polling budgets and persistence."""
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from ..contracts.provider_protocol import PollRequest, ProviderBatch, ProviderAdapter
from ..domain.models import Observation, LaneGeometry, EventInput, ProviderStatus
from ..storage.repository import Repository, ConcurrencyError
from ..engine.time_utils import expand_departure, parse_iso_dt, to_iso_utc
from .open_meteo import OpenMeteoAdapter
from .tomtom import TomTomAdapter
from .operator_bulletins import OperatorBulletinAdapter

class ProviderOrchestrator:
    def __init__(
        self,
        repo: Repository,
        open_meteo: Optional[ProviderAdapter] = None,
        tomtom: Optional[ProviderAdapter] = None,
        bulletins: Optional[ProviderAdapter] = None,
    ):
        self.repo = repo
        self.open_meteo = open_meteo or OpenMeteoAdapter()
        self.tomtom = tomtom or TomTomAdapter()
        self.bulletins = bulletins or OperatorBulletinAdapter()

    def build_poll_request(self, provider_name: str, weather_policy: str = "advisory_only") -> PollRequest:
        state = self.repo.get_state()
        network = self.repo.get_network()

        evaluation_at = parse_iso_dt(state.simulation_clock)
        horizon = evaluation_at + timedelta(hours=24)
        nodes = {node.id: node for node in network.nodes}
        target_departures: dict[str, set[str]] = {}
        plans = self.repo.get_plans()
        for p in plans:
            if p.status != "outside_demo_scope":
                for lane_id, dep_time in zip(p.selected_itinerary.lane_ids, p.selected_itinerary.departure_times):
                    dep = parse_iso_dt(dep_time)
                    if evaluation_at <= dep <= horizon:
                        target_departures.setdefault(lane_id, set()).add(to_iso_utc(dep))

        for lane in network.lanes:
            if not lane.active or lane.mode != "road":
                continue
            from_node = nodes.get(lane.from_node_id)
            if not from_node or not from_node.active:
                continue
            start_date = evaluation_at.astimezone(ZoneInfo(from_node.timezone)).date()
            departures = target_departures.setdefault(lane.id, set())
            for day_offset in range(3):
                local_date = start_date + timedelta(days=day_offset)
                if not (lane.valid_from <= local_date.isoformat() <= lane.valid_to):
                    continue
                for rule in lane.departures:
                    if local_date.isoweekday() not in rule.weekdays:
                        continue
                    departure = expand_departure(local_date, rule.local_time, from_node.timezone)
                    if departure is not None and evaluation_at <= departure <= horizon:
                        departures.add(to_iso_utc(departure))

        formatted_targets = {k: tuple(sorted(v)[:2]) for k, v in target_departures.items() if v}

        return PollRequest(
            provider=provider_name,
            dataset_id=state.snapshot.dataset_id,
            schedule_revision=state.snapshot.schedule_revision,
            evaluation_at=state.simulation_clock,
            network=network.model_dump(),
            target_departures=formatted_targets,
            weather_delay_policy="demo_thresholds" if weather_policy == "demo_thresholds" else "advisory_only",
        )

    async def poll_all(self, weather_policy: str = "advisory_only") -> list[ProviderBatch]:
        """Poll providers concurrently outside DB transactions."""
        batches: list[ProviderBatch] = []

        req_meteo = self.build_poll_request("open_meteo", weather_policy)
        req_tomtom = self.build_poll_request("tomtom", weather_policy)
        req_bulletins = self.build_poll_request("operator_bulletins", weather_policy)

        res = await asyncio.gather(
            self.open_meteo.poll(req_meteo),
            self.tomtom.poll(req_tomtom),
            self.bulletins.poll(req_bulletins),
            return_exceptions=True,
        )

        for b in res:
            if isinstance(b, ProviderBatch):
                batches.append(b)
            else:
                index = len(batches)
                # A crashed adapter must remain visible to the UI.
                provider = ("open_meteo", "tomtom", "operator_bulletins")[index]
                request = (req_meteo, req_tomtom, req_bulletins)[index]
                batches.append(ProviderBatch(
                    provider=provider, dataset_id=request.dataset_id,
                    schedule_revision=request.schedule_revision,
                    observations=(), proposed_events=(), geometries=(),
                    status={"name": provider, "status": "error", "last_poll_at": to_iso_utc(datetime.now(timezone.utc)),
                            "last_successful_poll_at": None, "consecutive_errors": 1,
                            "error_message": f"Adapter failed: {type(b).__name__}",
                            "mode": self.repo.get_state().mode},
                    warnings=(f"{provider} adapter failed",),
                ))

        return batches

    def ingest_batches(self, batches: list[ProviderBatch]) -> tuple[int, int]:
        """
        Ingest observations, geometries, and accepted events inside a DB transaction.
        Returns (observations_created, events_proposed).
        """
        state = self.repo.get_state()
        if state.mode != "live":
            raise ConcurrencyError("MODE_MISMATCH", "Provider batches cannot be ingested in demo mode")
        for batch in batches:
            if (batch.dataset_id != state.snapshot.dataset_id or
                    batch.schedule_revision != state.snapshot.schedule_revision):
                raise ConcurrencyError("STALE_SNAPSHOT", "Provider data was fetched for an old network", state.snapshot)

        obs_count = 0
        ev_count = 0
        existing_events = {event.id: event for event in self.repo.get_events()}
        with self.repo.conn:
            for batch in batches:
                provider_status = ProviderStatus.model_validate(batch.status)
                if provider_status.name != batch.provider or provider_status.mode != state.mode:
                    raise ValueError("Provider batch status does not match its source and mode")
                self.repo.store_provider_status(provider_status)

                for obs_dict in batch.observations:
                    obs = Observation.model_validate(obs_dict)
                    if obs.provider != batch.provider:
                        raise ValueError("Observation provider does not match batch source")
                    obs_count += int(self.repo.store_observation(obs))

                for geom_dict in batch.geometries:
                    lg = LaneGeometry.model_validate(geom_dict)
                    self.repo.upsert_lane_geometry(lg)

                for ev_dict in batch.proposed_events:
                    ev_inp = EventInput.model_validate(ev_dict)
                    if ev_inp.source_kind != "provider":
                        raise ValueError("Provider batch contains a non-provider event")
                    if ev_inp.valid_until and parse_iso_dt(ev_inp.valid_until) <= parse_iso_dt(ev_inp.valid_from):
                        raise ValueError("Provider event validity must have positive duration")
                    if not ev_inp.valid_until and not ev_inp.review_due_at:
                        raise ValueError("Open-ended provider event requires a review deadline")
                    if ev_inp.review_due_at and parse_iso_dt(ev_inp.review_due_at) <= parse_iso_dt(ev_inp.observed_at):
                        raise ValueError("Provider review deadline must follow observation")
                    event_id = f"provider:{batch.provider}:{ev_inp.external_id}"
                    existing = existing_events.get(event_id)
                    if existing is None and ev_inp.lifecycle_status == "withdrawn":
                        continue
                    effect_fields = (
                        "target_kind", "target_id", "mode", "effect_type", "effect_minutes",
                        "verification_status", "lifecycle_status", "correlation_key",
                        "valid_from", "valid_until", "applies_to_departure_at",
                    )
                    if existing and all(getattr(existing, field) == getattr(ev_inp, field) for field in effect_fields):
                        continue
                    event = self.repo.insert_event_version(
                        event_id=event_id,
                        version=existing.version + 1 if existing else 1,
                        inp=ev_inp,
                        reported_by=f"provider:{batch.provider}",
                    )
                    existing_events[event_id] = event
                    ev_count += 1

            if batches:
                self.repo.conn.execute("UPDATE app_state SET integrations_revision = integrations_revision + 1 WHERE id = 1;")
        return obs_count, ev_count
