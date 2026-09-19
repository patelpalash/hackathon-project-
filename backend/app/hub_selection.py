"""Select intermediate facilities using the road corridor, availability and detour."""
import math
from concurrent.futures import ThreadPoolExecutor
from .eta import _haversine_km

def ll(n): return (n["lat"], n["lon"])

def corridor_distance(n, geometry):
    # Local projection for point-to-segment distances (kilometres).
    scale = math.cos(math.radians(n["lat"]))
    def xy(p): return ((p[0]-n["lon"])*111.32*scale, (p[1]-n["lat"])*111.32)
    best = float("inf")
    for a, b in zip(geometry, geometry[1:]):
        x,y = xy(a); u,v = xy(b); dx,dy = u-x,v-y
        t = max(0,min(1,-(x*dx+y*dy)/(dx*dx+dy*dy or 1)))
        best = min(best, math.hypot(x+t*dx,y+t*dy))
    return best

def select_hubs(origin, destination, available_hubs, existing_route, routing, constraints):
    if not existing_route.get("geometry"):
        return []  # Never claim route relevance from a geographic midpoint.
    blocked = constraints.get("blocked", set())
    candidates = []
    baseline = existing_route["distance_km"]
    for n in available_hubs:
        if n["id"] in {origin["id"], destination["id"]} or n["id"] in blocked or not n.get("operational", True): continue
        if not n.get("transfer_enabled", True) or constraints.get("ldm",0) > n.get("capacity_ldm", 13.6): continue
        remaining = _haversine_km(ll(n), ll(destination))
        if remaining < 8 or corridor_distance(n, existing_route["geometry"]) > constraints.get("corridor_km", 35): continue
        candidates.append((remaining, n))
    candidates.sort(key=lambda x:x[0])
    def verify(item):
        _, n = item
        left = routing.leg(ll(origin), ll(n)); right = routing.leg(ll(n), ll(destination))
        if not left.get("geometry") or not right.get("geometry"): return None
        detour = left["distance_km"] + right["distance_km"] - baseline
        if detour > min(100, max(15, baseline*constraints.get("max_detour_ratio", .25))): return None
        return {"hub": n["id"], "name": n["name"], "reason": "Operational transfer facility near the road route; ranked by distance to destination after detour and capacity checks.",
                "distance_to_destination_km": right["distance_km"], "route_deviation_km": round(max(0,detour),1), "source": "OSRM road corridor + prototype transfer eligibility"}
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = [r for r in pool.map(verify,candidates[:8]) if r]
    return sorted(results, key=lambda r:(r["distance_to_destination_km"],r["route_deviation_km"]))[:3]
