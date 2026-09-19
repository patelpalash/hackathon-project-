import { useEffect, useState } from "react";
import { DateTime } from "luxon";
import {
  ArrowRight,
  Clock,
  Truck,
  Package,
  Plane,
  AlertTriangle,
  Check,
  Plus,
  Zap,
  ShieldCheck,
  Database,
  RefreshCw,
  ChevronRight,
} from "lucide-react";
import {
  api,
  intent,
  duration,
  stamp,
  type Route,
  type Network,
  type Model,
  type Plan,
} from "./api";
import type { Bundle } from "./App";
type Mutate = (path: string, body: unknown, method?: string) => Promise<any>;
export function Timeline({
  route,
  network,
}: {
  route: Route;
  network: Network;
}) {
  const [expanded, setExpanded] = useState<number | null>(null);
  const colors = { travel: "#3e70e8", handle: "#e6ad52", wait: "#a8b8c7" };
  return (
    <div className="timeline-content">
      <div className="timeline-bar">
        {route.segments.map((s, i) => (
          <button
            title={`${s.type}: ${duration(s.duration_minutes)}`}
            key={i}
            style={{ flex: s.duration_minutes, background: colors[s.type] }}
            onClick={() => setExpanded(expanded === i ? null : i)}
          />
        ))}
      </div>
      <div className="timeline-key">
        <span>
          <i style={{ background: colors.travel }} />
          Movement
        </span>
        <span>
          <i style={{ background: colors.handle }} />
          Handling
        </span>
        <span>
          <i style={{ background: colors.wait }} />
          Scheduled wait
        </span>
        <span className="muted">All times shown in facility timezone</span>
      </div>
      <div className="journey-steps">
        {route.segments.map((s, i) => {
          const lane = network.lanes.find((l) => l.id === s.lane_id),
            node = network.nodes.find(
              (n) => n.id === (s.node_id || lane?.from_node_id),
            );
          const Icon =
            s.type === "handle"
              ? Package
              : s.type === "wait"
                ? Clock
                : lane?.mode === "air"
                  ? Plane
                  : Truck;
          return (
            <div
              className={`journey-step ${expanded === i ? "expanded" : ""}`}
              key={i}
            >
              <button onClick={() => setExpanded(expanded === i ? null : i)}>
                <span className={`step-icon ${s.type}`}>
                  <Icon size={17} />
                </span>
                <div>
                  <strong>
                    {s.type === "travel"
                      ? `${lane?.from_node_id.split("_")[0]} → ${lane?.to_node_id.split("_")[0]}`
                      : node?.name || s.type}
                  </strong>
                  <small>
                    {s.type === "travel"
                      ? "Scheduled transit"
                      : s.type === "handle"
                        ? "Facility handling"
                        : "Wait for connection"}
                  </small>
                </div>
                <div className="step-time">
                  <strong>{duration(s.duration_minutes)}</strong>
                  <small>{stamp(s.start_at, node?.timezone)}</small>
                </div>
                <ChevronRight size={14} />
              </button>
              {expanded === i && (
                <div className="segment-details">
                  <p>
                    {stamp(s.start_at, node?.timezone)} →{" "}
                    {stamp(s.end_at, node?.timezone)}
                  </p>
                  {s.reasons.map((r, j) => (
                    <p key={j}>
                      {r.description} · {r.minutes} min
                      {r.event_ids.length
                        ? ` · events: ${r.event_ids.join(", ")}`
                        : ""}
                    </p>
                  ))}
                  <small>
                    UTC: {s.start_at} → {s.end_at}
                  </small>
                </div>
              )}
            </div>
          );
        })}
      </div>
      <div className="arrival-strip">
        <Check size={17} />
        <span>Expected arrival</span>
        <strong>
          {stamp(
            route.arrival_at,
            network.nodes.find(
              (n) =>
                n.id ===
                network.lanes.find((l) => l.id === route.lane_ids.at(-1))
                  ?.to_node_id,
            )?.timezone,
          )}
        </strong>
        <span>{duration(route.total_minutes)} total</span>
      </div>
    </div>
  );
}
export function ReviewView({
  bundle,
  busy,
  mutate,
  onReport,
}: {
  bundle: Bundle;
  busy: boolean;
  mutate: Mutate;
  onReport: () => void;
}) {
  const [review, setReview] = useState<{
      plan: Plan;
      snapshot: Bundle["state"]["snapshot"];
    }>(),
    [reason, setReason] = useState(""),
    [alternative, setAlternative] = useState(""),
    [history, setHistory] = useState<Model<"Decision">[]>([]),
    [filter, setFilter] = useState("current");
  const current = bundle.plans.find((p) => p.plan_id === review?.plan.plan_id);
  const stale =
    !!review &&
    (current?.plan_revision !== review.plan.plan_revision ||
      JSON.stringify(bundle.state.snapshot) !==
        JSON.stringify(review.snapshot));
  useEffect(() => {
    if (!review) return;
    const controller = new AbortController();
    api<Model<"DecisionList">>(
      `/plans/${review.plan.plan_id}/decisions`,
      undefined,
      "GET",
      controller.signal,
    )
      .then((d) => setHistory(d.decisions))
      .catch(() => {});
    return () => controller.abort();
  }, [review?.plan.plan_id, bundle.state.plans_revision]);
  const open = (plan: Plan) => {
    setReview({ plan, snapshot: bundle.state.snapshot });
    setAlternative(plan.alternative_recommendations[0]?.id || "");
    setReason("");
  };
  const decide = async (action: string) => {
    if (!review) return;
    try {
      const response = await mutate(`/plans/${review.plan.plan_id}/decisions`, {
        mutation_id: intent(),
        expected_snapshot: review.snapshot,
        expected_plan_revision: review.plan.plan_revision,
        actor: "demo-manager",
        action,
        route_id: action === "accept_route" ? alternative : null,
        reason,
      });
      if (response) {
        setReview(undefined);
        setReason("");
      }
    } catch {}
  };
  const preset = async (id: string) => {
    try {
      await mutate("/demo/presets", {
        mutation_id: intent(),
        expected_snapshot: bundle.state.snapshot,
        preset_id: id,
      });
    } catch {}
  };
  const filtered = bundle.events.filter(
    (e) =>
      filter === "all" ||
      (filter === "pending" && e.verification_status === "pending") ||
      (filter === "current" && e.lifecycle_status === "active"),
  );
  return (
    <>
      <div className="card scenario-controls">
        <div>
          <span className="eyebrow">SIMULATION LAB</span>
          <h2>A change in conditions. A better decision.</h2>
          <p className="muted">
            Presets update the backend and recalculate affected plans.
          </p>
        </div>
        <div className="actions wrap">
          {[
            ["traffic_direct", "Traffic +180 min"],
            ["handling_munich", "Munich handling"],
            ["closure_strasbourg", "Border closure"],
          ].map(([id, label]) => (
            <button
              key={id}
              className="button"
              disabled={busy || bundle.state.mode !== "demo"}
              onClick={() => void preset(id)}
            >
              <Zap size={14} />
              {label}
            </button>
          ))}
        </div>
      </div>
      <div className="review-grid">
        <section className="card">
          <div className="section-title">
            <h2>Network disruptions</h2>
            <button className="button primary" onClick={onReport}>
              <Plus size={15} />
              Report
            </button>
          </div>
          <div className="tabs">
            {["current", "pending", "all"].map((f) => (
              <button
                className={f === filter ? "active" : ""}
                key={f}
                onClick={() => setFilter(f)}
              >
                {f}
              </button>
            ))}
          </div>
          <div className="events-list">
            {filtered.map((e) => (
              <article className="event-card" key={e.id}>
                <div className="event-heading">
                  <span className={`event-icon ${e.type}`}>
                    <AlertTriangle size={17} />
                  </span>
                  <div>
                    <strong>
                      {e.type} · {e.target_id}
                    </strong>
                    <small>
                      {e.source_kind === "demo_feed"
                        ? "SIMULATED FEED"
                        : e.source_kind === "provider"
                          ? "PROVIDER"
                          : "MANAGER"}
                    </small>
                  </div>
                  <span className="badge amber">
                    {e.lifecycle_status === "withdrawn"
                      ? "withdrawn"
                      : e.verification_status}
                  </span>
                </div>
                <p>{e.reason}</p>
                <div className="event-meta">
                  {e.effect_minutes !== null
                    ? `+${e.effect_minutes} min`
                    : "Service closed"}{" "}
                  · {stamp(e.valid_from)}
                </div>
                <div className="event-meta">
                  Source: {e.source_reference} · Incident: {e.correlation_key}
                </div>
                {e.review_overdue && (
                  <p className="warning-text">
                    Review overdue · estimate may be stale
                  </p>
                )}
                {e.source_kind !== "provider" &&
                  e.lifecycle_status === "active" && (
                    <button
                      className="text-button"
                      disabled={busy}
                      onClick={async () => {
                        const reason = window.prompt(
                          "Reason for withdrawing this report (at least 3 characters)",
                        );
                        if (!reason || reason.trim().length < 3) return;
                        const {
                          id,
                          version,
                          reported_by,
                          received_at,
                          review_overdue,
                          ...input
                        } = e;
                        try {
                          await mutate(`/events/${id}/revisions`, {
                            mutation_id: intent(),
                            expected_snapshot: bundle.state.snapshot,
                            expected_version: version,
                            event: {
                              ...input,
                              lifecycle_status: "withdrawn",
                              reason,
                            },
                          });
                        } catch {}
                      }}
                    >
                      Withdraw report
                    </button>
                  )}
              </article>
            ))}
            {!filtered.length && (
              <div className="empty-state">
                <ShieldCheck size={30} />
                <h3>No reports in this view</h3>
                <p>Add a manager report or apply a demo scenario.</p>
              </div>
            )}
          </div>
        </section>
        <section className="card">
          <div className="section-title">
            <h2>Manager review</h2>
            <span className="count-chip">{bundle.plans.length} plans</span>
          </div>
          {!bundle.plans.length ? (
            <div className="empty-state">
              <Package size={30} />
              <h3>A saved plan starts the story</h3>
              <p>
                Save an itinerary in the planner, then apply a disruption to
                review alternatives.
              </p>
            </div>
          ) : (
            <div className="plans-list">
              {bundle.plans.map((p) => (
                <button
                  key={p.plan_id}
                  className={`plan-row ${review?.plan.plan_id === p.plan_id ? "selected" : ""}`}
                  onClick={() => open(p)}
                >
                  <div>
                    <strong>{p.name}</strong>
                    <small>
                      {p.selected_projection
                        ? stamp(p.selected_projection.arrival_at)
                        : "Current itinerary unavailable"}
                    </small>
                  </div>
                  <span
                    className={`badge ${p.status === "stable" ? "green" : "amber"}`}
                  >
                    {p.status.replaceAll("_", " ")}
                  </span>
                  <ChevronRight size={15} />
                </button>
              ))}
            </div>
          )}
          {review && (
            <div className="plan-detail">
              <h3>{review.plan.name}</h3>
              {stale && (
                <div className="alert error">
                  This plan changed. Review the latest state.
                  <button onClick={() => current && open(current)}>
                    Refresh
                  </button>
                </div>
              )}
              <div className="comparison">
                <div>
                  <small>ORIGINAL ETA</small>
                  <strong>
                    {stamp(review.plan.selected_itinerary.arrival_at)}
                  </strong>
                </div>
                <ArrowRight size={17} />
                <div>
                  <small>CURRENT PROJECTION</small>
                  <strong>
                    {review.plan.selected_projection
                      ? stamp(review.plan.selected_projection.arrival_at)
                      : "Unavailable"}
                  </strong>
                </div>
              </div>
              {review.plan.review_reasons.map((r, i) => (
                <p className="warning-text" key={i}>
                  {r}
                </p>
              ))}
              <label>
                Suggested alternative
                <select
                  value={alternative}
                  onChange={(e) => setAlternative(e.target.value)}
                >
                  <option value="">No alternative selected</option>
                  {review.plan.alternative_recommendations.map((r) => (
                    <option key={r.id} value={r.id}>
                      {duration(r.total_minutes)} · {stamp(r.arrival_at)}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Decision reason
                <textarea
                  value={reason}
                  minLength={3}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder="Explain why this is the right decision…"
                />
              </label>
              <div className="actions wrap">
                <button
                  className="button primary"
                  disabled={
                    busy ||
                    stale ||
                    !alternative ||
                    reason.trim().length < 3 ||
                    review.plan.status === "outside_demo_scope"
                  }
                  onClick={() => void decide("accept_route")}
                >
                  Accept alternative
                </button>
                <button
                  className="button"
                  disabled={
                    busy ||
                    stale ||
                    !review.plan.selected_projection ||
                    reason.trim().length < 3
                  }
                  onClick={() => void decide("keep_selected")}
                >
                  Keep current
                </button>
                <button
                  className="text-button"
                  disabled={
                    busy ||
                    stale ||
                    reason.trim().length < 3 ||
                    review.plan.status === "outside_demo_scope"
                  }
                  onClick={() => void decide("defer")}
                >
                  Defer
                </button>
              </div>
              <h4>Decision history</h4>
              {history.map((d) => (
                <details className="history-row" key={d.id}>
                  <summary>
                    <ShieldCheck size={14} />
                    {d.action.replaceAll("_", " ")} · {d.actor}
                    <small>{stamp(d.decided_at)}</small>
                  </summary>
                  <p>{d.reason}</p>
                  <pre>{JSON.stringify(d.review_evidence, null, 2)}</pre>
                </details>
              ))}
              {!history.length && (
                <p className="muted">No decisions recorded yet.</p>
              )}
            </div>
          )}
        </section>
      </div>
      <div className="scenario-strip">
        <Clock size={18} />
        <div>
          <strong>Demo clock controls</strong>
          <small>
            Advance time to see how booked departures and cutoffs behave.
          </small>
        </div>
        <button
          className="button"
          disabled={busy || bundle.state.mode !== "demo"}
          onClick={async () => {
            try {
              await mutate("/demo/clock", {
                mutation_id: intent(),
                expected_snapshot: bundle.state.snapshot,
                target_clock: DateTime.fromISO(bundle.state.simulation_clock)
                  .plus({ hours: 1 })
                  .toUTC()
                  .toISO({ suppressMilliseconds: true }),
              });
            } catch {}
          }}
        >
          Advance 1 hour
        </button>
        <button
          className="text-button danger"
          disabled={busy || bundle.state.mode !== "demo"}
          onClick={async () => {
            if (!window.confirm("Reset all demo plans, events and decisions?"))
              return;
            try {
              await mutate("/demo/reset", { confirm: "RESET_DEMO" });
              setReview(undefined);
            } catch {}
          }}
        >
          Reset demo
        </button>
      </div>
    </>
  );
}
export function EventForm({
  bundle,
  busy,
  mutate,
  onDone,
}: {
  bundle: Bundle;
  busy: boolean;
  mutate: Mutate;
  onDone: () => void;
}) {
  const [kind, setKind] = useState("lane"),
    [target, setTarget] = useState(bundle.network.lanes[0].id),
    [category, setCategory] = useState("operational"),
    [effect, setEffect] = useState("additional_travel_minutes"),
    [minutes, setMinutes] = useState(60),
    [reason, setReason] = useState(""),
    [key, setKey] = useState(`incident-${intent().slice(0, 8)}`),
    [accepted, setAccepted] = useState(true),
    [nodeMode, setNodeMode] = useState("road");
  const fmt = (t: string) =>
    DateTime.fromISO(t).toUTC().toFormat("yyyy-MM-dd'T'HH:mm");
  const [start, setStart] = useState(fmt(bundle.state.simulation_clock)),
    [end, setEnd] = useState(
      fmt(
        DateTime.fromISO(bundle.state.simulation_clock)
          .plus({ days: 1 })
          .toISO()!,
      ),
    );
  const [expected] = useState(bundle.state.snapshot);
  return (
    <form
      className="form-grid"
      onSubmit={async (e) => {
        e.preventDefault();
        try {
          await mutate("/events", {
            mutation_id: intent(),
            expected_snapshot: expected,
            event: {
              type: category,
              source_kind: "manager",
              external_id: intent(),
              source_reference: "Operations manager report",
              observed_at: bundle.state.simulation_clock,
              valid_from: DateTime.fromISO(start, { zone: "UTC" }).toISO(),
              valid_until: DateTime.fromISO(end, { zone: "UTC" }).toISO(),
              review_due_at: null,
              target_kind: kind,
              target_id: target,
              mode:
                kind === "lane"
                  ? bundle.network.lanes.find((l) => l.id === target)?.mode
                  : nodeMode,
              effect_type: effect,
              effect_minutes: effect.startsWith("additional") ? minutes : null,
              verification_status: accepted ? "accepted" : "pending",
              lifecycle_status: "active",
              correlation_key: key.trim(),
              reason: reason.trim(),
              applies_to_departure_at: null,
              observation_id: null,
            },
          });
          onDone();
        } catch {}
      }}
    >
      <div className="two-cols">
        <label>
          Category
          <select
            value={category}
            onChange={(e) => setCategory(e.target.value)}
          >
            {["operational", "traffic", "weather", "political"].map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        </label>
        <label>
          Target type
          <select
            value={kind}
            onChange={(e) => {
              setKind(e.target.value);
              setTarget(
                e.target.value === "node"
                  ? bundle.network.nodes[0].id
                  : bundle.network.lanes[0].id,
              );
              setEffect(
                e.target.value === "node"
                  ? "additional_handling_minutes"
                  : "additional_travel_minutes",
              );
            }}
          >
            <option value="lane">Transport lane</option>
            <option value="node">Facility</option>
          </select>
        </label>
      </div>
      <label>
        Affected target
        <select value={target} onChange={(e) => setTarget(e.target.value)}>
          {(kind === "node" ? bundle.network.nodes : bundle.network.lanes).map(
            (n) => (
              <option key={n.id} value={n.id}>
                {n.id}
              </option>
            ),
          )}
        </select>
      </label>
      <div className="two-cols">
        <label>
          Effect
          <select value={effect} onChange={(e) => setEffect(e.target.value)}>
            {(kind === "node"
              ? ["additional_handling_minutes"]
              : [
                  "additional_travel_minutes",
                  "closure",
                  "departure_cancellation",
                ]
            ).map((t) => (
              <option key={t} value={t}>
                {t.replaceAll("_", " ")}
              </option>
            ))}
          </select>
        </label>
        {effect.startsWith("additional") && (
          <label>
            Additional minutes
            <input
              type="number"
              min={0}
              required
              value={minutes}
              onChange={(e) => setMinutes(Number(e.target.value))}
            />
          </label>
        )}
        {kind === "node" && (
          <label>
            Outgoing mode
            <select
              value={nodeMode}
              onChange={(e) => setNodeMode(e.target.value)}
            >
              <option>road</option>
              <option>air</option>
            </select>
          </label>
        )}
      </div>
      <div className="two-cols">
        <label>
          Valid from (UTC)
          <input
            type="datetime-local"
            required
            value={start}
            onChange={(e) => setStart(e.target.value)}
          />
        </label>
        <label>
          Valid until (UTC)
          <input
            type="datetime-local"
            required
            min={start}
            value={end}
            onChange={(e) => setEnd(e.target.value)}
          />
        </label>
      </div>
      <label>
        Incident / correlation key
        <input
          required
          list="incidents"
          value={key}
          onChange={(e) => setKey(e.target.value)}
        />
        <datalist id="incidents">
          {[...new Set(bundle.events.map((e) => e.correlation_key))].map(
            (k) => (
              <option key={k}>{k}</option>
            ),
          )}
        </datalist>
        <small>
          Use the same key for reports about the same incident to avoid adding
          delays twice.
        </small>
      </label>
      <label>
        Reason
        <textarea
          required
          minLength={3}
          maxLength={1000}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="What happened, and what is the expected impact?"
        />
      </label>
      <label className="checkbox">
        <input
          type="checkbox"
          checked={accepted}
          onChange={(e) => setAccepted(e.target.checked)}
        />
        Confirmed: apply to routing immediately
      </label>
      <button
        className="button primary wide"
        disabled={busy || reason.trim().length < 3}
      >
        Save disruption <ArrowRight size={15} />
      </button>
    </form>
  );
}
export function DataView({
  bundle,
  busy,
  mutate,
}: {
  bundle: Bundle;
  busy: boolean;
  mutate: Mutate;
}) {
  return (
    <>
      <div className="card">
        <div className="section-title">
          <h2>Source data</h2>
          <span className="badge green">
            {bundle.data.import_complete
              ? "Import complete"
              : "Import incomplete"}
          </span>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Source file</th>
                <th>Records</th>
                <th>Coverage</th>
                <th>Import notes</th>
              </tr>
            </thead>
            <tbody>
              {bundle.data.sources.map((s) => (
                <tr key={s.filename}>
                  <td>
                    <Database size={14} /> {s.filename}
                  </td>
                  <td>{s.rows?.toLocaleString() || "—"}</td>
                  <td>
                    {s.date_from || "—"} → {s.date_to || "—"}
                  </td>
                  <td>{s.issues.join("; ") || "No reported issues"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <div className="review-grid">
        <section className="card padded">
          <span className="eyebrow">REAL SOURCE EXAMPLE</span>
          <h2>Hamburg trailer capacity</h2>
          {bundle.data.capacity_example ? (
            <>
              <p className="muted">
                {bundle.data.capacity_example.date} ·{" "}
                {bundle.data.capacity_example.relation}
              </p>
              <div className="capacity-grid">
                <div>
                  <strong>
                    {bundle.data.capacity_example.planned_trailers}
                  </strong>
                  <small>Planned trailers</small>
                </div>
                <div>
                  <strong>
                    {bundle.data.capacity_example.needed_trailers}
                  </strong>
                  <small>Needed trailers</small>
                </div>
                <div>
                  <strong>{bundle.data.capacity_example.special_trips}</strong>
                  <small>Special trips</small>
                </div>
              </div>
              <p>
                {bundle.data.capacity_example.loading_metres} loading metres ·{" "}
                {bundle.data.capacity_example.trailer_capacity_metres} metres
                per trailer
              </p>
            </>
          ) : (
            <p>Capacity example unavailable.</p>
          )}
          <p className="muted">
            Capacity records provide operational context; they are not
            historical transit-time labels.
          </p>
        </section>
        <section className="card padded">
          <span className="eyebrow">MODEL TRANSPARENCY</span>
          <h2>What the estimate includes</h2>
          {bundle.data.assumptions.map((a, i) => (
            <p className="assumption" key={i}>
              <Check size={14} />
              {a}
            </p>
          ))}
          <p className="muted">
            Sample schedules, assumed movement times and approximate facility
            coordinates. No live GPS or door-to-door prediction. Manager
            identity is a prototype identity.
          </p>
        </section>
      </div>
      <section className="card">
        <div className="section-title">
          <h2>Provider integrations</h2>
          <button
            className="button"
            disabled={busy || bundle.state.mode === "demo"}
            onClick={async () => {
              try {
                await mutate("/integrations/refresh", {
                  mutation_id: intent(),
                  expected_snapshot: bundle.state.snapshot,
                });
              } catch {}
            }}
          >
            <RefreshCw size={14} />
            Refresh live sources
          </button>
        </div>
        <div className="provider-grid">
          {bundle.integrations.providers.map((p) => (
            <div className="provider-card" key={p.name}>
              <div>
                <strong>{p.name.replaceAll("_", " ")}</strong>
                <span
                  className={`badge ${p.status === "ok" ? "green" : "amber"}`}
                >
                  {p.status.replaceAll("_", " ")}
                </span>
              </div>
              <p>
                {p.error_message ||
                  `${p.mode === "demo" ? "Disabled in deterministic demo" : "Provider status from backend"}`}
              </p>
              <small>
                {p.last_successful_poll_at
                  ? `Last success: ${stamp(p.last_successful_poll_at)}`
                  : "No successful poll recorded"}
              </small>
            </div>
          ))}
        </div>
        <details className="observations">
          <summary>
            Normalized observations ({bundle.observations.length})
          </summary>
          {bundle.observations.map((o) => (
            <div key={o.id}>
              <strong>
                {o.provider} · {o.target_id} · {o.stale ? "stale" : "reported"}
              </strong>
              <p>
                {o.attribution} · {stamp(o.fetched_at)}
              </p>
              <pre>{JSON.stringify(o.metrics, null, 2)}</pre>
            </div>
          ))}
        </details>
      </section>
    </>
  );
}
