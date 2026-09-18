"""Validate planning artifacts. Does not test the future application.

Run: python docs/tools/validate_spec.py
Dependency: jsonschema (pip install jsonschema).
"""
from pathlib import Path
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo
import json
import hashlib
import sys

DOCS = Path(__file__).resolve().parents[1]
# Authoring fallback; normal team use installs jsonschema into its own venv.
scratch_deps = DOCS.parent / 'tmp' / 'spec_validation_deps'
if scratch_deps.is_dir():
    sys.path.insert(0, str(scratch_deps))
try:
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError:
    raise SystemExit('Install validation dependency: python -m pip install jsonschema')

def read(name): return json.loads((DOCS/name).read_text(encoding='utf-8'))
def dt(value): return datetime.fromisoformat(value.replace('Z','+00:00'))
def iso(value): return value.isoformat().replace('+00:00','Z')
def minutes(start,end): return int((end-start).total_seconds()//60)
def check(condition,message):
    if not condition: raise AssertionError(message)

api=read('contracts/openapi.json')
def validate(name,value):
    schema={**api, '$schema':'https://json-schema.org/draft/2020-12/schema','$ref':f'#/components/schemas/{name}'}
    Draft202012Validator(schema,format_checker=FormatChecker()).validate(value)

def walk(value):
    if isinstance(value,dict):
        if '$ref' in value:
            target=value['$ref']; check(target.startswith('#/'),'External reference unexpected')
            found=api
            for part in target[2:].split('/'): found=found[part.replace('~1','/').replace('~0','~')]
        for child in value.values(): walk(child)
    elif isinstance(value,list):
        for child in value: walk(child)

walk(api)
for name,schema in api['components']['schemas'].items(): Draft202012Validator.check_schema(schema)
operations=[]
for path,methods in api['paths'].items():
    for method,op in methods.items():
        operations.append(op['operationId'])
        for param in op.get('parameters',[]): check('{'+param['name']+'}' in path,'Unbound path parameter')
check(len(set(operations))==len(operations),'Duplicate operationId')

network=read('fixtures/network.json'); validate('Network',network)
request=read('fixtures/search-request.json'); validate('SearchRequest',request)
response=read('fixtures/search-response.json'); validate('SearchResponse',response)
presets=read('fixtures/presets.json')
for event in presets.values(): validate('Event',event)
events={e['id']:e for e in presets.values()}
nodes={n['id']:n for n in network['nodes']}; lanes={l['id']:l for l in network['lanes']}
check(len(nodes)==len(network['nodes'])==9,'Node IDs/count incorrect')
check(len(lanes)==len(network['lanes'])==10,'Lane IDs/count incorrect')
for lane in lanes.values():
    check(lane['from_node_id'] in nodes and lane['to_node_id'] in nodes,'Unknown lane endpoint')
    check(lane['from_node_id']!=lane['to_node_id'],'Self loop in seed')
for node in nodes.values(): ZoneInfo(node['timezone'])
for event in events.values():
    check(event['target_id'] in (nodes if event['target_kind']=='node' else lanes),'Unknown event target')

for route in response['routes']:
    cursor=dt(request['ready_at']); total=0
    for segment in route['segments']:
        check(dt(segment['start_at'])==cursor,'Gap or overlap in timeline')
        end=dt(segment['end_at']); duration=minutes(cursor,end)
        check(duration==segment['duration_minutes'] and duration>0,'Segment duration inconsistent')
        check(sum(reason['minutes'] for reason in segment['reasons'])==duration,'Reason contributions inconsistent')
        cursor=end; total+=duration
    check(total==route['total_minutes']==minutes(dt(request['ready_at']),cursor),'Total inconsistent')
    check(iso(cursor)==route['arrival_at'],'Arrival inconsistent')
    canonical=json.dumps({'lane_ids':route['lane_ids'],'departure_times':route['departure_times']},sort_keys=True,separators=(',',':'))
    check(route['id']==hashlib.sha256(canonical.encode()).hexdigest()[:24],'Route ID hash inconsistent')

# Independent schedule/arithmetic replay for the deliberately simple fixture paths.
# This checker does NOT implement the production search, closure semantics for all
# cases, event fixed-point algorithm, state machine, HTTP API or concurrency tests.
# The fixtures have one daily service per lane and fixed non-overlapping event groups.
def overlap(start,end,event):
    return start < (dt(event['valid_until']) if event['valid_until'] else datetime.max.replace(tzinfo=start.tzinfo)) and dt(event['valid_from']) < end

def extra(target,start,end,kind,selected):
    groups={}
    for e in selected:
        if e['target_id']==target and e['effect_type']==kind and overlap(start,end,e):
            groups[e['correlation_key']]=max(groups.get(e['correlation_key'],0),e['effect_minutes'])
    return sum(groups.values())

def travel_end(lane,departure,work):
    rules=[r for r in network['calendar_rules'] if r['lane_id']==lane['id']]
    current=departure
    if not rules: return current+timedelta(minutes=work)
    zone=ZoneInfo(rules[0]['timezone'])
    # Minute stepping is intentionally transparent for these small integer fixtures.
    for _ in range(14*24*60):
        if not work: return current
        local=current.astimezone(zone)
        if local.isoweekday()!=rules[0]['weekday']: work-=1
        current+=timedelta(minutes=1)
    raise AssertionError('Reference fixture traversal exceeded horizon')

def path_arrival(req,path,selected):
    current=dt(req['ready_at']); horizon=current+timedelta(days=14)
    node_id=req['origin_id']
    for lane_id in path:
        lane=lanes[lane_id]; check(lane['from_node_id']==node_id,'Broken fixture path')
        node=nodes[node_id]
        handling=node['processing_minutes']
        current+=timedelta(minutes=handling+extra(node_id,current,current+timedelta(minutes=handling),'additional_handling_minutes',selected))
        zone=ZoneInfo(node['timezone']); start_date=current.astimezone(zone).date()
        choices=[]
        for day in range(15):
            local_date=start_date+timedelta(days=day)
            if not lane['valid_from']<=local_date.isoformat()<=lane['valid_to']:continue
            for schedule in lane['departures']:
                if local_date.isoweekday() not in schedule['weekdays']:continue
                departure=datetime.combine(local_date,time.fromisoformat(schedule['local_time']),zone).astimezone(current.tzinfo)
                if current>departure-timedelta(minutes=schedule['cutoff_minutes']):continue
                if departure>horizon:continue
                if any(r['lane_id']==lane_id and departure.astimezone(ZoneInfo(r['timezone'])).isoweekday()==r['weekday'] for r in network['calendar_rules']):continue
                work=lane['duration_minutes']
                work+=extra(lane_id,departure,departure+timedelta(minutes=work),'additional_travel_minutes',selected)
                arrival=travel_end(lane,departure,work)
                if any(e['target_id']==lane_id and e['effect_type']=='closure' and overlap(departure,arrival,e) for e in selected):continue
                choices.append((arrival,departure))
        check(bool(choices),'No reference fixture departure')
        current=min(choices)[0];node_id=lane['to_node_id']
    check(node_id==req['destination_id'],'Wrong path destination')
    return current

cases=read('fixtures/acceptance.json')['cases']
for case in cases:
    req=case['request'];validate('SearchRequest',req)
    check(dt(req['ready_at'])>=dt(case['simulation_clock']),'Fixture ready before clock')
    selected=[events[e] for e in case['event_ids']]
    for expected in case['expected_routes']:
        arrival=path_arrival(req,expected['lane_ids'],selected)
        check(iso(arrival)==expected['arrival_at'],f"{case['id']} {expected['lane_ids']}: reference {iso(arrival)} != expected {expected['arrival_at']}")
        check(minutes(dt(req['ready_at']),arrival)==expected['total_minutes'],f"{case['id']}: elapsed duration mismatch")
    sorting=lambda x:(dt(x['arrival_at']),len(x['lane_ids'])-1,','.join(x['lane_ids']))
    check(case['expected_routes']==sorted(case['expected_routes'],key=sorting),f"{case['id']}: ranking mismatch")

print(f'PASS: {len(operations)} API operations, {len(api["components"]["schemas"])} schemas; all local references resolve.')
print('PASS: network, search request/response and event fixtures conform to their schemas.')
print('PASS: baseline segment continuity, duration totals and route ID hashes.')
print(f'PASS: independent schedule/arithmetic replay for all {len(cases)} fixture cases.')
print('These checks validate the specification artifacts, not a built application.')
