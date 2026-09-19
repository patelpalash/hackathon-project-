"""Compare a proposal with the saved plan without changing that snapshot."""
from datetime import datetime


def change_summary(previous, proposed):
    if not previous: return {"material":True,"reasons":["No saved comparison snapshot"],"eta_minutes":0,"cost_eur":0}
    minutes=round((datetime.fromisoformat(proposed["eta"])-datetime.fromisoformat(previous["eta"])).total_seconds()/60)
    cost=round(proposed["cost"]["transport_eur"]-previous["cost"]["transport_eur"],2)
    reasons=[]
    if previous["path"]!=proposed["path"]: reasons.append("Route changed")
    if abs(minutes)>=15: reasons.append("ETA changed by at least 15 minutes")
    if abs(cost)>=max(.01,abs(previous["cost"]["transport_eur"])*.05): reasons.append("Transport estimate changed by at least 5%")
    if previous["risk"]["deadline_ok"]!=proposed["risk"]["deadline_ok"]: reasons.append("Deadline feasibility changed")
    if previous.get("revision")!=proposed.get("revision"): reasons.append("Manager inputs, closures or timetables changed")
    if previous.get("data_sources",{}).get("transport")!=proposed.get("data_sources",{}).get("transport"): reasons.append("Routing source or coverage changed")
    for key in ("weather","traffic","hub_delay","weekend_hold","legal_wait","schedule_wait"):
        if previous.get("components",{}).get(key,0)!=proposed.get("components",{}).get(key,0): reasons.append(key.replace("_"," ").capitalize()+" impact changed")
    return {"material":bool(reasons),"reasons":reasons,"eta_minutes":minutes,"cost_eur":cost,"previous_eta":previous["eta"],"proposed_eta":proposed["eta"],"previous_cost":previous["cost"]["transport_eur"],"proposed_cost":proposed["cost"]["transport_eur"],"evaluated_at":proposed.get("evaluated_at")}
