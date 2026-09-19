import type { Model } from "./api";

type Snapshot = Model<"Snapshot">;
type Route = Model<"Route">;

const baseSnapshot: Snapshot = {
  dataset_id: "demo-seed-1",
  schedule_revision: 1,
  event_revision: 1,
  clock_revision: 0,
};

let eventRevision = 1;
let clockRevision = 0;
let planRevision = 0;
let scenario = "";
let simulationClock = "2026-09-21T07:00:00Z";
let events: any[] = [];
let plans: any[] = [];
const decisions = new Map<string, any[]>();

const snapshot = (): Snapshot => ({
  ...baseSnapshot,
  event_revision: eventRevision,
  clock_revision: clockRevision,
});

const nodes = [
  node("FRA_AIR", "Frankfurt airport hand-over", "hand_over", "DE", 50.04, 8.57, 120),
  node("FRA_HUB", "Frankfurt hub", "hub", "DE", 50.11, 8.68, 120),
  node("HAM_BRANCH", "Hamburg branch", "branch", "DE", 53.55, 9.99, 0),
  node("IST_AIR", "Istanbul airport hand-over", "hand_over", "TR", 41.28, 28.75, 60, "Europe/Istanbul"),
  node("IST_BRANCH", "Istanbul branch", "branch", "TR", 41.01, 28.98, 60, "Europe/Istanbul"),
  node("KEM_BRANCH", "Kempten branch", "branch", "DE", 47.73, 10.31, 0),
  node("MUC_HUB", "Munich hub", "hub", "DE", 48.14, 11.58, 60),
  node("PAR_HUB", "Paris hub", "hub", "FR", 48.86, 2.35, 60, "Europe/Paris"),
  node("STR_HUB", "Strasbourg hub", "hub", "FR", 48.58, 7.75, 60, "Europe/Paris"),
];

const lanes = [
  lane("L_AIR_HUB", "FRA_AIR", "FRA_HUB", "road", 60, "21:00"),
  lane("L_FRA_HAM", "FRA_HUB", "HAM_BRANCH", "road", 480, "20:00"),
  lane("L_FRA_KEM", "FRA_HUB", "KEM_BRANCH", "road", 360, "18:00", [1, 2, 3, 4, 5], 60),
  lane("L_FRA_MUC", "FRA_HUB", "MUC_HUB", "road", 300, "15:00"),
  lane("L_FRA_STR", "FRA_HUB", "STR_HUB", "road", 180, "13:00"),
  lane("L_IST_AIR", "IST_BRANCH", "IST_AIR", "road", 60, "12:00"),
  lane("L_IST_FLIGHT", "IST_AIR", "FRA_AIR", "air", 180, "15:00", [1, 2, 3, 4, 5, 6, 7], 60),
  lane("L_MUC_KEM", "MUC_HUB", "KEM_BRANCH", "road", 120, "22:00"),
  lane("L_PAR_STR", "PAR_HUB", "STR_HUB", "road", 360, "09:00"),
  lane("L_STR_KEM", "STR_HUB", "KEM_BRANCH", "road", 300, "20:00"),
];

const geometry = lanes.map((l) => {
  const from = nodes.find((n) => n.id === l.from_node_id)!;
  const to = nodes.find((n) => n.id === l.to_node_id)!;
  return {
    lane_id: l.id,
    departure_at: null,
    geometry_kind: "schematic",
    geometry: { type: "LineString", coordinates: [[from.longitude, from.latitude], [to.longitude, to.latitude]] },
    source: "Synthetic facility coordinates",
    attribution: "Demo geometry; not verified road routing",
    fetched_at: null,
    stale: false,
  };
});

function node(id: string, name: string, type: string, country: string, latitude: number, longitude: number, processing_minutes: number, timezone = "Europe/Berlin") {
  return { id, name, type, country, timezone, latitude, longitude, processing_minutes, active: true, provenance: "demo_assumption" };
}

function lane(id: string, from_node_id: string, to_node_id: string, mode: string, duration_minutes: number, local_time: string, weekdays = [1, 2, 3, 4, 5, 6, 7], cutoff_minutes = 30) {
  return {
    id, from_node_id, to_node_id, mode, duration_minutes, active: true,
    valid_from: "2026-09-01", valid_to: "2026-11-15",
    departures: [{ id: `${id}_D1`, weekdays, local_time, cutoff_minutes }],
    provenance: "demo_assumption",
  };
}

