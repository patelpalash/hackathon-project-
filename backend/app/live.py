"""Cached live forecast and TomTom integrations; credentials never leave backend."""
import math
import os
import time
from datetime import datetime, timedelta, timezone
import httpx
from .weather_rules import evaluate

UTC=timezone.utc

def now(): return datetime.now(UTC)

def condition(code):
    if code in (71,73,75,77,85,86): return "Heavy Snow" if code in (75,86) else "Snow"
    if code in (95,96,99): return "Thunderstorm"
    if code in (45,48): return "Fog"
    if code in (65,67,82): return "Heavy Rain"
    if code in (51,53,55,61,63,66,80,81): return "Rain"
    return "Clear" if code==0 else "Cloudy"

class Forecasts:
    def __init__(self): self.cache={}; self.last_success=None; self.error=None; self.retry_after=0
    def fetch(self, points, times):
        keys=[(round(p[0],3),round(p[1],3)) for p in points]
        missing=list(dict.fromkeys(k for k in keys if k not in self.cache or time.time()-self.cache[k][0]>900))
        if missing and time.time()>=self.retry_after:
            try:
                r=httpx.get("https://api.open-meteo.com/v1/forecast",params={"latitude":",".join(str(k[0]) for k in missing),"longitude":",".join(str(k[1]) for k in missing),"hourly":"temperature_2m,precipitation,snowfall,visibility,wind_speed_10m,weather_code","forecast_days":16,"past_days":1,"timezone":"UTC","timeformat":"unixtime"},timeout=5)
                r.raise_for_status(); payload=r.json(); payload=payload if isinstance(payload,list) else [payload]
                if len(payload)!=len(missing): raise ValueError("Incomplete forecast response")
                for k,item in zip(missing,payload): self.cache[k]=(time.time(),item["hourly"])
                self.last_success=now().isoformat(); self.error=None
            except Exception as e: self.error=type(e).__name__; self.retry_after=time.time()+60
        rows=[]
        for index,(key,at) in enumerate(zip(keys,times)):
            cached=self.cache.get(key)
            row={"id":f"wx-{key[0]}-{key[1]}","lat":key[0],"lon":key[1],"source":"Open-Meteo forecast","valid_at":at.isoformat(),"node":"route","name":f"Route sample {index+1}"}
            if not cached: rows.append({**row,"status":"UNAVAILABLE","error":self.error}); continue
            fetched,hourly=cached; ts=at.timestamp(); hour=min(range(len(hourly["time"])),key=lambda i:abs(hourly["time"][i]-ts))
            if abs(hourly["time"][hour]-ts)>3600: rows.append({**row,"status":"OUT_OF_RANGE"});continue
            values={k:v[hour] for k,v in hourly.items() if k!="time"}
            if any(v is None for v in values.values()): rows.append({**row,"status":"UNAVAILABLE"});continue
            valid=datetime.fromtimestamp(hourly["time"][hour],UTC)
            record={**row,"start":valid.isoformat(),"end":(valid+timedelta(hours=1)).isoformat(),"temperature_c":values["temperature_2m"],"condition":condition(values["weather_code"]),"rain_mm":values["precipitation"],"snow_cm":values["snowfall"],"visibility_m":values["visibility"],"wind_kmh":values["wind_speed_10m"],"severity":"LOW"}
            row={**evaluate(record),"source":"Open-Meteo forecast","status":"FORECAST" if time.time()-fetched<=900 else "STALE","fetched_at":datetime.fromtimestamp(fetched,UTC).isoformat(),"valid_at":valid.isoformat()}
            rows.append(row)
        return rows

