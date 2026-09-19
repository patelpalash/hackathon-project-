"""
Shipment lifecycle + persistence. The provided data is aggregate daily operations,
not per-shipment records, so managers CREATE shipments here; each is planned,
costed, risk-scored and scheduled with a real feasibility check. Persisted to a
JSON store (STORE_DIR) so it survives restarts.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone

from .cost import journey_cost, cost_per_kg
from .eta import compute_journey
from .risk import assess

STORE_DIR = os.environ.get("STORE_DIR", os.path.join(os.getcwd(), "store"))
STORE = os.path.join(STORE_DIR, "shipments.json")
KG_PER_LDM = 1750.0


def _load():
    try:
        with open(STORE, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _save(d):
    os.makedirs(STORE_DIR, exist_ok=True)
    temporary = STORE + ".tmp"
    with open(temporary, "w", encoding="utf-8") as fh:
        json.dump(d, fh, indent=2, default=str)
    os.replace(temporary, STORE)


def _ldm(weight_kg):
    return max(0.5, round((weight_kg or 0) / KG_PER_LDM, 1))


def plan(ctx, origin, destination, depart_utc, weight_kg, required_delivery, value_eur, optimization="fastest", truck=None):
    from .hub_selection import select_hubs, ll
    from .operations import parse
    net=ctx["network"]; operations=ctx["operations"]; ldm=_ldm(weight_kg)
    if ldm>13.6: raise ValueError("Shipment exceeds the prototype single-trailer capacity (13.6 loading metres). Split the shipment.")
    road=ctx["providers"].routing.leg(ll(net["nodes"][origin]),ll(net["nodes"][destination]))
    blocked={e["node"] for e in operations.data["events"] if e["kind"]=="closure" and e.get("node") and operations.overlaps(e,depart_utc,depart_utc+timedelta(days=7))}
    selected=select_hubs(net["nodes"][origin],net["nodes"][destination],net["nodes"].values(),road,ctx["providers"].routing,{"blocked":blocked,"ldm":ldm})
    paths=[([origin,destination],None)]+[([origin,h["hub"],destination],h) for h in selected]
    options=[]
    for path,hub in paths:
        jr=compute_journey(net,ctx["holidays"],ctx["transfer"],ctx["hub_delays"],ctx["providers"],origin,destination,depart_utc,path,operations,truck)
        # Use the SAME road distances for fuel, cost and map/ETA.
        cost_net={**net,"edges":dict(net["edges"])}
        for leg in jr["road_legs"]:
            key=leg["from"]+"-"+leg["to"]
            edge=cost_net["edges"].get(key,{"cost_eur":round(leg["km"]*2.6),"capacity_ldm":13.6})
            cost_net["edges"][key]={**edge,"km":leg["km"]}
        c=journey_cost(cost_net,path,ldm)
        # Only attach lane histories for actual dataset edges, not unrelated endpoint histories.
        relations={net["edges"][a+"-"+b]["relation"] for a,b in zip(path,path[1:]) if a+"-"+b in net["edges"]}
        hist=[ctx["history"][r] for r in relations if r in ctx["history"]]
        risk=assess(jr,required_delivery,value_eur,hist)
        if jr["weather_alerts"]:
            risk["reasons"].append("Weather alert adds a modelled delay")
            risk["score"]+=25
        if jr["components"]["hub_delay"] or jr["components"]["traffic"]:
            risk["reasons"].append("Active operational events included in ETA")
            risk["score"]+=20
        risk["level"]="HIGH" if risk["score"]>=55 else "MEDIUM" if risk["score"]>=25 else "LOW"
        known=all(a+"-"+b in net["edges"] for a,b in zip(path,path[1:]))
        options.append({**jr,"label":f"Via {hub['name']}" if hub else "Direct road estimate","kind":"dataset_lane" if known else "estimate",
                        "intermediate_hub":hub,"recommendation_note":"Planning recommendation only; departure schedules and carrier availability are not supplied.",
                        "cost":{"transport_eur":c["transport_eur"],"fuel_l":c["fuel_l"],"fuel_eur":c["fuel_eur"],"distance_km":round(c["km"],1),"cost_per_kg":cost_per_kg(c["transport_eur"],weight_kg)},
                        "risk":risk,"ldm":ldm,"historical":_hist_summary(hist),"revision":operations.data["revision"]})
    from .optimization import decorate
    return decorate(options,ctx,origin,destination,ldm,optimization)


def _hist_summary(lane_hist):
    if not lane_hist:
        return None
    n = len(lane_hist)
    return {
        "avg_cost_eur": round(sum(h["avg_daily_cost_eur"] for h in lane_hist) / n),
        "avg_fuel_l": round(sum(h["avg_daily_fuel_l"] for h in lane_hist) / n),
        "reliability_pct": round(sum(h["reliability_pct"] for h in lane_hist) / n, 1),
        "samples": sum(h["samples"] for h in lane_hist),
    }


def savings_vs_baseline(recommended, baseline):
    """Estimated savings of recommended vs a baseline option (not guaranteed)."""
    return {
        "money_eur": baseline["cost"]["transport_eur"] - recommended["cost"]["transport_eur"],
        "fuel_l": baseline["cost"]["fuel_l"] - recommended["cost"]["fuel_l"],
        "time_min": baseline["total_minutes"] - recommended["total_minutes"],
        "note": "Estimated, not guaranteed — based on tariffs (relationen.csv) and current plan.",
    }


class Shipments:
    def __init__(self, ctx):
        self.ctx = ctx
        self.data = _load()
        for ship in self.data.values():
            if "accepted_plan" not in ship:
                ship["accepted_plan"] = next((o for o in ship.get("options",[]) if o["path"] == ship["route"]), None)

    def seed_if_empty(self):
        if self.data:
            return
        net = self.ctx["network"]
        base = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        samples = [
            ("R01", "R11", 8200, 42000, base + timedelta(hours=2), base + timedelta(days=2, hours=9), "Top"),
            ("R11", "R24", 15400, 180000, base + timedelta(hours=6), base + timedelta(days=2), "Top"),
            ("R08", "R03", 3100, 12000, base + timedelta(days=1), base + timedelta(days=3), "Standard"),
            ("R16", "R21", 21000, 810000, _next_friday(base, 16), _next_monday(_next_friday(base, 16), 9), "Top"),
        ]
        for o, d, w, v, dep, req, seg in samples:
            self.create({"origin": o, "destination": d, "weight_kg": w, "value_eur": v,
                         "planned_departure": dep.isoformat(), "required_delivery": req.isoformat(),
                         "customer_segment": seg, "container": f"C{uuid.uuid4().hex[:5].upper()}"})

    def create(self, p):
        sid = "SHP-" + uuid.uuid4().hex[:6].upper()
        dep = datetime.fromisoformat(p["planned_departure"].replace("Z", "+00:00")).astimezone(timezone.utc)
        opts = plan(self.ctx, p["origin"], p["destination"], dep, p.get("weight_kg", 0),
                    p.get("required_delivery"), p.get("value_eur", 0), p.get("optimization","fastest"),p.get("truck"))
        chosen = next((i for i,o in enumerate(opts) if o["path"] == p.get("selected_path")), 0)
        if p.get("selected_path") and opts[chosen]["path"] != p["selected_path"]: raise ValueError("Selected route is no longer available. Recalculate first.")
        rec = opts[chosen]
        ship = {
            "optimization": p.get("optimization","fastest"), "truck": p.get("truck"),
            "id": sid, "origin": p["origin"], "destination": p["destination"],
            "current_location": p["origin"], "route": rec["path"],
            "next_hub": rec["path"][1] if len(rec["path"]) > 1 else None,
            "status": "PLANNED",
            "planned_departure": p["planned_departure"], "scheduled_departure": None,
            "current_eta": rec["eta"], "required_delivery": p.get("required_delivery"),
            "distance_km": rec["cost"]["distance_km"], "weight_kg": p.get("weight_kg", 0),
            "container": p.get("container"), "value_eur": p.get("value_eur", 0),
            "est_cost_eur": rec["cost"]["transport_eur"], "est_fuel_l": rec["cost"]["fuel_l"],
            "cost_per_kg": rec["cost"]["cost_per_kg"], "risk_level": rec["risk"]["level"],
            "customer_segment": p.get("customer_segment"),
            "alert": None if rec["risk"]["deadline_ok"] else "Delivery deadline at risk",
            "options": opts, "selected_option": chosen, "accepted_plan": rec, "created_at": datetime.now(timezone.utc).isoformat(),
        }
        ship["delay_minutes"] = _delay(rec["eta"], p.get("required_delivery"))
        self.data[sid] = ship
        _save(self.data)
        return ship

    def schedule(self, sid, option_index=0, force=False):
        s = self.data.get(sid)
        if not s:
            return None, "unknown shipment"
        if s["status"] in {"IN TRANSIT", "DELIVERED"}: raise ValueError("Scheduling changes are supported before dispatch only")
        if not 0 <= option_index < len(s["options"]): raise ValueError("Invalid route option")
        opt = s["options"][option_index]
        if opt.get("revision", -1) != self.ctx["operations"].data["revision"]: raise ValueError("Conditions changed. Recalculate the shipment before scheduling.")
        if opt.get("valid_until") and datetime.fromisoformat(opt["valid_until"]) < datetime.now(timezone.utc): raise ValueError("Live quote expired. Recalculate before scheduling.")
        if not opt["risk"]["deadline_ok"] and not force:
            # feasibility warning BEFORE committing
            return s, f"WARNING: selected route misses delivery window (ETA {opt['eta']}). Schedule anyway or pick another route."
        s.update({"status": "SCHEDULED", "scheduled_departure": s["planned_departure"],
                  "route": opt["path"], "current_eta": opt["eta"],
                  "est_cost_eur": opt["cost"]["transport_eur"], "est_fuel_l": opt["cost"]["fuel_l"],
                  "risk_level": opt["risk"]["level"], "selected_option": option_index, "accepted_plan": opt,
                  "next_hub": opt["path"][1], "distance_km": opt["cost"]["distance_km"], "cost_per_kg": opt["cost"]["cost_per_kg"],
                  "delay_minutes": _delay(opt["eta"],s.get("required_delivery")), "alert": None if opt["risk"]["deadline_ok"] else "Delivery deadline at risk"})
        _save(self.data)
        return s, None

    def replan(self, sid):
        s=self.data[sid]
        if s["status"] in ("IN TRANSIT","DELIVERED"):
            raise ValueError("Prototype replanning is supported before dispatch only")
        s["options"]=plan(self.ctx,s["origin"],s["destination"],datetime.fromisoformat(s["planned_departure"].replace("Z","+00:00")),s["weight_kg"],s.get("required_delivery"),s.get("value_eur",0),s.get("optimization","fastest"),s.get("truck"))
        _save(self.data)
        return s

    def set_status(self, sid, status):
        if status not in {"PLANNED","SCHEDULED","IN TRANSIT","DELAYED","DELIVERED"}: raise ValueError("Invalid shipment status")
        s = self.data.get(sid)
        if s:
            s["status"] = status; _save(self.data)
        return s

    def list(self):
        return sorted(self.data.values(), key=lambda x: x["created_at"], reverse=True)

    def get(self, sid):
        return self.data.get(sid)


def _delay(eta, required):
    if not required:
        return 0
    e = datetime.fromisoformat(eta); r = datetime.fromisoformat(required.replace("Z", "+00:00"))
    return max(0, int((e - r).total_seconds() // 60))


def _next_friday(base, hour):
    d = base
    while d.isoweekday() != 5:
        d += timedelta(days=1)
    return d.replace(hour=hour)


def _next_monday(base, hour):
    d = base + timedelta(days=1)
    while d.isoweekday() != 1:
        d += timedelta(days=1)
    return d.replace(hour=hour)
