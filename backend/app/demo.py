"""Isolated, deterministic judge demo using captured OSRM geometry."""
import json, os, re
from pathlib import Path
from types import SimpleNamespace
from .operations import Operations


def context(base, session):
    if not re.fullmatch(r"[a-f0-9]{12}",session): raise ValueError("Invalid demo session")
    directory=Path(os.environ.get("STORE_DIR","store"))/"demo"/session
    if not (directory/"operations.json").exists(): raise ValueError("Unknown demo session")
    nodes={k:base["network"]["nodes"][k] for k in ("R16","R10","R21")}
    records=json.loads((Path(__file__).resolve().parents[2]/"data"/"demo_roads.json").read_text())
    lookup={((nodes[r["from"]]["lat"],nodes[r["from"]]["lon"]),(nodes[r["to"]]["lat"],nodes[r["to"]]["lon"])):r for r in records}
    def leg(a,b):
        row=lookup.get((tuple(a),tuple(b)))
        if row is None: return {"geometry":None,"source":"DEMO: connection unavailable"}
        return {**row,"source":"DEMO: captured OSRM geometry; illustrative travel times"}
    providers=SimpleNamespace(routing=SimpleNamespace(leg=leg),traffic=SimpleNamespace(status=lambda:"SIMULATED"))
    return {**base,"network":{**base["network"],"nodes":nodes,"edges":{}},"providers":providers,"operations":Operations(directory),"holidays":{},"transfer":{},"hub_delays":{},"is_demo":True}
