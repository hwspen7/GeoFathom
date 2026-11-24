"""Independent network-science reference fixtures; no external service needed."""
import base64
import math
import numpy as np
import pytest
from fastapi.testclient import TestClient
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
from analysis.network_routes import NetworkInput
from analysis.network_science import execute,NetworkError,METHODS
from core.main import app

P={'A':(0.,0.),'B':(.001,0.),'C':(.002,0.),'D':(.001,.001),'E':(.01,0.),'F':(.011,0.)}

def edge(e,u,v,c,d='forward'):
    return {'type':'Feature','geometry':{'type':'LineString','coordinates':[list(P[u]),list(P[v])]},
        'properties':{'edge_id':e,'source':u,'target':v,'minutes':c,'direction':d}}

def collection(*items):return {'type':'FeatureCollection','features':list(items)}
NETWORK=collection(edge('ab','A','B',2),edge('bc','B','C',3),edge('ad','A','D',4),edge('dc','D','C',4),edge('ef','E','F',1,'both'))
def run(kind,network=NETWORK,**kw):
    return execute(NetworkInput(operation=kind,network=network,cost_field=kw.pop('cost_field','minutes'),cost_unit='min',**kw))

def metrics(r):return r['receipt']['metrics']

def test_catalog_and_topology():
    r=run('topology');assert len(METHODS)==18
    assert r['receipt']['nodes']==6 and r['receipt']['directed_arcs']==6
    assert metrics(r)['weak_components']==2
    assert {row[0]:row[3] for row in r['rows']}=={'A':2,'B':1,'C':0,'D':1,'E':1,'F':1}
    assert len(r['features']['features'])==5

def test_shortest_path_and_parallel_edges():
    n=collection(*NETWORK['features'],edge('ab_fast','A','B',1))
    r=run('shortest_path',n,origins=['A'],destinations=['C'])
    assert [x[1] for x in r['rows']]==['ab_fast','bc']
    assert metrics(r)['total_cost']==4
    assert run('shortest_path',n,origins=['C'],destinations=['A'])['rows']==[]
    assert not metrics(run('shortest_path',n,origins=['C'],destinations=['A']))['reachable']

def test_od_and_nearest():
    r=run('od_matrix',origins=['A','C','E'],destinations=['B','C','F'])
    assert [x[-1] for x in r['rows']]==[2.,5.,None,None,0.,None,None,None,1.]
    r=run('nearest_facility',origins=['A','E'],destinations=['B','C'])
    assert r['rows']==[['A','B',2.],['E',None,None]]

def test_partial_service_network():
    r=run('service_area',origins=['A'],threshold=3)
    assert metrics(r)['reachable_nodes']==2
    assert {f['properties']['edge_id']:f['properties']['reachable_fraction'] for f in r['features']['features']}=={'ab':1.,'ad':.75,'bc':1/3}
    # Equal equatorial ab and bc; ad is a diagonal.
    expected=111.31949079327357*(1+1/3)+156.90347192691743*.75
    assert metrics(r)['reachable_length_m']==pytest.approx(expected,rel=1e-6)

def test_accessibility_models():
    r=run('gravity_access',origins=['A','E'],destinations=['B','C'],supply={'B':10,'C':20},beta=.2)
    assert r['rows'][0][1]==pytest.approx(10*math.exp(-.4)+20*math.exp(-1))
    assert r['rows'][1][1]==0
    r=run('two_step_fca',origins=['A','B','E'],destinations=['B','C'],supply={'B':12,'C':18},demand={'A':2,'B':4,'E':5},threshold=3)
    assert r['rows']==[['A',2.],['B',6.5],['E',0.]]
    assert metrics(r)['allocated_supply']==30

def test_centrality_exact():
    n=collection(edge('ab','A','B',1),edge('bc','B','C',1))
    r=run('harmonic_centrality',n);assert dict(r['rows'])=={'A':.75,'B':.5,'C':0.}
    r=run('betweenness',n);assert dict(r['rows'])=={'A':0.,'B':.5,'C':0.}
    # A-B-C and A-D-C equal cost; two A-B parallel arcs imply B carries 2/3.
    n=collection(edge('ab','A','B',1),edge('ab2','A','B',1),edge('bc','B','C',1),edge('ad','A','D',1),edge('dc','D','C',1))
    scores=dict(run('betweenness',n)['rows'])
    assert scores['B']==pytest.approx((2/3)/6) and scores['D']==pytest.approx((1/3)/6)