function addMinutes(iso: string, minutes: number) {
  return new Date(new Date(iso).getTime() + minutes * 60000).toISOString().replace(".000Z", "Z");
}

function reason(code: string, minutes: number, description: string, event_ids: string[] = []) {
  return { code, minutes, description, event_ids };
}

function route(id: string, lane_ids: string[], departure_times: string[], ready_at: string, durations: number[], waits: number[], eventId = ""): Route {
  const segments: any[] = [];
  let cursor = ready_at;
  segments.push({ segment_index: 0, type: "handle", node_id: "FRA_HUB", lane_id: null, start_at: cursor, end_at: addMinutes(cursor, 120), duration_minutes: 120, reasons: [reason("NODE_HANDLING", 120, "Standard handling at Frankfurt hub (FRA_HUB)")] });
  cursor = addMinutes(cursor, 120);
  lane_ids.forEach((laneId, i) => {
    const laneInfo = lanes.find((l) => l.id === laneId)!;
    const wait = waits[i] || 0;
    if (wait) {
      const nodeId = laneInfo.from_node_id;
      segments.push({ segment_index: segments.length, type: "wait", node_id: nodeId, lane_id: null, start_at: cursor, end_at: addMinutes(cursor, wait), duration_minutes: wait, reasons: [reason("WAIT_DEPARTURE", wait, `Waiting for scheduled departure at ${nodes.find((n) => n.id === nodeId)?.name || nodeId}`)] });
      cursor = addMinutes(cursor, wait);
    }
    const extraEvent = eventId && laneId === "L_FRA_KEM";
    segments.push({ segment_index: segments.length, type: "travel", node_id: null, lane_id: laneId, start_at: cursor, end_at: addMinutes(cursor, durations[i]), duration_minutes: durations[i], reasons: [reason("LANE_TRAVEL", durations[i], `Scheduled transit on lane ${laneId}`, extraEvent ? [eventId] : [])] });
    cursor = addMinutes(cursor, durations[i]);
    const toNode = laneInfo.to_node_id;
    if (i < lane_ids.length - 1) {
      const handle = toNode === "MUC_HUB" && scenario === "handling_munich" ? 180 : 60;
      segments.push({ segment_index: segments.length, type: "handle", node_id: toNode, lane_id: null, start_at: cursor, end_at: addMinutes(cursor, handle), duration_minutes: handle, reasons: [reason("NODE_HANDLING", handle, `Handling at ${nodes.find((n) => n.id === toNode)?.name || toNode}`, scenario === "handling_munich" && toNode === "MUC_HUB" ? ["evt-handling-munich"] : [])] });
      cursor = addMinutes(cursor, handle);
    }
  });
  return { id, lane_ids, departure_times, arrival_at: cursor, total_minutes: Math.round((new Date(cursor).getTime() - new Date(ready_at).getTime()) / 60000), transfer_count: lane_ids.length - 1, segments, explanation: [] };
}

function search(body: any) {
  const ready = body?.ready_at || "2026-09-21T08:00:00Z";
  const traffic = scenario === "traffic_direct";
  const closure = scenario === "closure_strasbourg";
  const currentEvents = events.filter((e) => e.lifecycle_status === "active" && e.verification_status === "accepted");
  const manualDirect = currentEvents.find((e) => e.target_id === "L_FRA_KEM" && e.effect_type === "additional_travel_minutes");
  const directExtra = (traffic ? 180 : 0) + (manualDirect?.effect_minutes || 0);
  const direct = route("route-direct", ["L_FRA_KEM"], ["2026-09-21T16:00:00Z"], ready, [360 + directExtra], [360], traffic ? "evt-traffic-direct" : manualDirect?.id || "");
  const mucHandle = scenario === "handling_munich" ? 120 : 0;
  const muc = route("route-via-munich", ["L_FRA_MUC", "L_MUC_KEM"], ["2026-09-21T13:00:00Z", "2026-09-21T20:00:00Z"], ready, [300, 120], [180, Math.max(0, 60 - mucHandle)]);
  if (mucHandle) muc.total_minutes += 120, muc.arrival_at = addMinutes(muc.arrival_at, 120);
  const routes = [direct, muc];
  if (!closure) routes.push(route("route-via-strasbourg", ["L_FRA_STR", "L_STR_KEM"], ["2026-09-21T11:00:00Z", "2026-09-21T18:00:00Z"], ready, [180, 300], [60, 180]));
  routes.sort((a, b) => a.total_minutes - b.total_minutes);
  return { snapshot: snapshot(), search_id: `search-${Date.now().toString(36)}`, status: routes.length ? "feasible" : "no_feasible_route", routes, diagnostics: [] };
}

