from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import json
import pytest
from fastapi.testclient import TestClient
from app.restrictions import drive_with_restrictions, BERLIN
from app.weekend import hub_release
from app.hub_selection import select_hubs
from app.weather_rules import evaluate
from app.eta import compute_journey, _haversine_km
from app.operations import Operations

def dt(s): return datetime.fromisoformat(s)

class Road:
    def leg(self,a,b):
        km=round(_haversine_km(a,b)*1.1,1)
        return {"geometry":[[a[1],a[0]],[b[1],b[0]]],"distance_km":km,"duration_minutes":max(1,round(km/65*60)),"source":"TEST ROAD"}
class Traffic:
    def leg(self,*args): return {"delay_minutes":0}
    def status(self): return "NOT_CONFIGURED"
class Providers:
    def __init__(self,*args): self.routing=Road(); self.traffic=Traffic()
    def all(self): return []

def test_saturday_arrival_waits_until_monday():
    arrival=dt("2026-09-19T12:00:00+02:00")
    release=hub_release(arrival,arrival+timedelta(hours=2))
    assert release.astimezone(BERLIN).isoformat()=="2026-09-21T00:00:00+02:00"

def test_sunday_22_is_still_held_by_business_policy():
    journey=drive_with_restrictions(dt("2026-09-20T22:30:00+02:00"),60,{})
    assert journey["waiting_minutes"]==90
    assert journey["arrival"].astimezone(BERLIN).isoformat()=="2026-09-21T01:00:00+02:00"

def test_subminute_start_and_consecutive_holiday():
    dep=dt("2026-09-19T23:59:30+02:00")
    journey=drive_with_restrictions(dep,120,{"2026-09-21":"Test holiday"})
    assert journey["arrival"]-dep>=timedelta(hours=46)
    assert len(journey["pauses"])==2
    assert journey["arrival"].astimezone(BERLIN).weekday()==0

def test_sunday_dst_length():
    result=drive_with_restrictions(dt("2026-10-25T00:00:00+02:00"),60,{})
    assert result["waiting_minutes"]==25*60
    assert result["arrival"].astimezone(BERLIN).hour==1

def test_dynamic_hub_relevance_availability_and_destination_priority():
    nodes=[{"id":i,"name":i,"lat":49.,"lon":lon} for i,lon in [("A",8),("B",9.8),("C",9.2),("D",10)]]
    nodes.append({"id":"HN","name":"Heilbronn","lat":52.,"lon":8.})
    road=Road(); base=road.leg((49,8),(49,10))
    hubs=select_hubs(nodes[0],nodes[3],nodes,base,road,{})
    assert hubs[0]["hub"]=="B" and "HN" not in [h["hub"] for h in hubs]
    assert select_hubs(nodes[0],nodes[3],nodes,base,road,{"blocked":{"B"}})[0]["hub"]=="C"
    assert select_hubs(nodes[0],nodes[3],nodes,{"geometry":None},road,{})==[]

def test_weekend_timeline_and_weather_scope(tmp_path,monkeypatch):
    monkeypatch.setenv("STORE_DIR",str(tmp_path)); ops=Operations()
    nodes={i:{"id":i,"name":i,"lat":49.,"lon":x,"type":"branch"} for i,x in [("A",8),("B",8.5),("C",9)]}
    net={"nodes":nodes,"edges":{}}
    sample={"node":"A","start":"2026-09-19T00:00:00Z","end":"2026-09-20T00:00:00Z","temperature_c":4,"condition":"Heavy Snow","rain_mm":0,"snow_cm":5,"visibility_m":500,"wind_kmh":35,"severity":"HIGH"}
    ops.put("weather",sample)
    j=compute_journey(net,{}, {},{},Providers(),"A","C",dt("2026-09-19T06:00:00+00:00"),["A","B","C"],ops)
    assert j["components"]["weather"]==120
    hold=next(s for s in j["steps"] if s["type"]=="weekend_hold")
    assert hold["location"]=="B" and dt(hold["end"]).astimezone(BERLIN).weekday()==0
    assert all(dt(s["start"]).astimezone(BERLIN).weekday()!=6 for s in j["steps"] if s["type"]=="drive")
    assert sum(s["minutes"] for s in j["steps"])==j["total_minutes"]
    later=compute_journey(net,{}, {},{},Providers(),"A","C",dt("2026-09-22T06:00:00+00:00"),["A","C"],ops)
    assert later["components"]["weather"]==0

@pytest.fixture
def client(tmp_path,monkeypatch):
    from app import main, shipments
    monkeypatch.setenv("STORE_DIR",str(tmp_path))
    monkeypatch.setattr(main,"DATA_DIR",str(Path(__file__).resolve().parents[1]/"data"/"raw"))
    monkeypatch.setattr(main,"Providers",Providers)
    monkeypatch.setattr(shipments,"STORE_DIR",str(tmp_path))
    monkeypatch.setattr(shipments,"STORE",str(tmp_path/"shipments.json"))
    with TestClient(main.app) as c: yield c

