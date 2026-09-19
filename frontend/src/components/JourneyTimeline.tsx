import { Package, Truck, Ban, Factory, PauseCircle, CloudSnow } from "lucide-react";
import type { JourneyStep } from "../api/types";

const ICON = { handling: Package, drive: Truck, legal_wait: Ban, hub_delay: Factory, weekend_hold: PauseCircle, weather: CloudSnow };
function hm(m: number) { const h = Math.floor(m / 60), mm = m % 60; return h ? `${h}h${mm ? " " + mm + "m" : ""}` : `${mm}m`; }
function t(iso: string) { return new Date(iso).toLocaleString("en-GB", { weekday: "short", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Berlin", hour12: false }); }

export function JourneyTimeline({ steps, active }: { steps: JourneyStep[]; active?: number }) {
  return (
    <div className="journey">
      {steps.map((s, i) => {
        const Icon = ICON[s.type];
        return (
          <div className={`jstep ${active === i ? "jstep--active" : ""}`} key={i}>
            <div className={`jstep__ic ic-${s.type}`}><Icon size={15} /></div>
            <div>
              <div className="jstep__t">{s.type === "weekend_hold" ? "Weekend Hold" : s.type === "weather" ? "Weather impact" : s.type === "legal_wait" ? "Legal waiting" : s.type === "hub_delay" ? "Operational delay" : s.type === "drive" ? "Drive" : "Handling"} · {s.location_name}</div>
              <div className="jstep__d">{s.detail}</div>
              <div className="jstep__src">{s.source}</div>
            </div>
            <div style={{ textAlign: "right" }}>
              <div className="jstep__dur">{hm(s.minutes)}</div>
              <div className="jstep__time">{t(s.start)} → {t(s.end)}</div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