class TomTom:
    def __init__(self):
        self.key=os.environ.get("TOMTOM_API_KEY",""); self.cache={}; self.last_success=None; self.error=None
    def get(self, url, params, ttl=120):
        if not self.key: return None
        ck=(url,str(sorted(params.items())))
        if ck in self.cache and time.time()-self.cache[ck][0]<ttl:return self.cache[ck][1]
        try:
            r=httpx.get(url,params={**params,"key":self.key},timeout=5);r.raise_for_status()
            payload=r.json(); self.cache[ck]=(time.time(),payload);self.last_success=now().isoformat();self.error=None
            return payload
        except Exception as e:self.error=type(e).__name__;return None
    def route(self,a,b,depart,truck):
        if not self.key:return None
        if depart<now()-timedelta(minutes=5):return None
        params={"traffic":"true","travelMode":"truck","routeType":"fastest","computeTravelTimeFor":"all","sectionType":"traffic","departAt":depart.replace(second=0,microsecond=0).isoformat(),"vehicleHeight":truck["height_m"],"vehicleWidth":truck["width_m"],"vehicleLength":truck["length_m"],"vehicleWeight":truck["gross_weight_kg"],"vehicleMaxSpeed":80}
        doc=self.get(f"https://api.tomtom.com/routing/1/calculateRoute/{a[0]},{a[1]}:{b[0]},{b[1]}/json",params)
        if not doc or not doc.get("routes"):return None
        route=doc["routes"][0];summary=route["summary"]
        points=[[p["longitude"],p["latitude"]] for leg in route["legs"] for p in leg["points"]]
        total=math.ceil(summary["travelTimeInSeconds"]/60);delay=min(total,math.ceil(summary.get("trafficDelayInSeconds",0)/60))
        sections=[]
        for s in route.get("sections",[]):
            if s.get("sectionType")=="TRAFFIC":
                sections.append({"geometry":points[s["startPointIndex"]:s["endPointIndex"]+1],"delay_minutes":round(s.get("delayInSeconds",0)/60,1),"description":s.get("simpleCategory","Traffic"),"source":"TomTom"})
        return {"geometry":points,"distance_km":round(summary["lengthInMeters"]/1000,1),"duration_minutes":total,"traffic_minutes":delay,"traffic_sections":sections,"source":"TomTom traffic-aware truck route","fetched_at":self.last_success}
    def incidents(self,coords):
        if not self.key:return {"status":"NOT_CONFIGURED","items":[]}
        # Request compact tiles of the route corridor, within provider bounding-box limits.
        selected=coords[::max(1,len(coords)//5)][:6]; items={}; failed=False
        for lon,lat in selected:
            bbox=f"{lon-.15},{lat-.1},{lon+.15},{lat+.1}"
            fields="{incidents{type,geometry{type,coordinates},properties{id,iconCategory,magnitudeOfDelay,events{description,code},startTime,endTime,from,to,delay}}}"
            doc=self.get("https://api.tomtom.com/traffic/services/5/incidentDetails",{"bbox":bbox,"fields":fields,"language":"en-GB","timeValidityFilter":"present"})
            if doc is None: failed=True
            for item in (doc or {}).get("incidents",[]):
                props=item["properties"];items[props["id"]]={"id":props["id"],"geometry":item["geometry"],"description":"; ".join(e["description"] for e in props.get("events",[])),"delay_minutes":round((props.get("delay") or 0)/60,1),"source":"TomTom","from":props.get("from"),"to":props.get("to"),"end":props.get("endTime")}
        return {"status":"ERROR" if failed else "LIVE","items":list(items.values()),"fetched_at":self.last_success}
    def tile(self,z,x,y):
        if not self.key: return None
        ck=("tile",z,x,y);cached=self.cache.get(ck)
        if cached and time.time()-cached[0]<120:return cached[1]
        try:
            r=httpx.get(f"https://api.tomtom.com/traffic/map/4/tile/flow/relative0/{z}/{x}/{y}.png",params={"key":self.key,"tileSize":256},timeout=5);r.raise_for_status()
            self.cache[ck]=(time.time(),r.content)
            if len(self.cache)>1200:self.cache={ck:self.cache[ck]}
            return r.content
        except Exception as e:self.error=type(e).__name__;return None

DEFAULT_TRUCK={"height_m":4.0,"width_m":2.55,"length_m":16.5,"gross_weight_kg":40000}
