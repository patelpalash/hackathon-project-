"""Provider adapter tests verifying Open-Meteo, TomTom, and Operator Bulletins."""
import json
import pytest
import httpx

from backend.app.contracts.provider_protocol import PollRequest, ProviderBatch
from backend.app.providers.open_meteo import OpenMeteoAdapter
from backend.app.providers.tomtom import TomTomAdapter
from backend.app.providers.operator_bulletins import OperatorBulletinAdapter
from backend.app.providers.orchestrator import ProviderOrchestrator
from backend.app.storage.repository import ConcurrencyError
from backend.app.domain.models import SearchRequest
from backend.app.engine.route_search import search_routes
from backend.app.engine.time_utils import parse_iso_dt

SAMPLE_NETWORK = {
    "nodes": [
        {"id": "FRA_HUB", "name": "Frankfurt", "latitude": 50.11, "longitude": 8.68, "timezone": "Europe/Berlin"},
        {"id": "KEM_BRANCH", "name": "Kempten", "latitude": 47.73, "longitude": 10.31, "timezone": "Europe/Berlin"},
    ],
    "lanes": [
        {"id": "L_FRA_KEM", "from_node_id": "FRA_HUB", "to_node_id": "KEM_BRANCH", "mode": "road", "duration_minutes": 360},
    ],
}

@pytest.mark.asyncio
async def test_open_meteo_advisory_vs_demo_thresholds():
    # Mock Open-Meteo response with 12mm rain and 85km/h wind
    mock_hourly = {
        "time": ["2026-09-21T16:00", "2026-09-21T17:00"],
        "precipitation": [12.0, 5.0],
        "wind_gusts_10m": [85.0, 40.0],
        "snowfall": [0.0, 0.0],
        "weather_code": [61, 61],
    }
    
    def handler(request):
        return httpx.Response(200, json={"hourly": mock_hourly})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as mock_client:
        adapter = OpenMeteoAdapter(client=mock_client)

        # 1. Advisory only policy (default)
        req_advisory = PollRequest(
            provider="open_meteo",
            dataset_id="test-1",
            schedule_revision=1,
            evaluation_at="2026-09-21T07:00:00Z",
            network=SAMPLE_NETWORK,
            target_departures={"L_FRA_KEM": ("2026-09-21T16:00:00Z",)},
            weather_delay_policy="advisory_only",
        )
        batch_adv = await adapter.poll(req_advisory)
        assert len(batch_adv.observations) == 1
        assert len(batch_adv.proposed_events) == 0 # no delay event proposed in advisory_only mode
        assert batch_adv.observations[0]["metrics"]["precipitation_mm"] == 12.0

        # 2. Demo thresholds policy: >=10mm (30m), >=80km/h (45m) -> max is 45m!
        req_thresh = PollRequest(
            provider="open_meteo",
            dataset_id="test-1",
            schedule_revision=1,
            evaluation_at="2026-09-21T07:00:00Z",
            network=SAMPLE_NETWORK,
            target_departures={"L_FRA_KEM": ("2026-09-21T16:00:00Z",)},
            weather_delay_policy="demo_thresholds",
        )
        batch_thresh = await adapter.poll(req_thresh)
        assert len(batch_thresh.proposed_events) == 1
        ev = batch_thresh.proposed_events[0]
        assert ev["effect_minutes"] == 45 # max within group, NOT sum (30+45=75)
        assert ev["correlation_key"] == "road-conditions:L_FRA_KEM:2026-09-21T16:00:00Z"
        assert ev["applies_to_departure_at"] == "2026-09-21T16:00:00Z"

@pytest.mark.asyncio
async def test_open_meteo_429_rate_limit():
    def handler(request):
        return httpx.Response(429, content=b"Too many requests")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as mock_client:
        adapter = OpenMeteoAdapter(client=mock_client)
        req = PollRequest(
            provider="open_meteo",
            dataset_id="test-1",
            schedule_revision=1,
            evaluation_at="2026-09-21T07:00:00Z",
            network=SAMPLE_NETWORK,
            target_departures={"L_FRA_KEM": ("2026-09-21T16:00:00Z",)},
            weather_delay_policy="advisory_only",
        )
        batch = await adapter.poll(req)
        assert batch.status["status"] == "stale"
        assert any("429" in w for w in batch.warnings)