def test_weather_edit_validation_and_persistence(client):
    body={"node":"HN","start":"2026-09-21T06:00:00Z","end":"2026-09-21T12:00:00Z","condition":"Heavy Snow"}
    r=client.post("/api/weather-records",json=body); assert r.status_code==200,r.text
    rid=r.json()["id"]; assert r.json()["alert"]
    r=client.put("/api/weather-records/"+rid,json={**body,"condition":"Clear","severity":"LOW","visibility_m":10000,"wind_kmh":5,"snow_cm":0})
    assert not r.json()["alert"]
    assert len(Operations().data["weather"])==1
    assert client.post("/api/weather-records",json={**body,"end":body["start"]}).status_code==422
    assert client.post("/api/route",json={"origin":"R16","destination":"R21","depart_at":"invalid"}).status_code==422

def test_traffic_recompute_and_manager_decision(client):
    body={"origin":"R16","destination":"R21","planned_departure":"2026-09-22T06:00:00Z","weight_kg":8000,"value_eur":180000,"required_delivery":"2026-09-25T06:00:00Z"}
    ship=client.post("/api/shipments",json=body).json(); sid=ship["id"]
    old_direct=next(o for o in ship["options"] if len(o["path"])==2)
    event=client.post("/api/events",json={"kind":"traffic","origin":"R16","destination":"R21","start":"2026-09-22T00:00:00Z","end":"2026-09-24T00:00:00Z","minutes":180,"reason":"Test heavy traffic"})
    assert event.status_code==200,event.text
    assert client.post(f"/api/shipments/{sid}/schedule").status_code==422
    refreshed=client.post(f"/api/shipments/{sid}/replan").json()
    new_direct=next(o for o in refreshed["options"] if len(o["path"])==2)
    assert new_direct["total_minutes"]-old_direct["total_minutes"]==180
    option=len(refreshed["options"])-1
    decision={"shipment_id":sid,"action":"accept","option":option,"revision":refreshed["options"][option]["revision"],"quote_id":refreshed["options"][option]["quote_id"],"reason":"Reviewed route impact"}
    assert client.post("/api/decisions",json={**decision,"revision":-1}).status_code==409
    r=client.post("/api/decisions",json=decision); assert r.status_code==200,r.text
    saved=client.get(f"/api/shipments/{sid}").json()
    assert saved["route"]==refreshed["options"][option]["path"]
    assert saved["current_eta"]==refreshed["options"][option]["eta"]
    assert Operations().data["decisions"][-1]["action"]=="accept"

def test_forced_schedule_persists_selected_option(client):
    from app import shipments
    body={"origin":"R16","destination":"R21","planned_departure":"2026-09-22T06:00:00Z","required_delivery":"2026-09-22T06:01:00Z"}
    ship=client.post("/api/shipments",json=body).json(); sid=ship["id"]; i=len(ship["options"])-1
    params={"option":i,"quote_id":ship["options"][i]["quote_id"],"reason":"Manager reviewed deadline"}
    assert client.post(f"/api/shipments/{sid}/schedule",params=params).status_code==409
    r=client.post(f"/api/shipments/{sid}/schedule",params={**params,"force":True}); assert r.json()["scheduled"]
    saved=json.loads(Path(shipments.STORE).read_text())[sid]
    assert saved["current_eta"]==ship["options"][i]["eta"] and saved["selected_option"]==i


def test_cost_objective_and_historical_benchmark(client):
    payload={"origin":"R16","destination":"R21","planned_departure":"2026-09-22T06:00:00Z","required_delivery":"2026-09-28T06:00:00Z","optimization":"cost"}
    response=client.post("/api/shipments",json=payload)
    assert response.status_code==200,response.text
    ship=response.json(); choices=ship["options"]
    assert ship["optimization"]=="cost"
    assert choices[0]["cost"]["transport_eur"]==min(o["cost"]["transport_eur"] for o in choices)
    for option in choices:
        assert option["historical_comparison"]["normalized_cost_eur"] is not None
        assert option["historical_comparison"]["time_difference_minutes"] is None
    direct=next(o for o in choices if len(o["path"])==2)
    assert choices[0]["comparison"]["money_saved_eur"]==direct["cost"]["transport_eur"]-choices[0]["cost"]["transport_eur"]
    assert client.get("/api/savings").json()["per_shipment"]

def test_live_traffic_is_counted_once():
    providers=Providers()
    providers.tomtom=SimpleNamespace(key="test",route=lambda *args:{"duration_minutes":180,"traffic_minutes":30,"geometry":[[8,49],[9,49]],"distance_km":150,"source":"TomTom test"})
    nodes={n:{"id":n,"name":n,"type":"branch","lat":49,"lon":lon} for n,lon in [("A",8),("B",9)]}
    j=compute_journey({"nodes":nodes,"edges":{}},{},{},{},providers,"A","B",dt("2026-09-22T06:00:00+00:00"))
    assert j["total_minutes"]==300
    assert j["components"]["transport"]==150 and j["components"]["traffic"]==30

