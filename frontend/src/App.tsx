import {
  useCallback,
  useEffect,
  useRef,
  useState,
  lazy,
  Suspense,
} from "react";
import {
  Activity,
  ArrowRight,
  ArrowUpRight,
  Check,
  ChevronRight,
  Clock,
  Database,
  GitBranch,
  LayoutDashboard,
  Loader2,
  MapPin,
  Plus,
  Printer,
  RefreshCw,
  Route as RouteIcon,
  ShieldCheck,
  Truck,
  Zap,
  X,
  Save,
  AlertTriangle,
  PanelLeftClose,
  Maximize2,
  Minimize2,
  Play,
} from "lucide-react";
import { DateTime } from "luxon";
import {
  api,
  intent,
  duration,
  stamp,
  type Model,
  type Route,
  type State,
  type Plan,
} from "./api";
import NetworkMap from "./NetworkMap";
import ScenarioLab from "./ScenarioLab";
import { DataView, ReviewView, EventForm, Timeline } from "./Panels";
const Schedules = lazy(() => import("./Schedules"));
type Page = "planner" | "network" | "review" | "data";
export type Bundle = {
  state: State;
  network: Model<"Network">;
  events: Model<"Event">[];
  plans: Plan[];
  geometry: Model<"LaneGeometry">[];
  data: Model<"DataSummary">;
  integrations: Model<"Integrations">;
  observations: Model<"Observation">[];
};
export default function App() {
  const [presenting, setPresenting] = useState(false);
  const [page, setPage] = useState<Page>("planner"),
    [bundle, setBundle] = useState<Bundle>(),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [busy, setBusy] = useState(false),
    [online, setOnline] = useState(false);
  const [result, setResult] = useState<Model<"SearchResponse">>(),
    [selected, setSelected] = useState(""),
    [searching, setSearching] = useState(false),
    [report, setReport] = useState(false),
    [save, setSave] = useState(false),
    [name, setName] = useState("Frankfurt → Kempten");
  const [origin, setOrigin] = useState("FRA_HUB"),
    [destination, setDestination] = useState("KEM_BRANCH"),
    [ready, setReady] = useState("2026-09-21T10:00"),
    [profile, setProfile] = useState("mixed"),
    [deadline, setDeadline] = useState("");
  const stateRef = useRef<State | undefined>(undefined),
    activeSearch = useRef<Model<"SearchRequest"> | undefined>(undefined),
    requestId = useRef(0),
    abort = useRef<AbortController | undefined>(undefined),
    refreshId = useRef(0);
  const runSearch = useCallback(async (req: Model<"SearchRequest">) => {
    abort.current?.abort();
    const control = new AbortController();
    abort.current = control;
    const id = ++requestId.current;
    setSearching(true);
    try {
      const value = await api<Model<"SearchResponse">>(
        "/routes/search",
        req,
        "POST",
        control.signal,
      );
      if (id !== requestId.current) return;
      setResult(value);
      setSelected((old) =>
        value.routes.some((r) => r.id === old)
          ? old
          : value.routes[0]?.id || "",
      );
      setError("");
    } catch (e) {
      if (!control.signal.aborted) {
        setError((e as Error).message);
        setResult(undefined);
      }
    } finally {
      if (id === requestId.current) setSearching(false);
    }
  }, []);
  const refresh = useCallback(
    async (force = false) => {
      const id = ++refreshId.current;
      try {
        const state = await api<State>("/state");
        if (
          !force &&
          JSON.stringify(state) === JSON.stringify(stateRef.current)
        ) {
          setOnline(true);
          return;
        }
        const [
          network,
          events,
          plans,
          geometry,
          data,
          integrations,
          observations,
        ] = await Promise.all([
          api<Model<"Network">>("/network"),
          api<Model<"EventList">>("/events"),
          api<Model<"PlanList">>("/plans"),
          api<Model<"MapGeometry">>("/map/geometry"),
          api<Model<"DataSummary">>("/data-summary"),
          api<Model<"Integrations">>("/integrations"),
          api<Model<"ObservationList">>("/integrations/observations"),
        ]);
        if (id !== refreshId.current) return;
        const prior = stateRef.current;
        stateRef.current = state;
        setBundle({
          state,
          network,
          events: events.events,
          plans: plans.plans,
          geometry: geometry.lanes,
          data,
          integrations,
          observations: observations.observations,
        });
        setOnline(true);
        if (!prior && state.mode === "live")
          setReady(
            DateTime.fromISO(state.simulation_clock)
              .setZone("Europe/Berlin")
              .plus({ hours: 1 })
              .toFormat("yyyy-MM-dd'T'HH:mm"),
          );
        if (
          prior &&
          JSON.stringify(prior.snapshot) !== JSON.stringify(state.snapshot) &&
          activeSearch.current
        )
          void runSearch(activeSearch.current);
      } catch (e) {
        if (id === refreshId.current) {
          setOnline(false);
          setError(`Backend unavailable. ${(e as Error).message}`);
        }
      }
    },
    [runSearch],
  );
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      if (!document.hidden) await refresh();
      if (!cancelled) timer = setTimeout(poll, 2000);
    };
    void poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
      abort.current?.abort();
    };
  }, [refresh]);
  const mutate = async (path: string, body: unknown, method = "POST") => {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const response = await api<any>(path, body, method);
      await refresh(true);
      setNotice("Workspace updated successfully");
      return response;
    } catch (e) {
      setError((e as Error).message);
      throw e;
    } finally {
      setBusy(false);
    }
  };
  const snapshot = bundle?.state.snapshot;
  const submitSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (!bundle) return;
    const zone = bundle.network.nodes.find((n) => n.id === origin)!.timezone;
    const local = DateTime.fromISO(ready, { zone });
    if (
      !local.isValid ||
      local.toFormat("yyyy-MM-dd'T'HH:mm") !== ready ||
      local.getPossibleOffsets().length > 1
    ) {
      setError(
        "Choose an unambiguous local time; this value crosses a daylight-saving change.",
      );
      return;
    }
    let end: string | null = null;
    if (deadline) {
      const destZone = bundle.network.nodes.find(
        (n) => n.id === destination,
      )!.timezone;
      const dt = DateTime.fromISO(deadline, { zone: destZone });
      if (
        !dt.isValid ||
        dt.getPossibleOffsets().length > 1 ||
        dt.toFormat("yyyy-MM-dd'T'HH:mm") !== deadline
      ) {
        setError("Choose a valid, unambiguous destination deadline.");
        return;
      }
      end = dt.toUTC().toISO({ suppressMilliseconds: true });
    }
    const req: Model<"SearchRequest"> = {
      origin_id: origin,
      destination_id: destination,
      ready_at: local.toUTC().toISO({ suppressMilliseconds: true })!,
      service_profile_id: profile,
      max_results: 3,
      arrival_deadline: end,
    };
    activeSearch.current = req;
    void runSearch(req);
  };
  const route = result?.routes.find((r) => r.id === selected),
    zone = bundle?.network.nodes.find((n) => n.id === destination)?.timezone;
  const reviewCount =
    bundle?.plans.filter(
      (p) => p.status === "review_required" || p.status === "blocked",
    ).length || 0;
  const title = {
    planner: "Route planner",
    network: "Network & schedules",
    review: "Disruptions & review",
    data: "Data & assumptions",
  }[page];
  return (
    <div className={`workspace ${presenting ? "presentation-mode" : ""}`}>
      <aside className="sidebar">
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            setPage("planner");
          }}
        >
          <span className="brand-symbol">
            <RouteIcon size={22} />
          </span>
          transit<span className="brand-period">.</span>
        </a>
        <div className="workspace-tag">
          <span className="square-logo">D</span>
          <div>
            European operations<small>Planning workspace</small>
          </div>
          <ChevronRight size={14} />
        </div>
        <div className="nav-heading">WORKSPACE</div>
        <nav>
          {(
            [
              { id: "planner", label: "Route planner", icon: LayoutDashboard },
              { id: "network", label: "Network & schedules", icon: GitBranch },
              { id: "review", label: "Disruptions & review", icon: Activity },
              { id: "data", label: "Data & assumptions", icon: Database },
            ] as const
          ).map((item) => (
            <button
              key={item.id}
              className={page === item.id ? "nav-link active" : "nav-link"}
              onClick={() => setPage(item.id)}
            >
              <item.icon size={18} />
              {item.label}
              {item.id === "review" && reviewCount > 0 && (
                <span className="nav-count">{reviewCount}</span>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="prototype-card">
            <Zap size={17} />
            <strong>Built for what happens next.</strong>
            <p>
              Realistic transit times.
              <br />
              Decisions you can explain.
            </p>
            <span>
              HACKATHON PROTOTYPE <ArrowUpRight size={13} />
            </span>
          </div>
          <div className="profile">
            <div className="avatar">DM</div>
            <div>
              Demo manager<small>Operations team</small>
            </div>
            <ShieldCheck size={17} />
          </div>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <div className="breadcrumb">
            Workspace <ChevronRight size={13} />
            <strong>{title}</strong>
          </div>
          <div className="topbar-right">
            <button className="presentation-toggle" onClick={() => setPresenting(!presenting)} aria-pressed={presenting} title="Toggle presentation layout">
              {presenting ? <Minimize2 size={15}/> : <Maximize2 size={15}/>}
              <span>{presenting ? "Exit presentation" : "Present"}</span>
            </button>
            <span className={`connection ${online ? "" : "offline"}`}>
              <i />
              {online ? "Backend connected" : "Connecting to backend"}
            </span>
            <span className="mode">
              {bundle?.state.mode || "demo"} environment
            </span>
            <div className="avatar small">DM</div>
          </div>
        </header>
        <main>
          <div className="page-heading">
            <div>
              <div className="eyebrow">
                OPERATIONS /{" "}
                {page === "planner" ? "PLANNING" : page.toUpperCase()}
              </div>
              <h1>
                {title}
                <span className="beta">BETA</span>
              </h1>
              <p>
                {page === "planner"
                  ? "Every connection. Every delay. One clear delivery promise."
                  : page === "review"
                    ? "Stay ahead of disruptions. Keep people in control."
                    : page === "network"
                      ? "The service network behind every delivery promise."
                      : "Know what powers your estimates—and where assumptions begin."}
              </p>
            </div>
            <div className="clock-card">
              <Clock size={16} />
              <div>
                <small>EVALUATION CLOCK</small>
                <strong>
                  {bundle
                    ? stamp(bundle.state.simulation_clock)
                    : "Connecting…"}
                </strong>
              </div>
              <button
                className="icon-button"
                title="Refresh workspace"
                onClick={() => void refresh(true)}
              >
                <RefreshCw size={15} />
              </button>
            </div>
          </div>
          {error && (
            <div className="alert error">
              <AlertTriangle size={18} />
              <span>{error}</span>
              <button onClick={() => setError("")} aria-label="Dismiss error">
                <X size={16} />
              </button>
            </div>
          )}
          {notice && (
            <div className="toast" role="status">
              <Check size={16} />
              {notice}
              <button
                onClick={() => setNotice("")}
                aria-label="Dismiss notification"
              >
                <X size={14} />
              </button>
            </div>
          )}
          {!bundle ? (
            <div className="initial-state">
              <Loader2 className="spin" />
              <h2>Connecting your workspace</h2>
              <p>
                Start the Python backend on port 8000 to load the service
                network.
              </p>
              <button className="button" onClick={() => void refresh(true)}>
                Try again
              </button>
            </div>
          ) : (
            <>
              {page === "planner" && (
                <>
                  <section className="mission-hero">
                    <div className="hero-copy">
                      <span className="hero-kicker"><span className="live-dot"/> TRANSIT INTELLIGENCE</span>
                      <h2>A changing world.<br/><em>A clearer arrival.</em></h2>
                      <p>Turn network conditions into explainable delivery promises. Explore the route, simulate the unexpected, and put your team in control.</p>
                      <div className="hero-actions">
                        <button className="button hero-launch" disabled={searching || !online} onClick={() => {
                          const at = DateTime.fromISO(bundle.state.simulation_clock).plus({hours: 1}).toUTC().toISO({suppressMilliseconds: true})!;
                          const req: Model<"SearchRequest"> = {origin_id: "FRA_HUB", destination_id: "KEM_BRANCH", ready_at: at, service_profile_id: "mixed", max_results: 3, arrival_deadline: null};
                          setOrigin(req.origin_id); setDestination(req.destination_id); setProfile("mixed"); setDeadline("");
                          setReady(DateTime.fromISO(at).setZone("Europe/Berlin").toFormat("yyyy-MM-dd'T'HH:mm"));
                          activeSearch.current = req; void runSearch(req);
                          document.querySelector(".search-card")?.scrollIntoView({behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth", block: "start"});
                        }}><Play size={15} fill="currentColor"/> Explore Frankfurt → Kempten <ArrowRight size={16}/></button>
                        <span>Schedules → Disruptions → Human decision</span>
                      </div>
                    </div>
                    <div className="hero-art" aria-hidden="true"><div className="orbit orbit-one"/><div className="orbit orbit-two"/><div className="hero-route-line"/><span className="hero-station station-a">FRA <i/></span><span className="hero-station station-b"><i/> MUC</span><span className="hero-station station-c"><i/> KEM</span><div className="hero-signal"><Activity size={18}/><span>Every leg.<strong>Accounted for.</strong></span></div></div>
                  </section>
                  <div className="stats-grid">
                    <Stat
                      icon={<GitBranch size={19} />}
                      label="Network coverage"
                      value={`${bundle.network.nodes.length} facilities`}
                      sub={`${new Set(bundle.network.nodes.map((n) => n.country)).size} countries connected`}
                    />
                    <Stat
                      icon={<RouteIcon size={19} />}
                      label="Scheduled connections"
                      value={`${bundle.network.lanes.filter((l) => l.active).length} active lanes`}
                      sub="Road & air services"
                    />
                    <Stat
                      icon={<Activity size={19} />}
                      label="Active disruptions"
                      value={String(
                        bundle.events.filter(
                          (e) => e.lifecycle_status === "active",
                        ).length,
                      ).padStart(2, "0")}
                      sub="Reported network conditions"
                    />
                    <Stat
                      icon={<ShieldCheck size={19} />}
                      label="Saved transport plans"
                      value={String(bundle.plans.length).padStart(2, "0")}
                      sub={
                        reviewCount
                          ? `${reviewCount} require your review`
                          : "Your planning workspace"
                      }
                    />
                  </div>
                  <section className="card search-card">
                    <div className="section-title">
                      <div>
                        <span className="section-number">01</span>
                        <h2>Plan a shipment</h2>
                      </div>
                      <span className="muted">
                        Branch to branch <span className="tiny-dot" /> Sample
                        schedules
                      </span>
                    </div>
                    <form onSubmit={submitSearch}>
                      <div className="search-fields">
                        <label>
                          Origin
                          <select
                            value={origin}
                            onChange={(e) => {
                              setOrigin(e.target.value);
                              if (e.target.value === destination) {
                                setDestination(bundle.network.nodes.find(n => n.active && n.id !== e.target.value)!.id);
                              }
                            }}
                          >
                            {bundle.network.nodes
                              .filter((n) => n.active)
                              .map((n) => (
                                <option key={n.id} value={n.id}>
                                  {n.name}
                                </option>
                              ))}
                          </select>
                        </label>
                        <div className="direction">
                          <ArrowRight size={18} />
                        </div>
                        <label>
                          Destination
                          <select
                            value={destination}
                            onChange={(e) => setDestination(e.target.value)}
                          >
                            {bundle.network.nodes
                              .filter((n) => n.active && n.id !== origin)
                              .map((n) => (
                                <option key={n.id} value={n.id}>
                                  {n.name}
                                </option>
                              ))}
                          </select>
                        </label>
                        <label>
                          Ready at{" "}
                          <small>
                            {
                              bundle.network.nodes.find((n) => n.id === origin)
                                ?.timezone
                            }
                          </small>
                          <input
                            type="datetime-local"
                            required
                            value={ready}
                            onChange={(e) => setReady(e.target.value)}
                          />
                        </label>
                        <label>
                          Service profile
                          <select
                            value={profile}
                            onChange={(e) => setProfile(e.target.value)}
                          >
                            <option value="mixed">Road + air</option>
                            <option value="road_only">Road only</option>
                          </select>
                        </label>
                        <button
                          className="button primary calculate"
                          disabled={searching || !online}
                        >
                          <RouteIcon size={17} />
                          {searching ? "Calculating…" : "Find routes"}
                          <ArrowRight size={17} />
                        </button>
                      </div>
                      <details className="advanced">
                        <summary>Optional arrival deadline</summary>
                        <label>
                          Deadline in destination timezone
                          <input
                            type="datetime-local"
                            value={deadline}
                            onChange={(e) => setDeadline(e.target.value)}
                          />
                        </label>
                      </details>
                    </form>
                  </section>
                  <ScenarioLab key={`${origin}|${destination}|${ready}|${profile}|${deadline}`} bundle={bundle} result={result} selected={route} request={activeSearch.current} busy={busy || searching} mutate={mutate} onReport={() => setReport(true)} onReview={() => setPage("review")} />
                  <div className="planner-grid">
                    <section className="card route-panel">
                      <div className="section-title">
                        <div>
                          <span className="section-number">02</span>
                          <h2>Route options</h2>
                        </div>
                        <span className="count-chip">
                          {result?.routes.length || 0} found
                        </span>
                      </div>
                      <div className="route-list">
                        {searching && <div className="loading-line" />}
                        {result?.routes.map((r, i) => (
                          <button
                            key={r.id}
                            className={`route-card ${selected === r.id ? "selected" : ""}`}
                            aria-pressed={selected === r.id}
                            style={{animationDelay: `${i * 65}ms`}}
                            onClick={() => setSelected(r.id)}
                          >
                            <div className="route-top">
                              <span className="route-label">
                                {i === 0 ? (
                                  <>
                                    <Zap size={12} /> Earliest arrival
                                  </>
                                ) : (
                                  <>Alternative {i}</>
                                )}
                              </span>
                              <span className="radio">
                                {selected === r.id && <Check size={11} />}
                              </span>
                            </div>
                            <div className="route-time">
                              {duration(r.total_minutes)}
                              <span>
                                {r.transfer_count} transfer
                                {r.transfer_count === 1 ? "" : "s"}
                              </span>
                            </div>
                            <div className="route-path">
                              {r.lane_ids.map((id, j) => {
                                const l = bundle.network.lanes.find(
                                  (l) => l.id === id,
                                )!;
                                return (
                                  <span key={id}>
                                    {j === 0 && (
                                      <>
                                        {l.from_node_id.split("_")[0]}{" "}
                                        <ChevronRight size={11} />
                                      </>
                                    )}
                                    {l.to_node_id.split("_")[0]}
                                    {j < r.lane_ids.length - 1 && (
                                      <ChevronRight size={11} />
                                    )}
                                  </span>
                                );
                              })}
                            </div>
                            <div className="route-relative"><span style={{width: `${Math.max(8, (result.routes[0].total_minutes / Math.max(1, r.total_minutes)) * 100)}%`}}/></div>
                            <div className="route-arrival">
                              <Clock size={12} />
                              <span>Arrives {stamp(r.arrival_at, zone)}</span>
                            </div>
                          </button>
                        ))}
                        {!result && !searching && (
                          <div className="empty-state">
                            <RouteIcon size={32} />
                            <h3>Find your next connection</h3>
                            <p>
                              Enter a route above to compare scheduled services
                              and realistic arrival times.
                            </p>
                          </div>
                        )}
                        {result?.routes.length === 0 && (
                          <div className="empty-state">
                            <AlertTriangle />
                            <h3>No feasible route</h3>
                            <p>
                              {result.diagnostics
                                .map((d) => d.message)
                                .join(" ") ||
                                "Try another ready time or service profile."}
                            </p>
                          </div>
                        )}
                      </div>
                      <div className="route-note">
                        <ShieldCheck size={16} />
                        <span>
                          Calculated from schedules, handling, cutoffs and
                          reported conditions.
                        </span>
                      </div>
                    </section>
                    <section className="card map-panel">
                      <NetworkMap
                        network={bundle.network}
                        routes={result?.routes || []}
                        selected={route}
                        geometries={bundle.geometry}
                        events={bundle.events}
                        onSelect={setSelected}
                      />
                      <div className="map-footer">
                        <div>
                          <MapPin size={15} />
                          <strong>
                            {route
                              ? `${route.lane_ids.length} legs in selected route`
                              : "Your European service network"}
                          </strong>
                        </div>
                        <span>Pickup & final delivery excluded</span>
                      </div>
                    </section>
                  </div>
                  <section className="card timeline-card">
                    <div className="section-title">
                      <div>
                        <span className="section-number">03</span>
                        <h2>Journey breakdown</h2>
                        {route && (
                          <span className="muted">
                            {duration(route.total_minutes)} total
                          </span>
                        )}
                      </div>
                      <div className="actions">
                        <button
                          className="button"
                          disabled={!route}
                          onClick={() => window.print()}
                        >
                          <Printer size={15} />
                          Print
                        </button>
                        <button
                          className="button dark"
                          disabled={!route || !online || searching}
                          onClick={() => setSave(true)}
                        >
                          <Save size={15} />
                          Save plan
                        </button>
                      </div>
                    </div>
                    {route ? (
                      <Timeline route={route} network={bundle.network} />
                    ) : (
                      <div className="timeline-placeholder">
                        <span />
                        <span />
                        <span />
                        <p>
                          Select a route to explore its step-by-step timing.
                        </p>
                      </div>
                    )}
                  </section>
                  <div className="scenario-strip">
                    <div className="scenario-icon">
                      <Zap size={19} />
                    </div>
                    <div>
                      <strong>See how conditions change a promise</strong>
                      <small>
                        {bundle.state.mode === "demo"
                          ? "Apply a simulated disruption and compare the updated routes."
                          : "Live conditions are sourced from configured providers."}
                      </small>
                    </div>
                    <button
                      className="button"
                      onClick={() => setPage("review")}
                    >
                      Open control room <ArrowRight size={15} />
                    </button>
                  </div>
                </>
              )}
              {page === "network" && (
                <Suspense fallback={<p>Loading schedule editor…</p>}>
                  <Schedules bundle={bundle} busy={busy} mutate={mutate} />
                </Suspense>
              )}
              {page === "review" && (
                <ReviewView
                  bundle={bundle}
                  busy={busy}
                  mutate={mutate}
                  onReport={() => setReport(true)}
                />
              )}
              {page === "data" && (
                <DataView bundle={bundle} busy={busy} mutate={mutate} />
              )}
              <footer>
                <span>TRANSIT / OPERATIONS INTELLIGENCE</span>
                <span>
                  Prototype · Assumed schedules · Explainable calculations
                </span>
                <button onClick={() => setPage("data")}>
                  View data provenance <ArrowUpRight size={12} />
                </button>
              </footer>
            </>
          )}
        </main>
      </div>
      {report && bundle && (
        <Modal title="Report a disruption" onClose={() => setReport(false)}>
          <EventForm
            bundle={bundle}
            busy={busy}
            mutate={mutate}
            onDone={() => setReport(false)}
          />
        </Modal>
      )}
      {save && route && result && (
        <Modal title="Save transport plan" onClose={() => setSave(false)}>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              try {
                await mutate("/plans", {
                  mutation_id: intent(),
                  expected_snapshot: result.snapshot,
                  search_id: result.search_id,
                  route_id: route.id,
                  name,
                });
                setSave(false);
              } catch {}
            }}
          >
            <p className="muted">
              Keep this itinerary under review as network conditions change.
            </p>
            <label>
              Plan name
              <input
                required
                maxLength={100}
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </label>
            <button className="button primary wide" disabled={busy}>
              Save {duration(route.total_minutes)} itinerary{" "}
              <ArrowRight size={16} />
            </button>
          </form>
        </Modal>
      )}
    </div>
  );
}
function Stat({
  icon,
  label,
  value,
  sub,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  sub: string;
}) {
  return (
    <div className="stat-card">
      <div className="stat-label">
        {label}
        <span>{icon}</span>
      </div>
      <strong>{value}</strong>
      <small>{sub}</small>
    </div>
  );
}
export function Modal({
  title,
  children,
  onClose,
}: {
  title: string;
  children: React.ReactNode;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    dialog.current?.showModal();
  }, []);
  return (
    <dialog
      ref={dialog}
      onCancel={onClose}
      onClick={(e) => {
        if (e.target === dialog.current) onClose();
      }}
    >
      <div className="modal-head">
        <h2>{title}</h2>
        <button
          className="icon-button"
          onClick={onClose}
          aria-label="Close dialog"
        >
          <X size={19} />
        </button>
      </div>
      {children}
    </dialog>
  );
}
