"""Provider adapter tests verifying Open-Meteo, TomTom, and Operator Bulletins."""
import json
import pytest
import httpx

from backend.app.contracts.provider_protocol import PollRequest, ProviderBatch
from backend.app.providers.open_meteo import OpenMeteoAdapter
from backend.app.providers.tomtom import TomTomAdapter
from backend.app.providers.operator_bulletins import OperatorBulletinAdapter
from backend.app.providers.orchestrator import ProviderOrchestrator

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

    # Poll with mock/simulated batch
    batches = await orchestrator.poll_all()
    assert len(batches) >= 1
    obs_count, ev_count = orchestrator.ingest_batches(batches)
    assert obs_count >= 0
    # State integrations revision incremented
    state = repo.get_state()
    assert state.integrations_revision >= 1