def test_scenario_and_edge_criticality():
    r=run('scenario_impact',origins=['A','B'],destinations=['C'],closed_edges=['bc'])
    assert r['rows']==[['A','C',5.,8.,3.,'reachable'],['B','C',3.,None,None,'disconnected']]
    assert metrics(r)['retained_fraction']==.5
    r=run('scenario_impact',origins=['A'],destinations=['C'],multipliers={'bc':3})
    assert r['rows'][0][3]==8
    r=run('edge_criticality',origins=['A','B'],destinations=['C'],test_edges=['bc','ad'])
    assert r['rows']==[['bc',1,.5,3.,1],['ad',0,0.,0.,2]]

def test_circuity_geodesic():
    n=collection(edge('ab','A','B',1),edge('bc','B','C',1))
    r=run('circuity',n,cost_field='length_m',origins=['A','C'],destinations=['C','A'])
    assert r['rows'][0][-1]==pytest.approx(1)
    assert r['rows'][1][-1] is None and r['rows'][2][-1] is None

def test_seeded_reliability_and_exact_limit():
    n=collection(edge('ab','A','B',1),edge('bc','B','C',1))
    kw={'origins':['A'],'destinations':['C'],'failure_probability':{'ab':.25,'bc':.2},'trials':1000,'seed':13}
    r=run('stochastic_reliability',n,**kw)
    assert r['rows']==run('stochastic_reliability',n,**kw)['rows']
    q=r['rows'][0];assert abs(q[3]-.6)<.06 and q[4]<=q[3]<=q[5] and q[6]==2
    r=run('stochastic_reliability',n,**{**kw,'failure_probability':{'ab':1.}})
    assert r['rows'][0][3:]==[0.,0.,pytest.approx(3.841458820694124/1003.8414588206941),None]

def raster(z):
    with MemoryFile() as mem:
        with mem.open(driver='GTiff',width=3,height=1,count=1,dtype='float64',crs='EPSG:4326',
                      transform=from_origin(-.0005,.0005,.001,.001),nodata=np.nan) as ds:
            ds.write(np.asarray(z,dtype=float).reshape(1,3),1);ds.scales=[2.];ds.offsets=[1.];ds.update_tags(TERRAIN_UNIT='hazard')
        return {'data':base64.b64encode(mem.read()).decode(),'band':1}

def test_raster_exposure_and_coverage():
    n=collection(edge('ab','A','B',1),edge('bc','B','C',1))
    r=run('hazard_exposure',n,raster=raster([1,3,5]),spacing_m=60)
    assert r['rows']==[['ab',5.,7.,1.,2],['bc',9.,11.,1.,2]]
    assert metrics(r)['scale']==2
    r=run('scenario_impact',n,origins=['A'],destinations=['C'],raster=raster([1,3,5]),spacing_m=60,hazard_threshold=10)
    assert metrics(r)['closed_edges']==['bc'] and metrics(r)['disconnected_pairs']==1
    with pytest.raises(NetworkError,match='coverage'):
        run('scenario_impact',n,origins=['A'],destinations=['C'],raster=raster([1,3,np.nan]),spacing_m=60)

def test_explicit_topology_and_invalid_inputs():
    # Crossing geometries are not silently joined: this is grade separation safe.
    n=collection(edge('ab','A','B',1),edge('dc','D','C',1))
    assert metrics(run('topology',n))['weak_components']==2
    with pytest.raises(NetworkError,match='Duplicate edge'):run('topology',collection(edge('ab','A','B',1),edge('ab','B','C',1)))
    with pytest.raises(NetworkError,match='Edge cost'):run('topology',collection(edge('ab','A','B',0)))
    with pytest.raises(NetworkError,match='Unknown'):run('shortest_path',origins=['missing'],destinations=['A'])
    assert TestClient(app).get('/analysis/network-science/catalog').status_code==200
    assert TestClient(app).post('/analysis/network-science/run',json={'operation':'shortest_path','network':NETWORK,'origins':['missing'],'destinations':['A']}).status_code==422

def test_result_figures_render():
    from terrain.studio_routes import StudioInput
    from terrain.studio_render import render
    results=[run('topology'),run('shortest_path',origins=['A'],destinations=['C']),run('od_matrix',origins=['A'],destinations=['B','C']),
        run('service_area',origins=['A'],threshold=5),run('gravity_access',origins=['A','B'],destinations=['C'],supply={'C':2}),
        run('betweenness'),run('scenario_impact',origins=['A','B'],destinations=['C'],multipliers={'bc':2}),
        run('edge_criticality',origins=['A','B'],destinations=['C'],test_edges=['bc','ad']),
        run('stochastic_reliability',origins=['A','B'],destinations=['C'],failure_probability={'bc':.3},trials=100)]
    for result in results:
        for figure in result['figures']:
            req=StudioInput(recipe=figure['recipe'],csv=figure['csv'],**figure['bindings'])
            png,_,_=render(req);assert png.startswith(b'\x89PNG')


