import { useRef, useState } from "react";
import { ArrowRight, CloudRain, Construction, Loader2, ShieldCheck, Timer, Truck, Zap } from "lucide-react";
import { api, duration, intent, stamp, type Model, type Route } from "./api";
import type { Bundle } from "./App";

export default function ScenarioLab({ bundle, result, selected, request, busy, mutate, onReport, onReview }: {
  bundle: Bundle; result?: Model<"SearchResponse">; selected?: Route; request?: Model<"SearchRequest">; busy: boolean;
  mutate: (path: string, body: unknown) => Promise<unknown>; onReport: () => void; onReview: () => void;
}) {
  const [pending, setPending] = useState("");
  const [comparison, setComparison] = useState<{ before: Route; after: Model<"SearchResponse">; label: string }>();
  const [error, setError] = useState("");
  const lock = useRef(false);
  async function apply(id: string, label: string) {
    if (!selected || !request || !result || lock.current || busy) return;
    lock.current = true;
    setPending(id); setError(""); setComparison(undefined);
    try {
      await mutate("/demo/presets", { mutation_id: intent(), expected_snapshot: result.snapshot, preset_id: id });
      const after = await api<Model<"SearchResponse">>("/routes/search", request);
      setComparison({ before: selected, after, label });
    } catch (e) { setError((e as Error).message); }
    finally { setPending(""); lock.current = false; }
  }
  const matching = comparison?.after.routes.find(r => r.lane_ids.join("|") === comparison.before.lane_ids.join("|"));
  const best = comparison?.after.routes[0];
  const saving = matching && best ? matching.total_minutes - best.total_minutes : 0;
  const current = comparison && JSON.stringify(comparison.after.snapshot) === JSON.stringify(bundle.state.snapshot);
  const zone = bundle.network.nodes.find(n => n.id === request?.destination_id)?.timezone;
  return <section className="scenario-lab">
    <div className="lab-heading"><div><span className="eyebrow"><Zap size={13} /> SCENARIO STUDIO</span><h2>Change the conditions. See the impact.</h2></div><span className="lab-badge">{bundle.state.mode === "demo" ? "Shared demo simulation" : "Live environment"}</span></div>
    <div className="scenario-choices">
      {[
        { id: "traffic_direct", label: "Heavy traffic", detail: "+180 min · direct corridor", icon: Truck },
        { id: "handling_munich", label: "Hub congestion", detail: "Handling delay · Munich", icon: Timer },
        { id: "closure_strasbourg", label: "Border closure", detail: "Blocked connection · Strasbourg", icon: Construction },
      ].map(({id,label,detail,icon: Icon}) => <button key={id} className={`scenario-choice ${pending === id ? "applying" : ""}`} disabled={!selected || busy || !!pending || bundle.state.mode !== "demo" || JSON.stringify(result?.snapshot) !== JSON.stringify(bundle.state.snapshot)} onClick={() => void apply(id,label)}><span className="scenario-glyph">{pending === id ? <Loader2 size={20} className="spin" /> : <Icon size={20} />}</span><span><strong>{label}</strong><small>{detail}</small></span><ArrowRight size={15} /></button>)}
      <button className="scenario-choice custom" onClick={onReport} disabled={busy || !!pending}><span className="scenario-glyph"><CloudRain size={20} /></span><span><strong>Weather or local intel</strong><small>Report with a reason & validity</small></span><ArrowRight size={15}/></button>
    </div>
    {!comparison && <p className="lab-hint">{pending ? "Applying the event and recalculating scheduled connections…" : selected ? "Presets update this demo network. Save a plan first to demonstrate manager approval; repeated presets do not stack." : "Find a route to unlock simulated disruptions. Weather and local reports use the manager review flow."}</p>}
    {error && <p className="lab-error" role="alert">{error}</p>}
    {comparison && <div className="impact-panel" aria-live="polite">
      <div className="impact-title"><span className="impact-dot"/><strong>{comparison.label} · {current ? "Calculated impact" : "Previous comparison"}</strong><small>Recorded against the selected itinerary</small></div>
      <div className="impact-metrics"><div><small>BEFORE SIMULATION</small><strong>{duration(comparison.before.total_minutes)}</strong><span>{stamp(comparison.before.arrival_at, zone)}</span></div><ArrowRight size={22}/><div><small>SAME CORRIDOR NOW</small><strong>{matching ? duration(matching.total_minutes) : "Not in top results"}</strong><span>{matching ? stamp(matching.arrival_at, zone) : "Review current alternatives"}</span></div><div className="impact-best"><small>EARLIEST AVAILABLE</small><strong>{best ? duration(best.total_minutes) : "No route"}</strong><span>{saving > 0 ? `${duration(saving)} recovered vs affected corridor` : best ? "Best current scheduled arrival" : "Try another ready time"}</span></div></div>
      <div className="impact-foot"><span><ShieldCheck size={15}/> Calculated automatically. Saved-plan changes require a manager decision.</span><button className="button dark" onClick={onReview}>Review saved plans <ArrowRight size={14}/></button></div>
    </div>}
  </section>;
}
