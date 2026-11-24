"""Build a research road graph from a local OSM Overpass JSON snapshot.

OSM node identity, rather than geometric proximity, defines connectivity.
No network download, inferred turn restrictions, or implicit speed defaults.
"""
from .network_science import require,number,point,GEOD
import hashlib
import json

def build_osm(data,speeds):
    raw=json.dumps(data,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    require(len(raw)<=8_000_000,'OSM snapshot exceeds 8 MB.')
    require(isinstance(data,dict) and isinstance(data.get('elements'),list),'Use Overpass JSON with nodes and ways.')
    elements=data['elements'];require(1<=len(elements)<=100000,'OSM element limit exceeded.')
    require(isinstance(speeds,dict) and speeds,'Provide explicit default km/h by included highway class.')
    speeds={k:number(v,'Default speed',.1,200) for k,v in speeds.items()}
    nodes={};ways=[];seen=set()
    def oid(value):
        require(isinstance(value,int) and not isinstance(value,bool) and 0<value<2**63,'Invalid OSM ID.')
        return value
    for item in elements:
        require(isinstance(item,dict),'Invalid OSM element.')
        kind=item.get('type')
        if kind=='node':
            key=oid(item.get('id'));require(key not in nodes,'Duplicate OSM node.')
            nodes[key]=point([item.get('lon'),item.get('lat')])
        elif kind=='way':
            key=oid(item.get('id'));require(key not in seen,'Duplicate OSM way.');seen.add(key)
            ways.append(item)
    features=[];excluded=0;restrictions=sum(isinstance(e,dict) and e.get('type')=='relation' and isinstance(e.get('tags'),dict) and e['tags'].get('type')=='restriction' for e in elements)
    for way in sorted(ways,key=lambda x:x['id']):
        tags=way.get('tags') or {};require(isinstance(tags,dict),'Invalid OSM way tags.')
        highway=tags.get('highway')
        if highway not in speeds or tags.get('access') in {'no','private'} or tags.get('motor_vehicle') in {'no','private'}:
            excluded+=1;continue
        require(not any(k in tags for k in ('oneway:conditional','access:conditional','motor_vehicle:conditional','maxspeed:conditional')),'Conditional OSM access/speed requires preprocessing.')
        require(tags.get('access','yes') in {'yes','public','permissive','designated'} and tags.get('motor_vehicle','yes') in {'yes','permissive','designated'},'Restricted OSM access requires preprocessing.')
        oneway=tags.get('oneway','yes' if tags.get('junction') in {'roundabout','circular'} or highway=='motorway' else 'no')
        require(oneway in {'yes','1','true','no','0','false','-1'},'Unsupported OSM oneway tag.')
        direction='reverse' if oneway=='-1' else 'forward' if oneway in {'yes','1','true'} else 'both'
        # Explicit scenario speed, not posted or observed travel speed.
        speed=speeds[highway]
        ids=way.get('nodes');require(isinstance(ids,list) and len(ids)>=2,'OSM way has no node sequence.')
        ids=[oid(x) for x in ids];require(all(x in nodes for x in ids),'OSM snapshot lacks referenced nodes; export full way geometry.')
        for i,(u,v) in enumerate(zip(ids,ids[1:])):
            if u==v:continue
            a,b=nodes[u],nodes[v]
            require(abs(a[0]-b[0])<=180,'Split antimeridian-crossing ways.')
            length=GEOD.inv(*a,*b)[2];require(length>0,'Coincident distinct OSM nodes in a road segment.')
            features.append({'type':'Feature','geometry':{'type':'LineString','coordinates':[a,b]},'properties':{
                'edge_id':f"osm:{way['id']}:{i}",'source':f'osm:{u}','target':f'osm:{v}','direction':direction,
                'osm_way':str(way['id']),'highway':highway,'scenario_speed_kmh':speed,'travel_time_s':length/(speed/3.6),
                'length_m':length}})
            require(len(features)<=10000,'Road graph exceeds 10,000 segments; use a smaller study area.')
    require(features,'No roads matched the selected highway classes.')
    return {'network':{'type':'FeatureCollection','features':features},'receipt':{
        'source_sha256':hashlib.sha256(raw).hexdigest(),'segments':len(features),'excluded_ways':excluded,'speed_kmh_by_class':speeds,
        'restriction_relations_present':restrictions,'assumption':'OSM shared node IDs only; class-based scenario speeds, no observed traffic, turn restrictions or conditional access. Review tags and data completeness before inference.'}}