@pytest.mark.asyncio
async def test_tomtom_no_key_not_configured():
    adapter = TomTomAdapter(api_key="")
    req = PollRequest(
        provider="tomtom",
        dataset_id="test-1",
        schedule_revision=1,
        evaluation_at="2026-09-21T07:00:00Z",
        network=SAMPLE_NETWORK,
        target_departures={"L_FRA_KEM": ("2026-09-21T16:00:00Z",)},
        weather_delay_policy="advisory_only",
    )
    batch = await adapter.poll(req)
    assert batch.status["status"] == "not_configured"
    assert len(batch.observations) == 0

@pytest.mark.asyncio
async def test_tomtom_route_delay_and_geometry():
    mock_response = {
        "routes": [{
            "summary": {
                "lengthInMeters": 350000,
                "travelTimeInSeconds": 18000,
                "trafficDelayInSeconds": 3660, # 61 minutes
            },
            "legs": [{
                "points": [
                    {"latitude": 50.11, "longitude": 8.68},
                    {"latitude": 47.73, "longitude": 10.31},
                ]
            }]
        }]
    }

    def handler(request):
        return httpx.Response(200, json=mock_response)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as mock_client:
        adapter = TomTomAdapter(api_key="mock-key", client=mock_client)
        req = PollRequest(
            provider="tomtom",
            dataset_id="test-1",
            schedule_revision=1,
            evaluation_at="2026-09-21T07:00:00Z",
            network=SAMPLE_NETWORK,
            target_departures={"L_FRA_KEM": ("2026-09-21T16:00:00Z",)},
            weather_delay_policy="advisory_only",
        )
        batch = await adapter.poll(req)
        assert batch.status["status"] == "ok"
        assert len(batch.observations) == 1
        assert len(batch.geometries) == 1
        assert batch.geometries[0]["geometry_kind"] == "provider_road"
        assert len(batch.proposed_events) == 1
        ev = batch.proposed_events[0]
        # 3660 seconds -> ceil(3660/60) = 61 minutes
        assert ev["effect_minutes"] == 61
        assert ev["correlation_key"] == "road-conditions:L_FRA_KEM:2026-09-21T16:00:00Z"
        assert ev["applies_to_departure_at"] == "2026-09-21T16:00:00Z"

@pytest.mark.asyncio
async def test_operator_bulletin_trusted_vs_untrusted():
    feed_data = {
        "events": [{
            "type": "political",
            "external_id": "notice-1",
            "source_reference": "Border Strike",
            "target_kind": "lane",
            "target_id": "L_FRA_KEM",
            "mode": "road",
            "effect_type": "closure",
            "reason": "Border block",
        }]
    }
    
    def handler(request):
        return httpx.Response(200, json=feed_data)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as mock_client:
        # Untrusted feed
        adapter_untrusted = OperatorBulletinAdapter(feed_url_or_path="http://bulletins/feed.json", is_trusted=False, client=mock_client)
        req = PollRequest(
            provider="operator_bulletins",
            dataset_id="test-1",
            schedule_revision=1,
            evaluation_at="2026-09-21T07:00:00Z",
            network=SAMPLE_NETWORK,
            target_departures={},
            weather_delay_policy="advisory_only",
        )
        batch_untrusted = await adapter_untrusted.poll(req)
        assert batch_untrusted.proposed_events[0]["verification_status"] == "pending"

        # Trusted feed
        adapter_trusted = OperatorBulletinAdapter(feed_url_or_path="http://bulletins/feed.json", is_trusted=True, client=mock_client)
        batch_trusted = await adapter_trusted.poll(req)
        assert batch_trusted.proposed_events[0]["verification_status"] == "accepted"

@pytest.mark.asyncio
async def test_orchestrator_ingestion(temp_db):
    repo = temp_db["repo"]
    orchestrator = temp_db["orchestrator"]
    with pytest.raises(ConcurrencyError) as exc:
        orchestrator.ingest_batches([])
    assert exc.value.code == "MODE_MISMATCH"
    assert repo.get_state().integrations_revision == 0


