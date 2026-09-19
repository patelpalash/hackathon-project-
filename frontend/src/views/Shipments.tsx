import { useEffect, useState } from "react";
import { Plus, X, AlertTriangle, CheckCircle2, Truck } from "lucide-react";
import { api } from "../api/client";
import type { NetNode, Shipment } from "../api/types";
import { eur, dt, hm, riskCls, stCls, localInput } from "../lib";
import { RouteCompare } from "../components/RouteCompare";

export function Shipments({ nodes }: { nodes: NetNode[] }) {
  const [ships, setShips] = useState<Shipment[]>([]);
  const [f, setF] = useState({ status: "", at_risk: false, high_value: false, delayed: false });
  const [creating, setCreating] = useState(false);
  const [detail, setDetail] = useState<Shipment | null>(null);
  const name = (id: string) => nodes.find((n) => n.id === id)?.name ?? id;
  function load() {
    const q = new URLSearchParams();
    if (f.status) q.set("status", f.status);
    if (f.at_risk) q.set("at_risk", "true");
    if (f.high_value) q.set("high_value", "true");
    if (f.delayed) q.set("delayed", "true");
    api.shipments("?" + q.toString()).then((r) => setShips(r.shipments)).catch(() => {});
  }
  useEffect(load, [f]);
  return (
    <>
      <div className="card">
        <div className="card__h"><div><h2><Truck size={15} className="h-ic" /> Shipments</h2><div className="sub">plan → compare → schedule (with feasibility check)</div></div>
          <button className="btn btn--sm" onClick={() => setCreating(true)}><Plus size={14} /> New shipment</button></div>
        <div className="filters">
          <select value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}><option value="">All statuses</option>{["PLANNED", "SCHEDULED", "IN TRANSIT", "DELAYED", "DELIVERED"].map((s) => <option key={s}>{s}</option>)}</select>
          <label style={{ fontSize: 12.5, display: "flex", gap: 5, alignItems: "center" }}><input type="checkbox" checked={f.at_risk} onChange={(e) => setF({ ...f, at_risk: e.target.checked })} /> At risk</label>
          <label style={{ fontSize: 12.5, display: "flex", gap: 5, alignItems: "center" }}><input type="checkbox" checked={f.high_value} onChange={(e) => setF({ ...f, high_value: e.target.checked })} /> High-value</label>
          <label style={{ fontSize: 12.5, display: "flex", gap: 5, alignItems: "center" }}><input type="checkbox" checked={f.delayed} onChange={(e) => setF({ ...f, delayed: e.target.checked })} /> Delayed</label>
        </div>
        <div style={{ overflowX: "auto" }}>
          <table className="htbl">
            <thead><tr><th>ID</th><th>Route</th><th>Status</th><th>ETA</th><th>Required</th><th>Delay</th><th>Weight</th><th>Value</th><th>Cost</th><th>Risk</th><th>Alert</th></tr></thead>
            <tbody>
              {ships.map((s) => (
                <tr key={s.id} style={{ cursor: "pointer" }} onClick={() => api.shipment(s.id).then(setDetail)}>
                  <td><b>{s.id}</b></td>
                  <td>{s.route.map(name).join(" → ")}</td>
                  <td><span className={stCls(s.status)}>{s.status}</span></td>
                  <td>{dt(s.current_eta)}</td><td style={{ color: "var(--muted)" }}>{dt(s.required_delivery)}</td>
                  <td className="num">{s.delay_minutes ? <span style={{ color: "var(--bad)", fontWeight: 700 }}>{hm(s.delay_minutes)}</span> : "—"}</td>
                  <td className="num">{(s.weight_kg / 1000).toFixed(1)}t</td><td className="num">{eur(s.value_eur)}</td><td className="num">{eur(s.est_cost_eur)}</td>
                  <td><span className={riskCls(s.risk_level)}>{s.risk_level}</span></td>
                  <td>{s.alert ? <span style={{ color: "var(--bad)", fontSize: 11, fontWeight: 700 }}><AlertTriangle size={11} style={{ verticalAlign: -1 }} /> {s.alert}</span> : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {ships.length === 0 && <div className="empty">No shipments match.</div>}
        </div>
      </div>

      {creating && <CreateModal nodes={nodes} onClose={() => setCreating(false)} onCreated={() => { setCreating(false); load(); }} />}
      {detail && <Drawer nodes={nodes} shipment={detail} onClose={() => setDetail(null)} onChanged={() => { api.shipment(detail.id).then(setDetail); load(); }} />}
    </>
  );
}

function CreateModal({ nodes, onClose, onCreated }: { nodes: NetNode[]; onClose: () => void; onCreated: () => void }) {
  const [v, setV] = useState({ origin: "R08", destination: "R11", weight_kg: "8000", value_eur: "50000", planned_departure: localInput(new Date()), required_delivery: localInput(new Date(Date.now()+3*86400000)) });
  const [err, setErr] = useState<string | null>(null);
  return (
    <div className="modal-bg" onClick={onClose}><div className="modal" onClick={(e) => e.stopPropagation()}>
      <h3><Plus size={16} style={{ verticalAlign: -3 }} /> New shipment</h3>
      {err && <div className="notice notice--warn">{err}</div>}
      <div className="fld"><label>Origin</label><select value={v.origin} onChange={(e) => setV({ ...v, origin: e.target.value })}>{nodes.map((n) => <option key={n.id} value={n.id}>{n.name}</option>)}</select></div>
      <div className="fld"><label>Destination</label><select value={v.destination} onChange={(e) => setV({ ...v, destination: e.target.value })}>{nodes.map((n) => <option key={n.id} value={n.id}>{n.name}</option>)}</select></div>
      <div className="fld"><label>Weight (kg)</label><input value={v.weight_kg} onChange={(e) => setV({ ...v, weight_kg: e.target.value })} /></div>
      <div className="fld"><label>Value (€)</label><input value={v.value_eur} onChange={(e) => setV({ ...v, value_eur: e.target.value })} /></div>
      <div className="fld"><label>Planned departure (device local)</label><input type="datetime-local" value={v.planned_departure} onChange={(e) => setV({ ...v, planned_departure: e.target.value })} /></div>
      <div className="fld"><label>Required delivery (device local)</label><input type="datetime-local" value={v.required_delivery} onChange={(e) => setV({ ...v, required_delivery: e.target.value })} /></div>
      <div className="row">
        <button className="btn btn--ghost btn--sm" onClick={onClose}>Cancel</button>
        <button className="btn btn--sm" onClick={() => api.createShipment({ ...v, planned_departure: new Date(v.planned_departure).toISOString(), required_delivery: v.required_delivery ? new Date(v.required_delivery).toISOString() : null, weight_kg: Number(v.weight_kg), value_eur: Number(v.value_eur) }).then(onCreated).catch((e) => setErr(String(e)))}>Create &amp; plan</button>
      </div>
    </div></div>
  );
}

function Drawer({ nodes, shipment, onClose, onChanged }: { nodes: NetNode[]; shipment: Shipment; onClose: () => void; onChanged: () => void }) {
  const [msg, setMsg] = useState<string | null>(null);
  const s = shipment;
  const [selected,setSelected] = useState(0);
  const sched = (force: boolean) => api.scheduleShipment(s.id, selected, force).then((r) => { setMsg(r.scheduled ? "Scheduled ✓" : r.warning ?? null); onChanged(); }).catch(e => setMsg(String(e)));
  return (
    <div className="drawer-bg" onClick={onClose}><div className="drawer" onClick={(e) => e.stopPropagation()}>
      <button className="x" onClick={onClose}><X size={18} /></button>
      <h2 style={{ margin: "0 0 4px", fontSize: 18 }}>{s.id} <span className={riskCls(s.risk_level)}>{s.risk_level}</span> <span className={stCls(s.status)}>{s.status}</span></h2>
      <div className="kv">
        <span className="k">Route</span><span className="v">{s.route.map((id) => nodes.find((n) => n.id === id)?.name ?? id).join(" → ")}</span>
        <span className="k">ETA</span><span className="v">{dt(s.current_eta)}</span>
        <span className="k">Required</span><span className="v">{dt(s.required_delivery)}</span>
        <span className="k">Weight / value</span><span className="v">{(s.weight_kg / 1000).toFixed(1)}t · {eur(s.value_eur)}</span>
        <span className="k">Est. cost / fuel</span><span className="v">{eur(s.est_cost_eur)} · {s.est_fuel_l}L</span>
        <span className="k">Cost / kg</span><span className="v">{s.cost_per_kg != null ? "€" + s.cost_per_kg.toFixed(3) : "—"}</span>
      </div>
      {msg && <div className={`notice ${msg.startsWith("Scheduled") ? "notice--info" : "notice--warn"}`} style={{ margin: "0 16px 8px" }}>{msg.startsWith("Scheduled") ? <CheckCircle2 size={15} /> : <AlertTriangle size={15} />} {msg}</div>}
      <div style={{ display: "flex", gap: 8, padding: "0 16px 12px" }}>
        <button className="btn btn--sm" onClick={() => sched(false)}><CheckCircle2 size={14} /> Schedule selected</button>
        {!s.options?.[selected]?.risk.deadline_ok && <button className="btn btn--ghost btn--sm" onClick={() => sched(true)}>Schedule anyway</button>}
      </div>
      {s.options && <div className="card">{<RouteCompare nodes={nodes} options={s.options} selected={selected} onSelect={setSelected} />}</div>}
    </div></div>
  );
}
