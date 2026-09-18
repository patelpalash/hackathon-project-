"""API integration tests verifying all operations against docs/contracts/openapi.json."""
import pytest
import httpx

@pytest.mark.asyncio
async def test_health_and_state(api_client: httpx.AsyncClient):
    r_health = await api_client.get("/api/health")
    assert r_health.status_code == 200
    data_health = r_health.json()
    assert data_health["status"] == "ok"
    assert data_health["database"] == "connected"

    r_state = await api_client.get("/api/state")
    assert r_state.status_code == 200
    data_state = r_state.json()
    assert data_state["api_version"] == "2.0.0"
    assert data_state["mode"] == "demo"
    assert "snapshot" in data_state

@pytest.mark.asyncio
async def test_network_and_data_summary(api_client: httpx.AsyncClient):
    r_net = await api_client.get("/api/network")
    assert r_net.status_code == 200
    net = r_net.json()
    assert len(net["nodes"]) == 9
    assert len(net["lanes"]) == 10

    r_ds = await api_client.get("/api/data-summary")
    assert r_ds.status_code == 200
    ds = r_ds.json()
    assert "sources" in ds
    assert ds["capacity_example"] is not None
    assert ds["capacity_example"]["relation"] == "R01"

@pytest.mark.asyncio
async def test_search_and_plan_decision_flow(api_client: httpx.AsyncClient):
    # 1. State
    r_state = await api_client.get("/api/state")
    state = r_state.json()
    snap = state["snapshot"]

    # 2. Search
    search_payload = {
        "origin_id": "FRA_HUB",
        "destination_id": "KEM_BRANCH",
        "ready_at": "2026-09-21T08:00:00Z",
        "service_profile_id": "mixed",
        "max_results": 3,
    }
    r_search = await api_client.post("/api/routes/search", json=search_payload)
    assert r_search.status_code == 200
    search_res = r_search.json()
    assert search_res["status"] == "feasible"
    assert len(search_res["routes"]) == 3
    search_id = search_res["search_id"]
    direct_route = search_res["routes"][0]

    # 3. Create plan
    plan_payload = {
        "mutation_id": "m-plan-api-1",
        "expected_snapshot": snap,
        "search_id": search_id,
        "route_id": direct_route["id"],
        "name": "Judge Demo Plan",
    }
    r_plan = await api_client.post("/api/plans", json=plan_payload)
    assert r_plan.status_code == 201
    plan = r_plan.json()
    plan_id = plan["plan_id"]
    assert plan["status"] == "stable"
    assert plan["selected_itinerary"]["arrival_at"] == "2026-09-21T22:00:00Z"

    # Idempotent retry of plan creation returns same plan
    r_retry = await api_client.post("/api/plans", json=plan_payload)
    assert r_retry.status_code == 201
    assert r_retry.json()["plan_id"] == plan_id

    # 4. Apply preset: traffic_direct -> adds 180 min to direct lane
    preset_payload = {
        "mutation_id": "m-preset-traffic",
        "expected_snapshot": snap,
        "preset_id": "traffic_direct",
    }
    r_preset = await api_client.post("/api/demo/presets", json=preset_payload)
    assert r_preset.status_code == 200
    assert r_preset.json()["event"]["effect_minutes"] == 180

    # 5. Fetch plan -> direct projection delayed to 2026-09-22T01:00:00Z, Munich recommended
    r_get_plan = await api_client.get(f"/api/plans/{plan_id}")
    assert r_get_plan.status_code == 200
    plan_after_preset = r_get_plan.json()
    assert plan_after_preset["selected_projection"]["arrival_at"] == "2026-09-22T01:00:00Z"
    # Alternative Munich arrives at 2026-09-21T22:00:00Z (3h earlier) -> review required!
    assert plan_after_preset["status"] == "review_required"
    munich_alt = next(r for r in plan_after_preset["alternative_recommendations"] if "L_FRA_MUC" in r["lane_ids"])

    # 6. Accept Munich recommendation
    cur_snap = (await api_client.get("/api/state")).json()["snapshot"]
    dec_payload = {
        "mutation_id": "m-accept-munich",
        "expected_snapshot": cur_snap,
        "expected_plan_revision": plan_after_preset["plan_revision"],
        "actor": "demo-manager",
        "action": "accept_route",
        "route_id": munich_alt["id"],
        "reason": "Munich route avoids 180m direct road delay",
    }
    r_dec = await api_client.post(f"/api/plans/{plan_id}/decisions", json=dec_payload)
    assert r_dec.status_code == 201
    dec_res = r_dec.json()
    assert dec_res["plan"]["selected_itinerary"]["arrival_at"] == "2026-09-21T22:00:00Z"
    assert dec_res["plan"]["status"] == "stable"
    assert dec_res["decision"]["action"] == "accept_route"

    # 7. Get decisions list
    r_decs = await api_client.get(f"/api/plans/{plan_id}/decisions")
    assert r_decs.status_code == 200
    decs_list = r_decs.json()["decisions"]
    assert len(decs_list) == 1
    assert decs_list[0]["review_evidence"]["reviewed_snapshot"] == cur_snap

@pytest.mark.asyncio
async def test_error_envelopes(api_client: httpx.AsyncClient):
    # 404 for unknown api path
    r_404 = await api_client.get("/api/unknown-resource-path")
    assert r_404.status_code == 404
    body_404 = r_404.json()
    assert "error" in body_404
    assert body_404["error"]["code"] == "NOT_FOUND"

    # 422 for invalid search input (e.g. past ready time)
    bad_search = {
        "origin_id": "FRA_HUB",
        "destination_id": "KEM_BRANCH",
        "ready_at": "2026-09-20T08:00:00Z", # before simulation clock 2026-09-21T07:00Z
        "service_profile_id": "mixed",
    }
    r_bad = await api_client.post("/api/routes/search", json=bad_search)
    assert r_bad.status_code == 422
    body_bad = r_bad.json()
    assert "error" in body_bad
    assert body_bad["error"]["code"] == "PAST_READY_TIME"

    # 409 for stale snapshot on node patch
    stale_snap = {
        "dataset_id": "stale-dataset",
        "schedule_revision": 999,
        "event_revision": 0,
        "clock_revision": 0,
    }
    patch_node_stale = {
        "mutation_id": "m-stale",
        "expected_snapshot": stale_snap,
        "processing_minutes": 150,
    }
    r_stale = await api_client.patch("/api/nodes/FRA_HUB", json=patch_node_stale)
    assert r_stale.status_code == 409
    body_stale = r_stale.json()
    assert body_stale["error"]["code"] == "STALE_SNAPSHOT"

@pytest.mark.asyncio
async def test_map_geometry_and_integrations(api_client: httpx.AsyncClient):
    r_geom = await api_client.get("/api/map/geometry")
    assert r_geom.status_code == 200
    geom_data = r_geom.json()
    assert len(geom_data["lanes"]) >= 10
    assert geom_data["lanes"][0]["geometry"]["type"] == "LineString"

    r_int = await api_client.get("/api/integrations")
    assert r_int.status_code == 200
    int_data = r_int.json()
    assert len(int_data["providers"]) == 3

    r_obs = await api_client.get("/api/integrations/observations")
    assert r_obs.status_code == 200
    assert "observations" in r_obs.json()