function preset(id: string) {
  scenario = id;
  eventRevision++;
  const label: Record<string, any> = {
    traffic_direct: ["evt-traffic-direct", "traffic", "L_FRA_KEM", 180, "Heavy traffic on the direct Frankfurt to Kempten corridor."],
    handling_munich: ["evt-handling-munich", "operational", "MUC_HUB", 120, "Munich hub congestion increases transfer handling."],
    closure_strasbourg: ["evt-closure-strasbourg", "political", "L_STR_KEM", null, "Border restriction closes the Strasbourg to Kempten connection."],
  };
  const [eventId, type, target, minutes, text] = label[id] || label.traffic_direct;
  events = events.filter((e) => !String(e.id).startsWith("evt-"));
  events.push(event(eventId, type, target, minutes, text, "demo_feed", "accepted"));
  refreshPlans();
  return { snapshot: snapshot() };
}

function event(id: string, type: string, target_id: string, effect_minutes: number | null, reasonText: string, source_kind = "manager", verification_status = "accepted") {
  return {
    id, version: 1, type, source_kind, external_id: id, source_reference: source_kind === "demo_feed" ? "Static demo scenario" : "Operations manager report",
    observed_at: simulationClock, received_at: simulationClock, valid_from: simulationClock, valid_until: "2026-09-22T07:00:00Z",
    review_due_at: null, target_kind: target_id.endsWith("_HUB") || target_id.endsWith("_BRANCH") ? "node" : "lane", target_id,
    mode: "road", effect_type: effect_minutes === null ? "closure" : "additional_travel_minutes", effect_minutes,
    verification_status, lifecycle_status: "active", correlation_key: id, reason: reasonText,
    applies_to_departure_at: null, observation_id: null, review_overdue: false,
  };
}

function refreshPlans() {
  plans = plans.map((p) => {
    const response = search({ ready_at: p.ready_at });
    const selected_projection = response.routes.find((r: Route) => r.lane_ids.join("|") === p.selected_itinerary.lane_ids.join("|")) || null;
    const changed = selected_projection && selected_projection.arrival_at !== p.selected_itinerary.arrival_at;
    return {
      ...p,
      status: changed ? "review_required" : "stable",
      selected_projection,
      review_reasons: changed ? ["Conditions changed after this plan was saved. Manager review is required."] : [],
      alternative_recommendations: response.routes.filter((r: Route) => r.id !== selected_projection?.id).slice(0, 2),
      plan_revision: ++planRevision,
    };
  });
}

