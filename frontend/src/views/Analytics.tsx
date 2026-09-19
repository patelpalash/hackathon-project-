import { useEffect, useState } from "react";
import { BarChart3, Building2, Plus, X, Factory, CloudLightning } from "lucide-react";
import { api } from "../api/client";
import type { RelationStat, Hub, Disruption } from "../api/types";
import { hm } from "../lib";

export function Analytics({ onData }: { onData: () => void }) {
  const [rel, setRel] = useState<RelationStat[]>([]);
  const [hubs, setHubs] = useState<Hub[]>([]);
  const [dis, setDis] = useState<Disruption[]>([]);
  const [weatherAlerts,setWeatherAlerts] = useState<string[]>([]);
  const [delayFor, setDelayFor] = useState<Hub | null>(null);
  function load() {
    api.operations().then(o=>setWeatherAlerts(o.weather.filter(w=>w.alert && Date.parse(w.end)>Date.now()).map(w=>w.node))).catch(()=>{});
    api.relations().then((r) => setRel(r.relations)).catch(() => {});
    api.hubs().then((r) => setHubs(r.hubs)).catch(() => {});
    api.disruptions().then((r) => setDis(r.historical)).catch(() => {});
  }
  useEffect(load, []);
  return (
    <>
      <div className="card">
        <div className="card__h"><div><h2><BarChart3 size={15} className="h-ic" /> Lane performance (historical)</h2><div className="sub">disposition.csv — 19,980 daily records · ranked by spillover</div></div></div>
        <div style={{ overflowX: "auto" }}>
          <table className="htbl">
            <thead><tr><th>Lane</th><th>Destination</th><th>km</th><th>Util</th><th>Spillover</th><th>Reliability</th><th>Line €</th><th>Special €</th><th>Avg €/day</th><th>Days</th></tr></thead>
            <tbody>{rel.map((r) => (
              <tr key={r.relation}><td><b>{r.relation}</b></td><td>{r.destination}</td><td className="num">{r.km}</td>
                <td className="num">{r.avg_utilisation}%</td>
                <td className="num" style={{ color: r.spillover_rate > 0.18 ? "var(--bad)" : "inherit", fontWeight: r.spillover_rate > 0.18 ? 700 : 400 }}>{(r.spillover_rate * 100).toFixed(0)}%</td>
                <td className="num">{r.reliability_pct}%</td><td className="num" style={{ color: "var(--muted)" }}>{r.cost_line_eur}</td>
                <td className="num" style={{ color: "var(--muted)" }}>{r.cost_special_eur}</td><td className="num">{r.avg_daily_cost_eur?.toLocaleString()}</td>
                <td className="num" style={{ color: "var(--faint)" }}>{r.samples?.toLocaleString()}</td></tr>
            ))}</tbody>
          </table>
        </div>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <div className="card__h"><div><h2><Building2 size={15} className="h-ic" /> Hubs &amp; operational delays</h2><div className="sub">transfer = historical proxy · managers set temporary delays</div></div></div>
        <div style={{ overflowX: "auto" }}>
          <table className="htbl">
            <thead><tr><th>Hub</th><th>Type</th><th>Avg transfer</th><th>Reliability</th><th>Operational delay</th><th></th></tr></thead>
            <tbody>{hubs.map((h) => {
              const t = "avg_transfer_minutes" in h.transfer ? h.transfer : null;
              const hi = "reliability_pct" in h.history ? h.history : null;
              return (<tr key={h.id}><td><b>{h.name}</b> {weatherAlerts.includes(h.id) && <span className="chip chip--delay">Weather alert</span>} <span style={{ color: "var(--faint)", fontSize: 11 }}>{h.id}</span></td>
                <td style={{ color: "var(--muted)" }}>{h.type}</td><td className="num">{t ? hm(t.avg_transfer_minutes) : "2h"}</td>
                <td className="num">{hi ? hi.reliability_pct + "%" : "—"}</td>
                <td>{h.operational_delay ? <span className="chip chip--delay"><Factory size={11} /> +{h.operational_delay.minutes}m · {h.operational_delay.reason}</span> : <span style={{ color: "var(--faint)", fontSize: 12 }}>none</span>}</td>
                <td style={{ textAlign: "right" }}>{h.operational_delay
                  ? <button className="delaybtn" onClick={() => api.clearDelay(h.id).then(() => { load(); onData(); })}><X size={12} /> resolve</button>
                  : <button className="delaybtn" onClick={() => setDelayFor(h)}><Plus size={12} /> add delay</button>}</td></tr>);
            })}</tbody>
          </table>
        </div>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <div className="card__h"><div><h2><CloudLightning size={15} className="h-ic" /> Historical disruption log</h2><div className="sub">stoerungen.csv</div></div></div>
        <div className="he">{dis.map((x, i) => (
          <div className="row" key={i}><span><b>{x.type}</b> · {x.from}{x.to !== x.from ? "→" + x.to : ""}<div style={{ fontSize: 11, color: "var(--muted)" }}>{x.description}</div></span>
            <span style={{ color: "var(--bad)", fontWeight: 700, whiteSpace: "nowrap" }}>{Math.round(x.volume_effect * 100)}% vol</span></div>
        ))}</div>
      </div>

      {delayFor && <DelayModal hub={delayFor} onClose={() => setDelayFor(null)} onSaved={() => { setDelayFor(null); load(); onData(); }} />}
    </>
  );
}

function DelayModal({ hub, onClose, onSaved }: { hub: Hub; onClose: () => void; onSaved: () => void }) {
  const [minutes, setMinutes] = useState("90");
  const [reason, setReason] = useState("High shipment volume");
  const [note, setNote] = useState("");
  return (
    <div className="modal-bg" onClick={onClose}><div className="modal" onClick={(e) => e.stopPropagation()}>
      <h3><Factory size={16} style={{ verticalAlign: -3 }} /> Operational delay · {hub.name}</h3>
      <div className="fld"><label>Additional minutes</label><input value={minutes} onChange={(e) => setMinutes(e.target.value)} /></div>
      <div className="fld"><label>Reason</label><select value={reason} onChange={(e) => setReason(e.target.value)}>{["High shipment volume", "Loading delay", "Unloading delay", "Sorting delay", "Equipment failure", "Staff shortage", "IT/system problem", "Vehicle availability", "Capacity problem", "Other"].map((r) => <option key={r}>{r}</option>)}</select></div>
      <div className="fld"><label>Note</label><input value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Friday evening loading capacity reduced" /></div>
      <div className="row"><button className="btn btn--ghost btn--sm" onClick={onClose}>Cancel</button>
        <button className="btn btn--sm" onClick={() => api.setDelay(hub.id, { minutes: Number(minutes), reason, note }).then(onSaved)}>Save delay</button></div>
    </div></div>
  );
}
