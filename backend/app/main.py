"""
DACHSER Live Transit Planner — API.
Real network + holidays + historical analytics; dynamic restriction engine; ETA,
cost, fuel, risk, savings engines; shipment lifecycle; live providers (honest
status); manager hub delays; audit. See README for the section-by-section map.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, AwareDatetime, model_validator
from typing import Literal
from functools import wraps
from fastapi.responses import JSONResponse, Response
from .operations import Operations, parse, LOCK
from .weather_rules import evaluate, THRESHOLDS

from . import analytics as an
from . import data as dataloader
from .cost import journey_cost, cost_per_kg
from .eta import compute_journey, _haversine_km
from .providers import Providers
from .restrictions import drive_with_restrictions
from .risk import assess
from .shipments import Shipments, plan as plan_options, savings_vs_baseline

from pathlib import Path
DATA_DIR = os.environ.get("DATA_DIR", str(Path(__file__).resolve().parents[2] / "data" / "raw"))
S = {}


def _now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _audit(kind, detail, source="system"):
    S["audit"].insert(0, {"at": _now_iso(), "type": kind, "detail": detail, "source": source})
    S["audit"] = S["audit"][:300]


def _ctx():
    return {"network": S["network"], "holidays": S["holidays"], "transfer": S["transfer"],
            "hub_delays": S["hub_delays"], "providers": S["providers"], "history": S["history"],
            "operations": S["operations"]}


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not DATA_DIR or not os.path.isdir(DATA_DIR):
        raise RuntimeError("Set DATA_DIR to the folder containing the DACHSER CSVs.")
    S["network"] = dataloader.load_network(DATA_DIR)
    S["holidays"] = dataloader.load_holidays(DATA_DIR)
    S["transfer"] = dataloader.transfer_stats(DATA_DIR)
    # relationen dict for cost/analytics
    rel = {}
    for e in S["network"]["edges"].values():
        if e["from"] == S["network"]["hub_id"]:
            rel[e["relation"]] = {"km": e["km"], "cost_line": e["cost_eur"], "cost_special": e["cost_special_eur"]}
    S["history"] = an.relation_history(DATA_DIR, rel)
    S["disruptions"] = an.disruptions(DATA_DIR)
    S["providers"] = Providers(S["holidays"])
    S["operations"] = Operations()
    S["hub_delays"] = S["operations"].data.setdefault("hub_delays", {})
    S["audit"] = []
    S["ships"] = Shipments(_ctx())
    S["ships"].seed_if_empty()
    _audit("startup", f"{len(S['network']['nodes'])} hubs, {len(S['holidays'])} holidays, "
                      f"{len(S['history'])} lane histories, {len(S['ships'].list())} shipments")
    yield


app = FastAPI(title="DACHSER Live Transit Planner", version="3.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def serialized(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        with LOCK:
            return fn(*args, **kwargs)
    return wrapped

@app.exception_handler(ValueError)
async def invalid_request(request, exc):
    return JSONResponse(status_code=422, content={"detail": str(exc)})

class TruckReq(BaseModel):
    height_m: float = Field(default=4, gt=0, le=6)
    width_m: float = Field(default=2.55, gt=0, le=4)
    length_m: float = Field(default=16.5, gt=0, le=30)
    gross_weight_kg: float = Field(default=40000, gt=0, le=100000)

class RouteReq(BaseModel):
    optimization: Literal["fastest","cost","balanced"] = "fastest"
    truck: TruckReq = Field(default_factory=TruckReq)
    origin: str
    destination: str
    depart_at: Optional[AwareDatetime] = None
    weight_kg: float = Field(default=8000, gt=0, le=23800)
    required_delivery: Optional[AwareDatetime] = None
    value_eur: float = Field(default=0, ge=0)


class DelayReq(BaseModel):
    minutes: int = Field(ge=0, le=10080)
    reason: str = Field(min_length=1, max_length=500)
    note: Optional[str] = ""


class ShipmentReq(BaseModel):
    optimization: Literal["fastest","cost","balanced"] = "fastest"
    truck: TruckReq = Field(default_factory=TruckReq)
    selected_path: Optional[list[str]] = None
    origin: str
    destination: str
    weight_kg: float = Field(default=8000, gt=0, le=23800)
    value_eur: float = Field(default=0, ge=0)
    planned_departure: AwareDatetime
    required_delivery: Optional[AwareDatetime] = None
    container: Optional[str] = None
    customer_segment: Optional[str] = None


def _parse(dt):
    return parse(dt) if isinstance(dt, str) else dt.astimezone(timezone.utc)


# ---- network / reference ----
@app.get("/api/health")
def health():
    return {"status": "ok", "version": "3.0.0-combined", "hubs": len(S["network"]["nodes"]), "time": _now_iso()}


@app.get("/api/network")
def network():
    n = S["network"]
    return {"hub_id": n["hub_id"], "nodes": list(n["nodes"].values()), "edges": list(n["edges"].values())}


@app.get("/api/hubs")
def hubs():
    out = []
    for nid, node in S["network"]["nodes"].items():
        rel = node.get("relation")
        st = S["transfer"].get(rel, {}) if rel else {}
        hist = S["history"].get(rel, {}) if rel else {}
        delay = S["hub_delays"].get(nid)
        out.append({**node, "transfer": st, "history": hist, "operational_delay": delay,
                    "expected_transfer_minutes": (st.get("avg_transfer_minutes", 120) if node["type"] == "branch" else 120) + (delay["minutes"] if delay else 0)})
    return {"hubs": out}


@app.get("/api/providers")
def providers():
    return {"providers": S["providers"].all(), "generated_at": _now_iso()}


@app.get("/api/holidays")
def holidays():
    today = datetime.now(timezone.utc).date().isoformat()
    up = sorted([{"date": d, "name": n, "region": "Baden-Württemberg", "country": "DE",
                  "transport_impact": "Prototype holiday window 00:00–22:00; Sunday business hold until Monday"}
                 for d, n in S["holidays"].items() if d >= today], key=lambda x: x["date"])[:12]
    return {"source": "kalender.csv (Baden-Württemberg)", "upcoming": up, "count": len(S["holidays"])}


@app.get("/api/analytics/relations")
def analytics_relations():
    net = S["network"]
    rows = []
    for e in net["edges"].values():
        if e["from"] == net["hub_id"]:
            h = S["history"].get(e["relation"], {})
            rows.append({"relation": e["relation"], "destination": net["nodes"][e["to"]]["name"],
                         "km": e["km"], "cost_line_eur": e["cost_eur"], "cost_special_eur": e["cost_special_eur"], **h})
    return {"relations": sorted(rows, key=lambda r: r.get("spillover_rate", 0), reverse=True)}


@app.get("/api/disruptions")
def disruptions():
    active = [{"hub": nid, "name": S["network"]["nodes"][nid]["name"], **d, "source": "MANAGER INPUT"}
              for nid, d in S["hub_delays"].items()]
    return {"active_operational": active, "historical": S["disruptions"]}


@app.get("/api/weather")
def weather(node: str):
    n = S["network"]["nodes"].get(node)
    if not n:
        raise HTTPException(404, "unknown node")
    return {"node": node, **S["providers"].weather.fetch(n["lat"], n["lon"])}


# ---- planning ----
@app.post("/api/route")
@serialized
def route(req: RouteReq):
    net = S["network"]
    if req.origin not in net["nodes"] or req.destination not in net["nodes"]:
        raise HTTPException(422, "unknown origin or destination")
    if req.origin == req.destination:
        raise HTTPException(422, "origin equals destination")
    if req.weight_kg > req.truck.gross_weight_kg: raise ValueError("Gross vehicle weight must include the cargo")
    depart = _parse(req.depart_at) if req.depart_at else datetime.now(timezone.utc)
    options = plan_options(_ctx(), req.origin, req.destination, depart,
                           req.weight_kg, req.required_delivery.isoformat() if req.required_delivery else None, req.value_eur, req.optimization, req.truck.model_dump())

    savings = savings_vs_baseline(options[0], options[1]) if len(options) > 1 else None
    wx = []  # Manual/sample records are evaluated by the same weather alert engine.
    _audit("route_calculated", f"{req.origin} → {req.destination}: recommended ETA {options[0]['eta']}")
    return {"options": options, "recommended": 0, "savings": savings,
            "weather": wx, "revision": S["operations"].data["revision"], "providers": S["providers"].all(), "evaluated_at": _now_iso()}


# ---- shipments ----
@app.get("/api/shipments")
def list_shipments(status: Optional[str] = None, origin: Optional[str] = None,
                   destination: Optional[str] = None, at_risk: Optional[bool] = None,
                   high_value: Optional[bool] = None, delayed: Optional[bool] = None):
    items = S["ships"].list()
    def keep(s):
        if status and s["status"] != status: return False
        if origin and s["origin"] != origin: return False
        if destination and s["destination"] != destination: return False
        if at_risk and s["risk_level"] not in ("MEDIUM", "HIGH"): return False
        if high_value and (s.get("value_eur", 0) < 100000): return False
        if delayed and not s.get("delay_minutes"): return False
        return True
    return {"shipments": [{k: v for k, v in s.items() if k not in {"options", "accepted_plan"}} for s in items if keep(s)]}


@app.get("/api/shipments/{sid}")
def get_shipment(sid: str):
    s = S["ships"].get(sid)
    if not s:
        raise HTTPException(404, "unknown shipment")
    return s


@app.post("/api/shipments")
@serialized
def create_shipment(req: ShipmentReq):
    net = S["network"]
    if req.origin not in net["nodes"] or req.destination not in net["nodes"] or req.origin == req.destination:
        raise HTTPException(422, "invalid origin/destination")
    if req.weight_kg > req.truck.gross_weight_kg: raise ValueError("Gross vehicle weight must include the cargo")
    s = S["ships"].create(req.model_dump(mode="json"))
    _audit("shipment_created", f"{s['id']}: {req.origin} → {req.destination}, {req.weight_kg:.0f} kg, risk {s['risk_level']}")
    return s


@app.post("/api/shipments/{sid}/schedule")
@serialized
def schedule_shipment(sid: str, option: int = 0, force: bool = False):
    s, warn = S["ships"].schedule(sid, option, force)
    if s is None:
        raise HTTPException(404, "unknown shipment")
    if warn and not force:
        return {"scheduled": False, "warning": warn, "shipment": {k: v for k, v in s.items() if k not in {"options", "accepted_plan"}}}
    _audit("shipment_scheduled", f"{sid}: scheduled via option {option}{' (forced past warning)' if force else ''}")
    return {"scheduled": True, "shipment": {k: v for k, v in s.items() if k not in {"options", "accepted_plan"}}}


@app.post("/api/shipments/{sid}/status")
@serialized
def set_status(sid: str, status: str):
    s = S["ships"].set_status(sid, status)
    if not s:
        raise HTTPException(404, "unknown shipment")
    _audit("shipment_status", f"{sid}: → {status}")
    return {"ok": True, "status": status}


# ---- dashboards ----
@app.get("/api/savings")
def savings():
    total = {"money_eur": 0, "fuel_l": 0, "time_min": 0, "optimized": 0}
    per = []
    for s in S["ships"].list():
        chosen = s.get("accepted_plan") or {}
        comparison = chosen.get("comparison")
        if not comparison: continue  # legacy plans need recalculation; never invent savings
        sv = {"money_eur":comparison["money_saved_eur"],"fuel_l":comparison["fuel_saved_l"],"time_min":comparison["minutes_saved"]}
        total["money_eur"] += sv["money_eur"]; total["fuel_l"] += sv["fuel_l"]
        total["time_min"] += sv["time_min"]; total["optimized"] += 1
        per.append({"id":s["id"],"container":s.get("container"),**sv})
    n = total["optimized"] or 1
    return {"total": total, "avg_per_shipment_eur": round(total["money_eur"] / n, 2),
            "per_shipment": per, "note": "Signed estimate against each saved quote’s direct route. Negative values mean added cost, fuel or time. Legacy plans need recalculation.",
            "source": "relationen.csv tariffs + plan"}


@app.get("/api/high-value")
def high_value():
    out = []
    for s in S["ships"].list():
        if s.get("value_eur", 0) >= 100000:
            opt = s.get("accepted_plan") or s.get("options", [{}])[0]
            out.append({"id": s["id"], "value_eur": s["value_eur"], "origin": s["origin"],
                        "destination": s["destination"], "current_location": s["current_location"],
                        "route": s["route"], "required_delivery": s.get("required_delivery"),
                        "current_eta": s["current_eta"], "risk_level": s["risk_level"],
                        "exposure_eur": opt.get("risk", {}).get("exposure_eur", 0),
                        "reasons": opt.get("risk", {}).get("reasons", []),
                        "recommended_action": "Review alternatives" if s["risk_level"] != "LOW" else "On track"})
    return {"shipments": sorted(out, key=lambda x: x["exposure_eur"], reverse=True)}


@app.get("/api/dashboard")
def dashboard():
    ships = S["ships"].list()
    by_status = {}
    for s in ships:
        by_status[s["status"]] = by_status.get(s["status"], 0) + 1
    at_risk = [s["id"] for s in ships if s["risk_level"] in ("MEDIUM", "HIGH")]
    high_val = [s["id"] for s in ships if s.get("value_eur", 0) >= 100000]
    sv = savings()
    hol = holidays()["upcoming"]
    return {"counts": by_status, "total": len(ships), "at_risk": len(at_risk),
            "high_value": len(high_val), "active_hub_delays": len(S["hub_delays"]),
            "next_holiday": hol[0] if hol else None,
            "estimated_savings_eur": sv["total"]["money_eur"],
            "providers": S["providers"].all(), "generated_at": _now_iso()}


# ---- manager ----
@app.post("/api/hubs/{node_id}/delay")
@serialized
def set_delay(node_id: str, req: DelayReq):
    if node_id not in S["network"]["nodes"]:
        raise HTTPException(404, "unknown hub")
    S["hub_delays"][node_id] = {"minutes": req.minutes, "reason": req.reason, "note": req.note,
                                "status": "ACTIVE", "at": _now_iso()}
    S["operations"].data["revision"] += 1
    S["operations"].save()
    _audit("hub_delay_set", f"{S['network']['nodes'][node_id]['name']}: +{req.minutes}m — {req.reason}", "MANAGER INPUT")
    return {"ok": True, "hub": node_id, "delay": S["hub_delays"][node_id]}


@app.delete("/api/hubs/{node_id}/delay")
@serialized
def clear_delay(node_id: str):
    if S["hub_delays"].pop(node_id, None):
        S["operations"].data["revision"] += 1
        S["operations"].save()
        _audit("hub_delay_resolved", f"{S['network']['nodes'][node_id]['name']}: operational delay resolved", "MANAGER INPUT")
    return {"ok": True}


@app.get("/api/audit")
def audit():
    return {"events": S["audit"]}


# ---- sample weather / events / manager review ----
class WindowReq(BaseModel):
    start: AwareDatetime
    end: AwareDatetime
    @model_validator(mode="after")
    def chronological(self):
        if self.end <= self.start: raise ValueError("End must be after start")
        return self

class WeatherReq(WindowReq):
    node: str
    temperature_c: float = Field(default=4, ge=-80, le=65)
    condition: str = Field(default="Heavy Snow", min_length=1, max_length=100)
    rain_mm: float = Field(default=0, ge=0, le=500)
    snow_cm: float = Field(default=5, ge=0, le=500)
    visibility_m: float = Field(default=500, ge=0, le=100000)
    wind_kmh: float = Field(default=35, ge=0, le=400)
    severity: Literal["LOW","MEDIUM","HIGH"] = "HIGH"

class EventReq(WindowReq):
    kind: Literal["traffic","hub_delay","closure"]
    node: Optional[str] = None
    origin: Optional[str] = None
    destination: Optional[str] = None
    minutes: int = Field(default=120, ge=0, le=10080)
    reason: str = Field(min_length=1, max_length=500)

class DecisionReq(BaseModel):
    shipment_id: str
    action: Literal["accept","keep","defer"]
    option: int = Field(default=0, ge=0)
    revision: int
    reason: str = Field(min_length=3, max_length=1000)
    acknowledge_deadline: bool = False

def _node(nid):
    if nid not in S["network"]["nodes"]: raise ValueError("Unknown hub")

@app.get("/api/operations")
def operations():
    result = S["operations"].snapshot()
    result["weather"] = [evaluate(r) for r in result["weather"]]
    result["thresholds"] = THRESHOLDS
    return result

@app.post("/api/weather-records")
@serialized
def add_weather(req: WeatherReq):
    _node(req.node)
    row=S["operations"].put("weather",req.model_dump(mode="json"))
    _audit("weather_sample",f"{req.node}: {req.condition}","MANUAL SAMPLE")
    return evaluate(row)

@app.put("/api/weather-records/{rid}")
@serialized
def edit_weather(rid: str, req: WeatherReq):
    _node(req.node)
    if not any(r["id"]==rid for r in S["operations"].data["weather"]): raise HTTPException(404,"Unknown weather record")
    return evaluate(S["operations"].put("weather",req.model_dump(mode="json"),rid))

@app.delete("/api/weather-records/{rid}")
@serialized
def delete_weather(rid: str):
    S["operations"].remove("weather",rid)
    return {"ok":True}

@app.post("/api/events")
@serialized
def add_event(req: EventReq):
    if req.kind=="traffic":
        _node(req.origin); _node(req.destination)
        if req.origin==req.destination: raise ValueError("Choose different endpoints")
    else: _node(req.node)
    row=S["operations"].put("events",req.model_dump(mode="json"))
    _audit("scenario_event",req.reason,"SIMULATED / MANAGER INPUT")
    return row

@app.delete("/api/events/{rid}")
@serialized
def resolve_event(rid: str):
    S["operations"].remove("events",rid)
    _audit("event_resolved",rid,"MANAGER INPUT")
    return {"ok":True}

@app.post("/api/shipments/{sid}/replan")
@serialized
def replan_shipment(sid: str):
    if not S["ships"].get(sid): raise HTTPException(404,"Unknown shipment")
    with LOCK:
        return S["ships"].replan(sid)

@app.post("/api/decisions")
@serialized
def decision(req: DecisionReq):
    with LOCK:
        if req.revision!=S["operations"].data["revision"]: raise HTTPException(409,"Conditions changed. Recalculate before deciding.")
        s=S["ships"].get(req.shipment_id)
        if not s: raise HTTPException(404,"Unknown shipment")
        if req.option>=len(s["options"]): raise ValueError("Invalid option")
        option=s["options"][req.option]
        if option.get("revision",-1)!=req.revision: raise HTTPException(409,"Recalculate shipment options first")
        previous_route=list(s["route"])
        if req.action=="accept":
            _, warning=S["ships"].schedule(req.shipment_id,req.option,req.acknowledge_deadline)
            if warning: raise HTTPException(409,warning)
        row=S["operations"].put("decisions",{**req.model_dump(),"path":option["path"],"eta":option["eta"],"previous_route":previous_route})
        _audit("manager_decision",f"{req.shipment_id}: {req.action} — {req.reason}","MANAGER INPUT")
        return row

@app.get("/api/assumptions")
def assumptions():
    import json
    from pathlib import Path
    return json.loads((Path(__file__).parent / "assumptions.json").read_text(encoding="utf-8"))


class MapReq(BaseModel):
    geometry: list[tuple[float,float]] = Field(min_length=2,max_length=50000)
    at: AwareDatetime
    @model_validator(mode="after")
    def bounds(self):
        if any(not (-180<=lon<=180 and -85<=lat<=85) for lon,lat in self.geometry): raise ValueError("Invalid coordinates")
        return self

@app.post("/api/map-conditions")
def map_conditions(req: MapReq):
    from .live import now
    coords=req.geometry
    samples=[coords[round((len(coords)-1)*f)] for f in [0,.25,.5,.75,1]]
    points=[(lat,lon) for lon,lat in samples]
    weather=S["providers"].forecasts.fetch(points,[req.at]*len(points))
    # Incidents and flow show current conditions only, never future predictions.
    incidents=S["providers"].tomtom.incidents(coords) if abs((req.at-now()).total_seconds())<3600 else {"status":"CURRENT_ONLY","items":[]}
    return {"weather":weather,"incidents":incidents,"traffic_configured":bool(S["providers"].tomtom.key),"at":req.at.isoformat(),"fetched_at":_now_iso(),"note":"Forecast preview does not change saved departure or ETA. Recalculate the plan to refresh arrival estimates."}

@app.get("/api/traffic-tiles/{z}/{x}/{y}.png")
def traffic_tile(z:int,x:int,y:int):
    if not (0<=z<=22 and 0<=x<2**z and 0<=y<2**z): raise HTTPException(422,"Invalid tile")
    if not S["providers"].tomtom.key: raise HTTPException(503,"TOMTOM_API_KEY not configured")
    tile=S["providers"].tomtom.tile(z,x,y)
    if tile is None: raise HTTPException(502,"Traffic tiles temporarily unavailable")
    return Response(content=tile,media_type="image/png",headers={"Cache-Control":"private, max-age=120"})