@pytest.mark.asyncio
async def test_live_traffic_ingestion_deduplicates_and_withdraws(temp_db):
    repo = temp_db["repo"]
    repo.conn.execute("UPDATE app_state SET mode = 'live' WHERE id = 1")
    repo.conn.commit()
    departure = "2026-09-21T16:00:00Z"
    delay = {"seconds": 3660}
    search = SearchRequest(
        origin_id="FRA_HUB", destination_id="KEM_BRANCH",
        ready_at="2026-09-21T08:00:00Z", service_profile_id="mixed", max_results=10,
    )

    def direct_arrival():
        routes, _ = search_routes(repo.get_network(), search, repo.get_events(),
                                  parse_iso_dt(repo.get_state().simulation_clock))
        return parse_iso_dt(next(route.arrival_at for route in routes
                                 if route.lane_ids == ["L_FRA_KEM"]))

    baseline_arrival = direct_arrival()

    def handler(request):
        return httpx.Response(200, json={"routes": [{"summary": {
            "trafficDelayInSeconds": delay["seconds"], "travelTimeInSeconds": 18000,
        }, "legs": []}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = TomTomAdapter(api_key="test-key", client=client)

        async def batch():
            state = repo.get_state()
            return await adapter.poll(PollRequest(
                provider="tomtom", dataset_id=state.snapshot.dataset_id,
                schedule_revision=state.snapshot.schedule_revision,
                evaluation_at=state.simulation_clock,
                network=repo.get_network().model_dump(),
                target_departures={"L_FRA_KEM": (departure,)},
                weather_delay_policy="advisory_only",
            ))

        first = await batch()
        assert first.proposed_events[0]["valid_until"] > departure
        assert first.proposed_events[0]["review_due_at"] > first.proposed_events[0]["observed_at"]
        assert temp_db["orchestrator"].ingest_batches([first]) == (1, 1)
        assert repo.get_events()[0].effect_minutes == 61
        assert (direct_arrival() - baseline_arrival).total_seconds() == 61 * 60
        assert repo.get_integrations().providers[1].status == "ok"

        repeat = await batch()
        assert temp_db["orchestrator"].ingest_batches([repeat]) == (0, 0)
        assert repo.get_events()[0].version == 1

        delay["seconds"] = 120
        updated = await batch()
        assert temp_db["orchestrator"].ingest_batches([updated]) == (1, 1)
        assert repo.get_events()[0].version == 2
        assert repo.get_events()[0].effect_minutes == 2
        assert (direct_arrival() - baseline_arrival).total_seconds() == 2 * 60

        delay["seconds"] = 0
        cleared = await batch()
        assert temp_db["orchestrator"].ingest_batches([cleared]) == (1, 1)
        assert repo.get_events()[0].version == 3
        assert repo.get_events()[0].lifecycle_status == "withdrawn"
        assert direct_arrival() == baseline_arrival

        repo.conn.execute("UPDATE app_state SET schedule_revision = schedule_revision + 1 WHERE id = 1")
        repo.conn.commit()
        with pytest.raises(ConcurrencyError) as exc:
            temp_db["orchestrator"].ingest_batches([cleared])
        assert exc.value.code == "STALE_SNAPSHOT"


@pytest.mark.asyncio
async def test_provider_failure_and_missing_metric_do_not_create_zero_delay():
    request = PollRequest(
        provider="tomtom", dataset_id="live-test", schedule_revision=1,
        evaluation_at="2026-09-21T07:00:00Z", network=SAMPLE_NETWORK,
        target_departures={"L_FRA_KEM": ("2026-09-21T16:00:00Z",)},
        weather_delay_policy="advisory_only",
    )

    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda req: httpx.Response(200, json={"routes": [{"summary": {}}]})
    )) as client:
        result = await TomTomAdapter(api_key="test-key", client=client).poll(request)
        assert result.status["status"] == "stale"
        assert result.observations == ()
        assert result.proposed_events == ()

    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda req: httpx.Response(503)
    )) as client:
        result = await OpenMeteoAdapter(client=client).poll(request)
        assert result.status["status"] == "stale"
        assert result.observations == ()


@pytest.mark.asyncio
async def test_crashed_adapter_is_reported(temp_db):
    class CrashedAdapter:
        async def poll(self, request):
            raise RuntimeError("simulated adapter crash")

    class EmptyAdapter:
        async def poll(self, request):
            return ProviderBatch(
                provider=request.provider, dataset_id=request.dataset_id,
                schedule_revision=request.schedule_revision, observations=(),
                proposed_events=(), geometries=(), status={
                    "name": request.provider, "status": "disabled", "last_poll_at": None,
                    "last_successful_poll_at": None, "consecutive_errors": 0,
                    "error_message": None, "mode": "demo",
                }, warnings=(),
            )

    orchestrator = ProviderOrchestrator(temp_db["repo"], CrashedAdapter(), EmptyAdapter(), EmptyAdapter())
    batches = await orchestrator.poll_all()
    assert [batch.provider for batch in batches] == ["open_meteo", "tomtom", "operator_bulletins"]
    assert batches[0].status["status"] == "error"