def test_osm_snapshot_build_and_grade_separation():
    from analysis.network_import import build_osm
    snapshot={'elements':[
        {'type':'node','id':1,'lon':0.,'lat':0.},{'type':'node','id':2,'lon':.001,'lat':0.},
        {'type':'node','id':3,'lon':.002,'lat':0.},{'type':'node','id':4,'lon':.001,'lat':0.},
        {'type':'node','id':5,'lon':.001,'lat':.001},
        {'type':'way','id':100,'nodes':[1,2,3],'tags':{'highway':'residential','oneway':'-1'}},
        {'type':'way','id':101,'nodes':[4,5],'tags':{'highway':'residential','bridge':'yes'}},
        {'type':'way','id':102,'nodes':[2,5],'tags':{'highway':'residential','access':'private'}}]}
    out=build_osm(snapshot,{'residential':36});n=out['network'];assert len(n['features'])==3
    assert out['receipt']['excluded_ways']==1
    assert n['features'][0]['properties']['direction']=='reverse'
    assert n['features'][0]['properties']['travel_time_s']==pytest.approx(11.1319490793)
    assert metrics(run('topology',n,cost_field='travel_time_s'))['weak_components']==2
    assert metrics(run('shortest_path',n,cost_field='travel_time_s',origins=['osm:3'],destinations=['osm:1']))['reachable']
    assert not metrics(run('shortest_path',n,cost_field='travel_time_s',origins=['osm:1'],destinations=['osm:3']))['reachable']
    assert TestClient(app).post('/analysis/network-science/build-osm',json={'snapshot':snapshot,'speed_kmh_by_class':{'residential':36}}).status_code==200

def test_pareto_exact_nondominated_paths():
    n=collection(edge('ab','A','B',1),edge('bc','B','C',1),edge('ad','A','D',3),edge('dc','D','C',3),edge('ac','A','C',8))
    for f,c in zip(n['features'],[5,5,1,1,11]):f['properties']['risk']=c
    r=run('pareto_path',n,origins=['A'],destinations=['C'],secondary_cost_field='risk')
    assert r['rows']==[[1,2.,10.,2],[2,6.,2.,2]]
    assert len(r['features']['features'])==4 and metrics(r)['nondominated_routes']==2
    assert run('pareto_path',n,origins=['C'],destinations=['A'],secondary_cost_field='risk')['rows']==[]

def test_raster_impedance_and_adjusted_path():
    n=collection(edge('ab','A','B',1),edge('bc','B','C',1))
    kw={'raster':raster([1,3,5]),'spacing_m':60,'exposure_reference':5,'exposure_scale':4,'exposure_alpha':math.log(2)}
    r=run('raster_impedance',n,**kw)
    assert [x[-1] for x in r['rows']]==pytest.approx([1,2])
    derived=r['features'];assert metrics(run('shortest_path',derived,cost_field='adjusted_cost',origins=['A'],destinations=['C']))['total_cost']==pytest.approx(3)
    assert not metrics(run('shortest_path',derived,cost_field='adjusted_cost',origins=['C'],destinations=['A']))['reachable']
    r=run('raster_least_cost',n,origins=['A'],destinations=['C'],**kw)
    assert metrics(r)['baseline_optimal_cost']==2 and metrics(r)['adjusted_optimal_cost']==pytest.approx(3)
    with pytest.raises(NetworkError,match='coverage'):
        run('raster_impedance',n,**{**kw,'raster':raster([1,3,np.nan])})

def test_correlated_failure_limit_and_seed():
    # Two nearly co-located parallel routes have near-perfect latent
    # correlation at long range; independent reliability is 0.75.
    n=collection(edge('ab','A','B',1),edge('ab2','A','B',1))
    kw={'origins':['A'],'destinations':['B'],'failure_probability':{'ab':.5,'ab2':.5},'trials':2000,'seed':17}
    corr=run('correlated_reliability',n,**kw);ind=run('stochastic_reliability',n,**kw)
    assert corr['rows']==run('correlated_reliability',n,**kw)['rows']
    assert abs(corr['rows'][0][3]-.5)<.05
    assert abs(ind['rows'][0][3]-.75)<.05
    assert metrics(corr)['maximum_off_diagonal_latent_correlation']==pytest.approx(1)
