import { useEffect, useState } from "react";
import { LayoutDashboard, Truck, Route, PiggyBank, BarChart3, RefreshCw, ShieldCheck, CloudSun, BookOpen, ArrowUpRight, Activity } from "lucide-react";
import { api } from "./api/client";
import type { NetworkDoc, Provider, Operations } from "./api/types";
import { statusClass } from "./lib";
import { Dashboard } from "./views/Dashboard";
import { Shipments } from "./views/Shipments";
import { Planner } from "./views/Planner";
import { Savings } from "./views/Savings";
import { Analytics } from "./views/Analytics";
import { WeatherLab } from "./views/WeatherLab";
import { ControlRoom } from "./views/ControlRoom";
import { Assumptions } from "./views/Assumptions";
const TABS = [
  { id:"planner", label:"Route planner", icon:Route }, { id:"dashboard", label:"Overview", icon:LayoutDashboard },
  { id:"control", label:"Control room", icon:ShieldCheck }, { id:"shipments", label:"Shipments", icon:Truck },
  { id:"weather", label:"Weather lab", icon:CloudSun }, { id:"analytics", label:"Network intelligence", icon:BarChart3 },
  { id:"savings", label:"Savings", icon:PiggyBank }, { id:"assumptions", label:"Assumptions", icon:BookOpen }
];
export default function App() {
  const [tab,setTab]=useState("planner"); const [net,setNet]=useState<NetworkDoc|null>(null);
  const [providers,setProviders]=useState<Provider[]>([]); const [ops,setOps]=useState<Operations|null>(null);
  const [tick,setTick]=useState(0); const [err,setErr]=useState("");
  const refresh=()=>setTick(t=>t+1);
  useEffect(()=>{let alive=true; api.network().then(n=>{if(alive)setNet(n)}).catch(e=>{if(alive)setErr(String(e))}); return()=>{alive=false}},[]);
  useEffect(()=>{let alive=true; const load=()=>Promise.all([api.providers(),api.operations()]).then(([p,o])=>{if(alive){setProviders(p.providers);setOps(o);setErr("")}}).catch(e=>{if(alive)setErr(String(e))}); void load(); const timer=setInterval(load,15000); return()=>{alive=false;clearInterval(timer)}},[tick]);
  const nodes=net?.nodes??[];
  const alerts=ops?.weather.filter(w=>w.alert && Date.parse(w.end)>Date.now())??[];
  return <div className="app-shell">
    <header className="workspace-header"><a href="#" className="brand" onClick={e=>{e.preventDefault();setTab("planner")}}><span className="brand-icon"><Route size={22}/></span><span>transit<span className="brand-dot">.</span><small>OPERATIONS WORKSPACE</small></span></a><span className="workspace-label">DACHSER / Challenge 03</span><div className="top__spacer"/><span className="prototype-tag">HACKATHON PROTOTYPE</span><button className="icon-button" aria-label="Refresh workspace" onClick={refresh}><RefreshCw size={17}/></button><span className="avatar" title="Demo manager">MK</span></header>
    <nav className="workspace-nav" aria-label="Workspace navigation">{TABS.map(t=><button key={t.id} aria-current={tab===t.id?"page":undefined} className={tab===t.id?"active":""} onClick={()=>setTab(t.id)}><t.icon size={16}/>{t.label}</button>)}</nav>
    <main className="wrap">
      <div className="page-meta"><span>WORKSPACE <span>/</span> {TABS.find(t=>t.id===tab)?.label.toUpperCase()}</span><span><Activity size={12}/> {nodes.length} facilities · {ops?.events.length??0} scenario events</span></div>
      {err&&<div role="alert" className="notice notice--warn">Connection issue: {err}<button className="linkbtn" onClick={refresh}>Retry</button></div>}
      {alerts.length>0 && tab!=="weather" && <button className="alert-strip" onClick={()=>setTab("weather")}><CloudSun size={18}/><span><b>{alerts.length} weather alert{alerts.length>1?"s":""}</b> · Manual samples affect matching journeys during their time windows.</span><ArrowUpRight size={17}/></button>}
      {tab==="planner"&&<Planner nodes={nodes} revision={ops?.revision??0} onChange={refresh} onReview={()=>setTab("control")}/>}
      {tab==="dashboard"&&<><div className="page-heading"><div><span className="eyebrow">THE BIG PICTURE</span><h1>Every shipment. In focus.</h1><p>Your network, priorities and exceptions in one place.</p></div><button className="btn" onClick={()=>setTab("planner")}>Plan a shipment <ArrowUpRight size={16}/></button></div><Dashboard key={tick}/></>}
      {tab==="control"&&<ControlRoom nodes={nodes} onChange={refresh}/>}
      {tab==="weather"&&<WeatherLab nodes={nodes} onChange={refresh}/>}
      {tab==="shipments"&&<Shipments nodes={nodes}/>}
      {tab==="analytics"&&<><div className="page-heading"><div><span className="eyebrow">NETWORK INTELLIGENCE</span><h1>Learn from every lane.</h1><p>Historical operations and hub performance from the supplied data.</p></div></div><Analytics onData={refresh}/></>}
      {tab==="savings"&&<Savings/>}{tab==="assumptions"&&<Assumptions/>}
      <footer className="workspace-footer"><span>Transit / Decision support, with people in control.</span><div className="provider-strip">{providers.map(p=><span key={p.key} className={statusClass(p.status)} title={`${p.name} · ${p.status}${p.error ? " · " + p.error : ""}`}><span className="dot"/>{p.key}: {p.status.replace(/_/g," ")}</span>)}</div></footer>
    </main>
  </div>
}
