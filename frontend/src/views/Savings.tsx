import { useEffect, useState } from "react";
import { PiggyBank, Fuel, Clock, TrendingDown } from "lucide-react";
import { api } from "../api/client";
import type { SavingsResp } from "../api/types";
import { eur, hm } from "../lib";

export function Savings() {
  const [s, setS] = useState<SavingsResp | null>(null);
  useEffect(() => { api.savings().then(setS).catch(() => {}); }, []);
  return (
    <>
      <div className="tiles">
        <div className="tile tile--accent"><div className="l"><PiggyBank size={13} /> Net savings (est.)</div><div className="v">{eur(s?.total.money_eur)}</div><div className="s">signed comparison vs direct routes</div></div>
        <div className="tile"><div className="l"><Fuel size={13} /> Fuel saved</div><div className="v">{s?.total.fuel_l ?? "—"} L</div></div>
        <div className="tile"><div className="l"><Clock size={13} /> Time saved</div><div className="v">{s ? (s.total.time_min<0?"−":"")+hm(Math.abs(s.total.time_min)) : "—"}</div></div>
        <div className="tile"><div className="l"><TrendingDown size={13} /> Optimized</div><div className="v">{s?.total.optimized ?? "—"}</div><div className="s">avg {eur(s?.avg_per_shipment_eur)}/shipment</div></div>
      </div>
      <div className="card" style={{ marginTop: 16 }}>
        <div className="card__h"><div><h2><PiggyBank size={15} className="h-ic" /> Savings by shipment</h2><div className="sub">{s?.note}</div></div></div>
        <div style={{ overflowX: "auto" }}>
          <table className="htbl">
            <thead><tr><th>Shipment</th><th>Container</th><th>Money</th><th>Fuel</th><th>Time</th></tr></thead>
            <tbody>{(s?.per_shipment ?? []).map((p) => (
              <tr key={p.id}><td><b>{p.id}</b></td><td style={{ color: "var(--muted)" }}>{p.container ?? "—"}</td>
                <td className="num" style={{ color: p.money_eur>=0 ? "var(--ok)" : "var(--bad)", fontWeight: 700 }}>{eur(p.money_eur)}</td>
                <td className="num">{p.fuel_l} L</td><td className="num">{(p.time_min<0?"−":"")+hm(Math.abs(p.time_min))}</td></tr>
            ))}</tbody>
          </table>
          {(!s || s.per_shipment.length === 0) && <div className="empty">No optimized shipments yet.</div>}
        </div>
      </div>
    </>
  );
}
