import { useEffect, useRef, useState, lazy, Suspense } from "react";
import maplibregl from "maplibre-gl";
import type { FeatureCollection } from "geojson";
import "maplibre-gl/dist/maplibre-gl.css";
import { Expand, MapPin, Play, Pause, RotateCcw } from "lucide-react";
import { duration, type Network, type Route, type Event, type Model } from "./api";
const MapFallback = lazy(() => import("./MapFallback"));

export default function NetworkMap({
  network,
  routes,
  selected,
  geometries,
  events,
  onSelect,
}: {
  network: Network;
  routes: Route[];
  selected?: Route;
  geometries: Model<"LaneGeometry">[];
  events: Event[];
  onSelect: (id: string) => void;
}) {
  const element = useRef<HTMLDivElement>(null),
    map = useRef<maplibregl.Map | null>(null);
  const [ready, setReady] = useState(false),
    [fallback, setFallback] = useState(false),
    [unavailable, setUnavailable] = useState(false);
  const [progress, setProgress] = useState(0), [playing, setPlaying] = useState(false);
  const vehicle = useRef<maplibregl.Marker | null>(null);
  useEffect(() => { setProgress(0); setPlaying(false); }, [selected?.id, selected?.arrival_at]);
  useEffect(() => {
    if (!playing) return;
    let frame: number, last = 0;
    const tick = (time: number) => {
      if (last) setProgress(p => Math.min(1, p + (time - last) / 24000));
      last = time;
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing]);
  useEffect(() => { if (progress >= 1) setPlaying(false); }, [progress]);
  useEffect(() => {
    if (!ready || !map.current || !selected) return;
    const el = document.createElement("div");
    el.className = "journey-beacon";
    el.textContent = "→";
    vehicle.current = new maplibregl.Marker({element: el}).setLngLat([0, 0]).addTo(map.current);
    return () => { vehicle.current?.remove(); vehicle.current = null; };
  }, [ready, selected?.id]);
  useEffect(() => {
    if (!selected || !vehicle.current) return;
    let elapsed = progress * selected.total_minutes;
    let segment = selected.segments[selected.segments.length - 1];
    for (const s of selected.segments) { segment = s; if (elapsed <= s.duration_minutes) break; elapsed -= s.duration_minutes; }
    if (!segment) return;
    const lane = network.lanes.find(l => l.id === segment.lane_id);
    const node = network.nodes.find(n => n.id === (segment.node_id || lane?.from_node_id));
    if (!node) return;
    let point: [number, number] = [node.longitude, node.latitude];
    if (segment.type === "travel" && lane) {
      const end = network.nodes.find(n => n.id === lane.to_node_id)!;
      const occurrence = selected.departure_times[selected.lane_ids.indexOf(lane.id)];
      const g = geometries.find(g => g.lane_id === lane.id && g.departure_at === occurrence) || geometries.find(g => g.lane_id === lane.id && g.departure_at === null);
      const geometry = g?.geometry as GeoJSON.Geometry | undefined;
      const points = geometry?.type === "LineString" ? geometry.coordinates : [[node.longitude,node.latitude],[end.longitude,end.latitude]];
      if (points.length >= 2) {
        const lengths = points.slice(1).map((p,i) => Math.hypot(p[0]-points[i][0],p[1]-points[i][1]));
        let distance = lengths.reduce((a,b) => a+b,0) * Math.min(1,elapsed / Math.max(1,segment.duration_minutes));
        for (let i=0;i<lengths.length;i++) {
          if (distance <= lengths[i] || i === lengths.length-1) {
            const fraction = lengths[i] ? Math.min(1,distance/lengths[i]) : 0;
            point = [points[i][0]+(points[i+1][0]-points[i][0])*fraction,points[i][1]+(points[i+1][1]-points[i][1])*fraction]; break;
          }
          distance -= lengths[i];
        }
      }
    }
    vehicle.current.setLngLat(point);
  }, [progress, selected, ready, network, geometries]);
  const latest = useRef({ routes, onSelect });
  latest.current = { routes, onSelect };
  const fit = () => {
    if (!map.current) return;
    const nodes = selected
      ? network.nodes.filter((n) =>
          selected.lane_ids.some((id) => {
            const l = network.lanes.find((l) => l.id === id);
            return l?.from_node_id === n.id || l?.to_node_id === n.id;
          }),
        )
      : network.nodes.filter((n) => n.longitude < 15);
    if (nodes.length)
      map.current.fitBounds(
        nodes.reduce(
          (b, n) => b.extend([n.longitude, n.latitude]),
          new maplibregl.LngLatBounds(),
        ),
        { padding: 80, maxZoom: 7, duration: 700 },
      );
  };
  useEffect(() => {
    if (!element.current) return;
    let timer: ReturnType<typeof setTimeout>;
    try {
      const m = new maplibregl.Map({
        container: element.current,
        style: "https://tiles.openfreemap.org/styles/liberty",
        center: [9.1, 49.3],
        zoom: 5.2,
        attributionControl: { compact: true },
      });
      map.current = m;
      const localStyle = () => {
        if (!m.isStyleLoaded()) {
          setFallback(true);
          m.setStyle({
            version: 8,
            sources: {},
            layers: [
              {
                id: "background",
                type: "background",
                paint: { "background-color": "#e9eff0" },
              },
            ],
          });
        }
      };
      timer = setTimeout(localStyle, 9000);
      m.on("load", () => {
        clearTimeout(timer);
        setReady(true);
      });
      m.on("error", () => setFallback(true));
      m.addControl(
        new maplibregl.NavigationControl({ showCompass: false }),
        "bottom-right",
      );
      const observer = new ResizeObserver(() => m.resize());
      observer.observe(element.current);
      return () => {
        clearTimeout(timer);
        observer.disconnect();
        m.remove();
        map.current = null;
        setReady(false);
      };
    } catch {
      setUnavailable(true);
    }
  }, []);
  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    const blocked = new Set(
      events
        .filter(
          (e) =>
            e.verification_status === "accepted" &&
            e.lifecycle_status === "active" &&
            e.target_kind === "lane",
        )
        .map((e) => e.target_id),
    );
    const features: FeatureCollection = {
      type: "FeatureCollection",
      features: network.lanes.map((l) => {
        const from = network.nodes.find((n) => n.id === l.from_node_id)!,
          to = network.nodes.find((n) => n.id === l.to_node_id)!;
        const occurrence =
          selected?.departure_times[selected.lane_ids.indexOf(l.id)];
        const geometry =
          geometries.find(
            (g) => g.lane_id === l.id && g.departure_at === occurrence,
          ) ||
          geometries.find((g) => g.lane_id === l.id && g.departure_at === null);
        return {
          type: "Feature",
          properties: {
            id: l.id,
            selected: selected?.lane_ids.includes(l.id) ? 1 : 0,
            color: blocked.has(l.id)
              ? "#ec8c43"
              : selected?.lane_ids.includes(l.id)
                ? "#386bed"
                : "#9babb7",
          },
          geometry: (geometry?.geometry as GeoJSON.Geometry) || {
            type: "LineString",
            coordinates: [
              [from.longitude, from.latitude],
              [to.longitude, to.latitude],
            ],
          },
        };
      }),
    };
    if (m.getSource("lanes"))
      (m.getSource("lanes") as maplibregl.GeoJSONSource).setData(features);
    else {
      m.addSource("lanes", { type: "geojson", data: features });
      m.addLayer({
        id: "route-glow", type: "line", source: "lanes",
        filter: ["==", ["get", "selected"], 1],
        paint: {"line-color": "#386bed", "line-width": 15, "line-opacity": 0.14, "line-blur": 3},
      });
      m.addLayer({
        id: "routes",
        type: "line",
        source: "lanes",
        paint: {
          "line-color": ["get", "color"],
          "line-width": ["case", ["==", ["get", "selected"], 1], 4, 2],
          "line-opacity": 0.85,
          "line-dasharray": [2, 1],
        },
      });
      m.on("mouseenter", "routes", () => { m.getCanvas().style.cursor = "pointer"; });
      m.on("mouseleave", "routes", () => { m.getCanvas().style.cursor = ""; });
      m.on("click", "routes", (e) => {
        const id = e.features?.[0].properties?.id;
        const r = latest.current.routes.find((r) => r.lane_ids.includes(id));
        if (r) latest.current.onSelect(r.id);
      });
    }
    const markers = network.nodes.map((n) => {
      const el = document.createElement("div");
      el.className = "map-node";
      const label = document.createElement("span");
      label.textContent = n.name.replace(/ hub| branch| hand-over/gi, "");
      el.append(label);
      const popup = document.createElement("div");
      popup.className = "facility-popup";
      const heading = document.createElement("strong"); heading.textContent = n.name;
      const detail = document.createElement("p"); detail.textContent = `${n.country} · ${n.timezone}`;
      popup.append(heading,detail);
      return new maplibregl.Marker({ element: el })
        .setPopup(new maplibregl.Popup({offset: 16}).setDOMContent(popup))
        .setLngLat([n.longitude, n.latitude])
        .addTo(m);
    });
    return () => markers.forEach((m) => m.remove());
  }, [ready, network, selected, geometries, events]);
  return (
    <div className="map-wrap">
      <div ref={element} className="map-canvas" />
      {unavailable && (
        <div className="map-offline">
          <Suspense fallback={<p>Loading schematic…</p>}>
            <MapFallback network={network} selected={selected} />
          </Suspense>
        </div>
      )}
      <div className="map-title">
        <span className="live-dot" /> NETWORK VIEW <span>Europe</span>
      </div>
      <button className="map-fit icon-button" onClick={fit} title="Fit route">
        <Expand size={17} />
      </button>
      {selected && ready && !unavailable && <div className="journey-replay">
        <button className="replay-play" onClick={() => { if (progress >= 1) setProgress(0); setPlaying(!playing); }} aria-label={playing ? "Pause journey replay" : "Play journey replay"}>{playing ? <Pause size={15}/> : <Play size={15} fill="currentColor"/>}</button>
        <div className="replay-track"><div><strong>Journey replay</strong><span>Illustrative · not live tracking</span></div><input aria-label="Journey replay progress" type="range" min="0" max="1000" value={Math.round(progress*1000)} onChange={e => {setPlaying(false);setProgress(Number(e.target.value)/1000);}}/></div>
        <span className="replay-time">{duration(Math.round(selected.total_minutes*progress))}</span>
        <button className="icon-button" aria-label="Reset journey replay" onClick={() => {setPlaying(false);setProgress(0);}}><RotateCcw size={14}/></button>
      </div>}
      <div className="map-legend">
        <span>
          <i className="blue-line" /> Selected connection
        </span>
        <span>
          <i className="orange-line" /> Disrupted corridor
        </span>
      </div>
      <div className="map-source">
        {fallback ? "Basemap unavailable or incomplete · " : "OpenFreeMap · "}
        Schematic service connections · approximate facilities
        {geometries.some((g) => g.geometry_kind === "provider_road")
          ? " · road data: TomTom"
          : ""}
      </div>
    </div>
  );
}
