import { useEffect, useState } from "react";
import { Package, AlertTriangle, Gem, PiggyBank, Factory, CalendarDays, Gauge, History, CloudLightning } from "lucide-react";
import { api } from "../api/client";
import type { Dashboard as Dash, Holiday, AuditEvent, HighValue, Provider, Disruption } from "../api/types";
import { eur, dt, statusClass, riskCls } from "../lib";

export function Dashboard() {
  const [d, setD] = useState<Dash | null>(null);
  const [hol, setHol] = useState<Holiday[]>([]);
  const [audit, setAudit] = useState<AuditEvent[]>([]);
  const [hv, setHv] = useState<HighValue[]>([]);
  const [dis, setDis] = useState<Disruption[]>([]);
  const load = () => {
    api.dashboard().then(setD).catch(() => {});
    api.holidays().then((r) => setHol(r.upcoming)).catch(() => {});
    api.audit().then((r) => setAudit(r.events)).catch(() => {});
    api.highValue().then((r) => setHv(r.shipments)).catch(() => {});
    api.disruptions().then((r) => setDis(r.historical)).catch(() => {});
  };
  useEffect(() => { load(); const t = setInterval(load, 15000); return () => clearInterval(t); }, []);
  const providers: Provider[] = d?.providers ?? [];
  return (
    <>
      <div className="tiles">
        <div className="tile"><div className="l"><Package size={13} /> Shipments</div><div className="v">{d?.total ?? "—"}</div><div className="s">{Object.entries(d?.counts ?? {}).map(([k, v]) => `${v} ${k.toLowerCase()}`).join(" · ")}</div></div>
        <div className="tile tile--risk"><div className="l"><AlertTriangle size={13} /> At risk</div><div className="v">{d?.at_risk ?? "—"}</div><div className="s">medium/high risk</div></div>
        <div className="tile"><div className="l"><Gem size={13} /> High-value</div><div className="v">{d?.high_value ?? "—"}</div><div className="s">≥ €100k</div></div>
        <div className="tile"><div className="l"><Factory size={13} /> Active hub delays</div><div className="v">{d?.active_hub_delays ?? "—"}</div><div className="s">manager input</div></div>
        <div className="tile tile--accent"><div className="l"><PiggyBank size={13} /> Est. savings</div><div className="v">{eur(d?.estimated_savings_eur)}</div><div className="s">vs alternative plan</div></div>
      </div>

      <div className="sectiongrid">
        <div className="card">
          <div className="card__h"><div><h2><Gem size={15} className="h-ic" /> High-value & critical</h2><div className="sub">exposure if delivery is missed</div></div></div>
          <div className="he">
            {hv.length === 0 && <div className="empty">No high-value shipments.</div>}
            {hv.map((h) => (
              <div className="row" key={h.id} style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 6 }}>
                <div><b>{h.id}</b> · {h.origin}→{h.destination} · {eur(h.value_eur)}<div style={{ fontSize: 11, color: "var(--muted)" }}>req {dt(h.required_delivery)} · ETA {dt(h.current_eta)}</div></div>
                <div style={{ textAlign: "right" }}><span className={riskCls(h.risk_level)}>{h.risk_level}</span><div style={{ fontSize: 11, color: "var(--bad)", fontWeight: 700 }}>{h.exposure_eur ? "exposure " + eur(h.exposure_eur) : ""}</div></div>
              </div>
            ))}
          </div>
        </div>

        <div className="card">
          <div className="card__h"><div><h2><CalendarDays size={15} className="h-ic" /> Upcoming holidays</h2><div className="sub">kalender.csv · driving-ban impact</div></div></div>
          <div className="he">
            {hol.map((h) => <div className="row" key={h.date}><span><b>{h.date}</b> · {h.name}</span><span style={{ color: "var(--warn)", fontWeight: 700, fontSize: 11 }}>ban risk</span></div>)}
          </div>
        </div>

        <div className="card">
          <div className="card__h"><div><h2><Gauge size={15} className="h-ic" /> Data sources</h2><div className="sub">LIVE only on a real fetch</div></div></div>
          <div className="he">
            {providers.map((p) => <div className="row" key={p.key}><span>{p.name}<div style={{ fontSize: 11, color: "var(--muted)" }}>{p.kind}</div></span><span className={statusClass(p.status)}><span className="dot" /> {p.status.replace("_", " ")}</span></div>)}
          </div>
        </div>

        <div className="card">
          <div className="card__h"><div><h2><CloudLightning size={15} className="h-ic" /> Historical disruptions</h2><div className="sub">stoerungen.csv</div></div></div>
          <div className="he">
            {dis.slice(0, 6).map((x, i) => <div className="row" key={i}><span><b>{x.type}</b> · {x.from}<div style={{ fontSize: 11, color: "var(--muted)" }}>{x.description.slice(0, 60)}</div></span><span style={{ color: "var(--bad)", fontWeight: 700 }}>{Math.round(x.volume_effect * 100)}%</span></div>)}
          </div>
        </div>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <div className="card__h"><div><h2><History size={15} className="h-ic" /> Audit trail</h2></div></div>
        <div className="audit">
          {audit.map((a, i) => <div className="arow" key={i}><span className="tm">{dt(a.at)}</span><div><span className="ty">{a.type}</span> <span style={{ fontSize: 10, color: "var(--faint)" }}>{a.source}</span><div>{a.detail}</div></div></div>)}
        </div>
      </div>
    </>
  );
}