def test_live_forecast_threshold_and_timestamp(monkeypatch):
    from app.live import Forecasts
    import httpx
    at=dt("2026-09-22T08:00:00+00:00")
    payload={"hourly":{"time":[at.timestamp()],"temperature_2m":[4],"precipitation":[0],"snowfall":[5],"visibility":[500],"wind_speed_10m":[35],"weather_code":[75]}}
    monkeypatch.setattr(httpx,"get",lambda *args,**kwargs:SimpleNamespace(raise_for_status=lambda:None,json=lambda:payload))
    rows=Forecasts().fetch([(49,9)],[at])
    assert rows[0]["source"]=="Open-Meteo forecast" and rows[0]["status"]=="FORECAST"
    assert rows[0]["delay_minutes"]==120 and rows[0]["valid_at"]==at.isoformat()


def test_timetable_cutoff_weekend_and_holiday():
    from app.schedules import next_departure
    service={"origin":"A","destination":"B","weekdays":[0,1,2,3,4,5,6],"departure_time":"18:00","timezone":"Europe/Berlin","cutoff_minutes":30,"source":"TEST"}
    ready=dt("2026-09-19T17:31:00+02:00")
    departure,_=next_departure(ready,"A","B",[service],{"2026-09-21":"Test holiday"})
    assert departure.astimezone(BERLIN).isoformat()=="2026-09-22T18:00:00+02:00"
    departure,_=next_departure(dt("2026-09-22T17:30:00+02:00"),"A","B",[service],{})
    assert departure.astimezone(BERLIN).isoformat()=="2026-09-22T18:00:00+02:00"


def test_live_change_rejects_approval_without_manual_revision(client,monkeypatch):
    from app import main
    payload={"origin":"R16","destination":"R21","planned_departure":"2026-09-22T06:00:00Z","required_delivery":"2026-09-25T18:00:00Z"}
    ship=client.post("/api/shipments",json=payload).json(); sid=ship["id"]
    option=ship["options"][0]
    before=json.dumps(ship["accepted_plan"],sort_keys=True)
    base=main.S["providers"].routing.leg
    monkeypatch.setattr(main.S["providers"].routing,"leg",lambda *args:{**base(*args),"duration_minutes":base(*args)["duration_minutes"]+45})
    decision={"shipment_id":sid,"action":"accept","option":0,"revision":option["revision"],"quote_id":option["quote_id"],"reason":"Reviewed live quote"}
    result=client.post("/api/decisions",json=decision)
    assert result.status_code==422,result.text
    assert "Live conditions changed" in result.text
    saved=client.get(f"/api/shipments/{sid}").json()
    assert json.dumps(saved["accepted_plan"],sort_keys=True)==before
    assert client.post("/api/decisions",json=decision).status_code==409


def test_demo_isolation_approval_and_actual_exclusion(client):
    initial=client.get("/api/operations").json()
    ship=client.post("/api/demo/start").json(); sid=ship["id"]
    baseline=ship["accepted_plan"]
    changed=client.post(f"/api/demo/{sid}/disruption").json()
    assert client.get("/api/operations").json()==initial
    assert changed["accepted_plan"]==baseline and changed["plan_change"]["material"]
    assert changed["options"][0]["total_minutes"]<next(o for o in changed["options"] if len(o["path"])==2)["total_minutes"]
    o=changed["options"][0]
    result=client.post("/api/decisions",json={"shipment_id":sid,"action":"accept","option":0,"revision":o["revision"],"quote_id":o["quote_id"],"reason":"Approve demo alternative"})
    assert result.status_code==200,result.text
    client.post(f"/api/shipments/{sid}/status?status=DELIVERED")
    outcome=client.post(f"/api/shipments/{sid}/outcome",json={"actual_departure":"2026-09-22T06:00:00Z","actual_arrival":o["eta"],"actual_cost_eur":o["cost"]["transport_eur"]-10})
    assert outcome.status_code==200,outcome.text
    assert outcome.json()["actual"]["cost_error_eur"]==-10
    assert client.get("/api/performance").json()["samples"]==0
    assert not any(r["id"]==sid for r in client.get("/api/savings").json()["per_shipment"])


def test_schedule_timeline_and_signed_savings(client):
    service={"origin":"R16","destination":"R21","weekdays":[0,1,2,3,4],"departure_time":"18:00","timezone":"Europe/Berlin","cutoff_minutes":30}
    assert client.post("/api/services",json=service).status_code==200
    payload={"origin":"R16","destination":"R21","planned_departure":"2026-09-22T06:00:00Z","required_delivery":"2026-09-25T18:00:00Z"}
    ship=client.post("/api/shipments",json=payload).json()
    direct=next(o for o in ship["options"] if len(o["path"])==2)
    wait=next(step for step in direct["steps"] if step["type"]=="schedule_wait")
    assert dt(wait["end"]).astimezone(BERLIN).hour==18
    assert sum(step["minutes"] for step in direct["steps"])==direct["total_minutes"]
    for option in ship["options"]:
        assert option["comparison"]["money_saved_eur"]==direct["cost"]["transport_eur"]-option["cost"]["transport_eur"]
    assert any(o["comparison"]["money_saved_eur"]<0 for o in ship["options"])
