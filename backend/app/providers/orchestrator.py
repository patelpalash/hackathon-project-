"""Provider orchestration coordinator managing polling budgets and persistence."""
import asyncio
from datetime import datetime, timezone
from typing import Optional

from ..contracts.provider_protocol import PollRequest, ProviderBatch, ProviderAdapter
from ..domain.models import Snapshot, Observation, LaneGeometry, Geometry, EventInput, RefreshResult
from ..storage.repository import Repository, ConcurrencyError
from ..engine.time_utils import to_iso_utc
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

        # Find next scheduled road departures across active plans or network lanes
        target_departures: dict[str, tuple[str, ...]] = {}
        plans = self.repo.get_plans()
        for p in plans:
            if p.status != "outside_demo_scope":
                for lane_id, dep_time in zip(p.selected_itinerary.lane_ids, p.selected_itinerary.departure_times):
                    target_departures.setdefault(lane_id, set()).add(dep_time)

        # Fallback to network lane departures if no saved plan targets
        if not target_departures:
            for lane in network.lanes:
                if lane.mode == "road":
                    # add first departure as target
                    if lane.departures:
                        target_departures[lane.id] = (f"{lane.valid_from}T{lane.departures[0].local_time}:00Z",)

        formatted_targets = {k: tuple(sorted(list(v))) for k, v in target_departures.items()}

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

        return batches

    def ingest_batches(self, batches: list[ProviderBatch]) -> tuple[int, int]:
        """
        Ingest observations, geometries, and accepted events inside a DB transaction.
        Returns (observations_created, events_proposed).
        """
        obs_count = 0
        ev_count = 0

        for b in batches:
            for obs_dict in b.observations:
                obs = Observation.model_validate(obs_dict)
                self.repo.store_observation(obs)
                obs_count += 1

            for geom_dict in b.geometries:
                lg = LaneGeometry.model_validate(geom_dict)
                self.repo.upsert_lane_geometry(lg)

            for ev_dict in b.proposed_events:
                ev_inp = EventInput.model_validate(ev_dict)
                ev_count += 1
                if ev_inp.verification_status == "accepted":
                    self.repo.insert_event_version(
                        event_id=ev_inp.external_id,
                        version=1,
                        inp=ev_inp,
                        reported_by=f"provider:{b.provider}",
                    )

        # Update integrations revision
        self.repo.conn.execute("UPDATE app_state SET integrations_revision = integrations_revision + 1 WHERE id = 1;")
        self.repo.conn.commit()
        return obs_count, ev_count