export async function demoApi<T>(path: string, body?: any, method = "POST"): Promise<T> {
  if (path === "/state") return { api_version: "2.0.0", snapshot: snapshot(), simulation_clock: simulationClock, demo_mode: true, mode: "demo", plans_revision: planRevision, integrations_revision: 0 } as T;
  if (path === "/network") return { snapshot: snapshot(), nodes, lanes, calendar_rules: [{ id: "DEMO_SUNDAY_HAM", lane_id: "L_FRA_HAM", mode: "road", timezone: "Europe/Berlin", weekday: 7, start_local_time: "00:00", end_next_day_local_time: "00:00", action: "pause_travel", provenance: "demo_assumption" }], service_profiles: [{ id: "mixed", allowed_modes: ["road", "air"], max_lanes: 5, scope: "branch_to_branch" }, { id: "road_only", allowed_modes: ["road"], max_lanes: 5, scope: "branch_to_branch" }] } as T;
  if (path === "/events") return { snapshot: snapshot(), events } as T;
  if (path === "/plans") {
    if (body) {
      const routeFound = search({ ready_at: "2026-09-21T08:00:00Z" }).routes.find((r: Route) => r.id === body.route_id) || search({ ready_at: "2026-09-21T08:00:00Z" }).routes[0];
      plans.push({ plan_id: `plan-${plans.length + 1}`, plan_revision: ++planRevision, name: body.name || "Saved delivery promise", status: "stable", ready_at: "2026-09-21T08:00:00Z", selected_itinerary: routeFound, selected_projection: routeFound, review_reasons: [], alternative_recommendations: [], created_at: new Date().toISOString() });
      return plans.at(-1) as T;
    }
    return { snapshot: snapshot(), plans } as T;
  }
  if (path.match(/^\/plans\/.+\/decisions$/)) {
    const id = path.split("/")[2];
    if (!body) return { decisions: decisions.get(id) || [] } as T;
    const list = decisions.get(id) || [];
    list.unshift({ id: `decision-${Date.now()}`, action: body.action, actor: body.actor, reason: body.reason, route_id: body.route_id, decided_at: new Date().toISOString(), review_evidence: { snapshot: snapshot(), static_demo: true } });
    decisions.set(id, list);
    plans = plans.map((p) => p.plan_id === id ? { ...p, status: body.action === "defer" ? "review_required" : "stable", plan_revision: ++planRevision } : p);
    return { ok: true } as T;
  }
  if (path === "/map/geometry") return { snapshot: snapshot(), integrations_revision: 0, lanes: geometry } as T;
  if (path === "/data-summary") return dataSummary as T;
  if (path === "/integrations") return { providers: [{ name: "tomtom_traffic", status: "ok", mode: "demo", last_successful_poll_at: null, error_message: null }, { name: "openweather", status: "ok", mode: "demo", last_successful_poll_at: null, error_message: null }, { name: "gdacs", status: "ok", mode: "demo", last_successful_poll_at: null, error_message: null }] } as T;
  if (path === "/integrations/observations") return { observations: [] } as T;
  if (path === "/routes/search") return search(body) as T;
  if (path === "/demo/presets") return preset(body.preset_id) as T;
  if (path === "/demo/clock") return (simulationClock = body.target_clock, clockRevision++, { snapshot: snapshot() }) as T;
  if (path === "/demo/reset") return (scenario = "", events = [], plans = [], eventRevision++, planRevision++, { snapshot: snapshot() }) as T;
  if (path === "/events" && method === "POST") return (events.unshift(event(`evt-${Date.now()}`, body.event.type, body.event.target_id, body.event.effect_minutes, body.event.reason, "manager", body.event.verification_status)), eventRevision++, refreshPlans(), { snapshot: snapshot() }) as T;
  if (path.match(/^\/events\/.+\/revisions$/)) return (events = events.map((e) => path.includes(e.id) ? { ...e, lifecycle_status: "withdrawn", reason: body.event.reason } : e), eventRevision++, refreshPlans(), { snapshot: snapshot() }) as T;
  return {} as T;
}

const dataSummary = {
  sources: [
    { filename: "disposition.csv", rows: 19980, date_from: "2024-01-02", date_to: "2026-08-31", issues: [], sha256: "demo" },
    { filename: "kalender.csv", rows: 1050, date_from: "2024-01-01", date_to: "2026-11-15", issues: [], sha256: "demo" },
    { filename: "kundensignale.csv", rows: 72, date_from: "2024-01-05", date_to: "2026-09-22", issues: ["3 signals have missing end dates"], sha256: "demo" },
    { filename: "stoerungen.csv", rows: 7, date_from: "2024-01-17", date_to: "2026-04-23", issues: [], sha256: "demo" },
    { filename: "vertriebsereignisse.csv", rows: 188, date_from: "2024-01-01", date_to: "2026-07-31", issues: [], sha256: "demo" },
  ],
  assumptions: [
    "Source CSV data contains historical operational volume, not carrier timetables or ETA labels.",
    "Nine nodes and ten lanes are synthetic prototype assumptions.",
    "Traffic, weather and political disruption reports become route penalties or closures.",
    "Manager decisions are required before changing a saved customer promise.",
  ],
  import_complete: true,
  capacity_example: { source_file: "disposition.csv", relation: "R01", destination: "Hamburg", date: "2024-01-04", planned_trailers: 4, needed_trailers: 5, special_trips: 1, loading_metres: 55.5, trailer_capacity_metres: 13.6 },
};
