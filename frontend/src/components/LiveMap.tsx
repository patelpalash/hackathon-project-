import { useEffect, useMemo, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { CloudSun, RefreshCw, Expand, LocateFixed, Car, TriangleAlert } from "lucide-react";
import { api, BASE } from "../api/client";
import type { NetNode, RouteOption, MapConditions, LiveWeather } from "../api/types";
import { dt } from "../lib";
const STYLE="https://tiles.openfreemap.org/styles/liberty";
const HUB="#1a3682", BRANCH="#66738c", ROUTE="#17765e";
function hasWebGL(){try{const c=document.createElement("canvas");return !!(c.getContext("webgl2")||c.getContext("webgl"))}catch{return false}}
function popup(text:string){return new maplibregl.Popup({offset:15,maxWidth:"280px"}).setText(text)}
export function LiveMap({nodes,path,geometry,alternatives=[],onSelect,routeWeather=[],trafficSections=[],onRefresh}:{nodes:NetNode[];path:string[];geometry?:number[][]|null;alternatives?:RouteOption[];onSelect?:(i:number)=>void;routeWeather?:LiveWeather[];trafficSections?:{geometry:number[][];delay_minutes:number;description:string}[];onRefresh?:()=>void}){
 const ref=useRef<HTMLDivElement|null>(null),shell=useRef<HTMLDivElement|null>(null),map=useRef<maplibregl.Map|null>(null);
 const markers=useRef<maplibregl.Marker[]>([]),weatherMarkers=useRef<maplibregl.Marker[]>([]),incidentMarkers=useRef<maplibregl.Marker[]>([]);
 const [fallback,setFallback]=useState(!hasWebGL()),[ready,setReady]=useState(false),[data,setData]=useState<MapConditions|null>(null),[error,setError]=useState(""),[loading,setLoading]=useState(false),[tick,setTick]=useState(0);
 const [wx,setWx]=useState(true),[traffic,setTraffic]=useState(true),[incidents,setIncidents]=useState(true),[hubs,setHubs]=useState(true),[offset,setOffset]=useState(-1);
 const byId=useMemo(()=>new Map(nodes.map(n=>[n.id,n])),[nodes]);
 const coords=useMemo(()=>geometry?.length?geometry:path.flatMap(id=>{const n=byId.get(id);return n?[[n.lon,n.lat]]:[]}),[geometry,path,byId]);
 const coordKey=JSON.stringify(coords);
 const fit=()=>{if(!map.current||coords.length<2)return;const b=new maplibregl.LngLatBounds();coords.forEach(p=>b.extend([p[0],p[1]]));map.current.fitBounds(b,{padding:45,maxZoom:9,duration:450})};
 useEffect(()=>{let alive=true;setLoading(true);setError("");setData(null);const at=new Date(Date.now()+Math.max(0,offset)*3600000).toISOString();api.mapConditions(JSON.parse(coordKey),at).then(r=>{if(alive)setData(r)}).catch(e=>{if(alive)setError(String(e))}).finally(()=>{if(alive)setLoading(false)});return()=>{alive=false}},[coordKey,offset,tick]);
 useEffect(()=>{const timer=setInterval(()=>setTick(t=>t+1),120000);return()=>clearInterval(timer)},[]);
 useEffect(()=>{if(fallback||!ref.current)return;let m:maplibregl.Map;try{m=new maplibregl.Map({container:ref.current,style:STYLE,center:[10.2,51],zoom:5,attributionControl:{compact:true}})}catch{setFallback(true);return}map.current=m;m.on("load",()=>setReady(true));m.on("error",e=>{const message=String(e.error?.message??"");if(/traffic-tiles/.test(message)){setError("Traffic layer unavailable. Road routes remain visible.")}else if(!m.isStyleLoaded()&&/style|fetch|network/i.test(message)){setFallback(true)}});m.addControl(new maplibregl.NavigationControl(),"top-right");m.addControl(new maplibregl.ScaleControl());return()=>{setReady(false);m.remove();map.current=null}},[fallback]);
 useEffect(()=>{const m=map.current;if(!m||!ready)return;
 const features=alternatives.filter(o=>o.geometry?.length).map(o=>({type:"Feature" as const,properties:{index:alternatives.indexOf(o)},geometry:{type:"LineString" as const,coordinates:o.geometry!}}));
 const altData={type:"FeatureCollection" as const,features};const alt=m.getSource("alternatives") as maplibregl.GeoJSONSource|undefined;
 if(alt)alt.setData(altData);else{m.addSource("alternatives",{type:"geojson",data:altData});m.addLayer({id:"alternatives-line",type:"line",source:"alternatives",paint:{"line-color":"#82909c","line-width":5,"line-opacity":.45}})}
 const line={type:"FeatureCollection" as const,features:coords.length>1?[{type:"Feature" as const,properties:{},geometry:{type:"LineString" as const,coordinates:coords}}]:[]};const src=m.getSource("route") as maplibregl.GeoJSONSource|undefined;
 if(src)src.setData(line);else{m.addSource("route",{type:"geojson",data:line});m.addLayer({id:"route-l",type:"line",source:"route",paint:{"line-color":ROUTE,"line-width":5,"line-opacity":.95}})}
 const sections={type:"FeatureCollection" as const,features:trafficSections.filter(s=>s.geometry.length>1).map(s=>({type:"Feature" as const,properties:{delay:s.delay_minutes,description:s.description},geometry:{type:"LineString" as const,coordinates:s.geometry}}))};const sectionSource=m.getSource("traffic-sections") as maplibregl.GeoJSONSource|undefined;
 if(sectionSource)sectionSource.setData(sections);else{m.addSource("traffic-sections",{type:"geojson",data:sections});m.addLayer({id:"traffic-sections-line",type:"line",source:"traffic-sections",paint:{"line-color":"#de7043","line-width":7}})}
 const click=(e:maplibregl.MapLayerMouseEvent)=>{const i=Number(e.features?.[0]?.properties?.index);if(Number.isInteger(i))onSelect?.(i)};
 const sectionClick=(e:maplibregl.MapLayerMouseEvent)=>{const p=e.features?.[0]?.properties;popup(`${p?.description??"Traffic"} · ${p?.delay??0} minutes provider traffic impact (included in ETA)`).setLngLat(e.lngLat).addTo(m)};
 m.on("click","alternatives-line",click);m.on("click","traffic-sections-line",sectionClick);fit();return()=>{m.off("click","alternatives-line",click);m.off("click","traffic-sections-line",sectionClick)}
 },[ready,coordKey,alternatives,trafficSections,onSelect]);
 useEffect(()=>{const m=map.current;if(!m||!ready)return;markers.current.forEach(x=>x.remove());markers.current=[];if(!hubs)return;const onPath=new Set(path);markers.current=nodes.map(n=>{const el=document.createElement("button");el.setAttribute("aria-label",`${n.name} facility`);el.className=`facility-marker ${onPath.has(n.id)?"on-route":""}`;return new maplibregl.Marker({element:el}).setLngLat([n.lon,n.lat]).setPopup(popup(`${n.name} · ${n.type} · ${n.source}`)).addTo(m)})},[ready,nodes,path,hubs]);
 const forecasts=offset===-1&&routeWeather.length?routeWeather:data?.weather??[];
 useEffect(()=>{const m=map.current;if(!m||!ready)return;weatherMarkers.current.forEach(x=>x.remove());weatherMarkers.current=[];if(!wx)return;const unique=new Map(forecasts.map(w=>[w.id,w]));weatherMarkers.current=[...unique.values()].map(w=>{const el=document.createElement("button");el.className=`weather-marker wx-${w.level??"unknown"}`;el.textContent=w.condition?.includes("Snow")?"❄":w.condition?.includes("Rain")?"☂":w.condition==="Clear"?"☀":"☁";el.title=`${w.condition??w.status} · ${w.temperature_c??"—"}°C`;return new maplibregl.Marker({element:el,offset:[0,-20]}).setLngLat([w.lon,w.lat]).setPopup(popup(`${w.source} · ${w.status}
${w.condition??"Forecast unavailable"} · ${w.temperature_c??"—"}°C
Wind ${w.wind_kmh??"—"} km/h · visibility ${w.visibility_m??"—"} m
Valid ${dt(w.valid_at)}
Retrieved ${dt(w.fetched_at)}
Weather impact rule: +${w.delay_minutes??0}m (estimate)`)).addTo(m)})},[ready,forecasts,wx]);
 useEffect(()=>{const m=map.current;if(!m||!ready)return;incidentMarkers.current.forEach(x=>x.remove());incidentMarkers.current=[];if(incidents&&offset<=0){incidentMarkers.current=(data?.incidents.items??[]).map(i=>{const c=i.geometry.type==="Point"?i.geometry.coordinates as number[]:(i.geometry.coordinates as number[][])[0];const el=document.createElement("button");el.className="incident-marker";el.textContent="!";el.title=i.description;return new maplibregl.Marker({element:el}).setLngLat([c[0],c[1]]).setPopup(popup(`${i.description}
${i.delay_minutes}m reported delay · ${i.source}
Current incident near route; exact impact comes from routing.`)).addTo(m)})}
 if(data?.traffic_configured&&!m.getSource("traffic-flow")){m.addSource("traffic-flow",{type:"raster",tiles:[`${new URL(BASE,window.location.href).href.replace(/\/$/,"")}/traffic-tiles/{z}/{x}/{y}.png`],tileSize:256,attribution:"Traffic © TomTom"});m.addLayer({id:"traffic-flow-layer",type:"raster",source:"traffic-flow",paint:{"raster-opacity":.7}},"alternatives-line")}
 if(m.getLayer("traffic-flow-layer"))m.setLayoutProperty("traffic-flow-layer","visibility",traffic&&offset<=0?"visible":"none");if(m.getLayer("traffic-sections-line"))m.setLayoutProperty("traffic-sections-line","visibility",traffic&&offset<=0?"visible":"none");
 },[ready,data,traffic,incidents,offset]);
 const refresh=()=>{setTick(t=>t+1);onRefresh?.()};
 return <div className="live-map-shell" ref={shell}><div className="live-controls"><div className="layer-toggles">{[["Weather",wx,setWx,CloudSun],["Traffic",traffic,setTraffic,Car],["Incidents",incidents,setIncidents,TriangleAlert],["Hubs",hubs,setHubs,LocateFixed]].map(([label,enabled,setter,Icon])=>{const I=Icon as typeof CloudSun;return <button key={String(label)} aria-pressed={enabled as boolean} onClick={()=>(setter as (v:boolean)=>void)(!enabled)}><I size={13}/>{String(label)}</button>})}</div><div className="map-actions"><button aria-label="Fit route" onClick={fit}><LocateFixed size={15}/></button><button aria-label="Fullscreen map" onClick={()=>{if(document.fullscreenElement)void document.exitFullscreen();else void shell.current?.requestFullscreen().catch(()=>setError("Fullscreen is unavailable in this browser"))}}><Expand size={15}/></button><button disabled={loading} aria-label="Refresh live conditions and ETA" onClick={refresh}><RefreshCw size={15} className={loading?"spin":""}/></button></div></div>
 <div className="forecast-controls"><label>Weather preview<select aria-label="Weather forecast time" value={offset} onChange={e=>setOffset(Number(e.target.value))}><option value={-1}>At planned passage</option><option value={0}>Now</option><option value={3}>In 3 hours</option><option value={6}>In 6 hours</option><option value={12}>In 12 hours</option></select></label><span>{loading?"Fetching conditions…":`Updated ${data?dt(data.fetched_at):"—"}`}<small>{offset>0?"Future weather only · current traffic layer hidden":"Traffic: current conditions · weather: forecast"}</small></span></div>
 {fallback?<Fallback nodes={nodes} path={path} geometry={geometry}/>:<div ref={ref} className="maplibre"/>}
 <div className="map-legend"><span><i style={{background:"#17765e"}}/> Selected route</span><span><i style={{background:"#82909c"}}/> Alternatives · click to compare</span><span><i style={{background:"#de7043"}}/> Traffic impact</span></div>
 {data&&!data.traffic_configured&&<div className="map-note">Live traffic requires TOMTOM_API_KEY on the backend. No traffic is invented.</div>}{data?.incidents.status==="ERROR"&&<div className="map-note">Traffic incidents could not be refreshed. Coverage may be incomplete.</div>}{error&&<div role="alert" className="map-note">{error}</div>}
 <details className="weather-readout"><summary>Weather along the route · {forecasts.filter(w=>w.status==="FORECAST").length} forecast samples</summary>{forecasts.map((w,i)=><div key={w.id+i}><span>{w.condition??w.status} · {w.temperature_c??"—"}°C</span><span>{dt(w.valid_at)} · {w.status} · wind {w.wind_kmh??"—"} km/h</span></div>)}<p>Previewing a time changes the overlay only. The planner refreshes ETAs every 2 minutes while active; refresh manually for an immediate update. Weather impacts are modelled, not measured delays.</p></details></div>
}

function Fallback({ nodes, path, geometry }: { nodes: NetNode[]; path: string[]; geometry?: number[][] | null }) {
  const W = 760, H = 360, P = 30;
  const lons = nodes.map((n) => n.lon), lats = nodes.map((n) => n.lat);
  const lo0 = Math.min(...lons), lo1 = Math.max(...lons), la0 = Math.min(...lats), la1 = Math.max(...lats);
  const X = (lon: number) => P + ((lon - lo0) / (lo1 - lo0 || 1)) * (W - 2 * P);
  const Y = (lat: number) => P + ((la1 - lat) / (la1 - la0 || 1)) * (H - 2 * P);
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const onPath = new Set(path);
  return (
    <div className="mapwrap mapfallback">
      <div className="map-lbl">{geometry ? "Basemap offline · actual road geometry retained" : "Basemap offline · schematic connection (not a road route)"}</div>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ display: "block", width: "100%" }}>
        {path.length > 1 && <polyline fill="none" stroke={ROUTE} strokeWidth={3} points={(geometry && geometry.length > 1 ? geometry.map(([lon, lat]) => `${X(lon)},${Y(lat)}`) : path.map((id) => { const n = byId.get(id)!; return `${X(n.lon)},${Y(n.lat)}`; })).join(" ")} />}
        {nodes.map((n) => {
          const x = X(n.lon), y = Y(n.lat), isHub = n.type === "hub", hot = onPath.has(n.id);
          return isHub
            ? <rect key={n.id} x={x - 6} y={y - 6} width={12} height={12} rx={2} fill={HUB} />
            : <circle key={n.id} cx={x} cy={y} r={hot ? 5 : 3.5} fill={hot ? ROUTE : "#fff"} stroke={hot ? ROUTE : BRANCH} strokeWidth={1.8} />;
        })}
        {nodes.filter((n) => n.type === "hub" || onPath.has(n.id)).map((n) => (
          <text key={n.id + "t"} x={X(n.lon) + 8} y={Y(n.lat) + 3} fontSize={10} fontWeight={700} fill="#334">{n.name}</text>
        ))}
      </svg>
    </div>
  );
}
