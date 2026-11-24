"""Independent arithmetic, repeatability, masks, API and portable-report tests."""
import base64
import io
import json
import zipfile
from threading import Event

import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient
from pypdf import PdfReader
from rasterio.transform import from_origin
from rasterio.warp import transform_geom
from shapely.geometry import box, mapping
from uuid import uuid4

from imagery.raster import RasterError
from imagery.store import image_file, file_sha256
from terrain.cancellation import TerrainCancelled
from terrain.professional import raster_product
from terrain.research import analyze_experiment, difference, unpack
from terrain.research_routes import Experiment

@pytest.fixture
def experiment_source(tmp_path, monkeypatch):
    monkeypatch.setenv('GEOFATHOM_IMAGERY_DIR',str(tmp_path))
    uid=str(uuid4());path=tmp_path/(uid+'.tif')
    affine=from_origin(500000,4500000,10,10)
    values=np.full((10,10),100.)
    with rasterio.open(path,'w',driver='GTiff',width=10,height=10,count=1,
        dtype='float64',crs='EPSG:32617',transform=affine,nodata=float('nan')) as ds:
        ds.write(values,1);ds.update_tags(VERTICAL_DATUM='NAVD88')
    geometry=transform_geom('EPSG:32617','EPSG:4326',mapping(box(500000,4499900,500100,4500000)))
    base={'image_id':uid,'geometry':geometry,'operation':'cutfill_map','reference':90}
    return base,path,affine


def run(base,**kwargs):
    return analyze_experiment(Experiment(base=base,**kwargs),image_file)


def archive(result):
    return zipfile.ZipFile(io.BytesIO(base64.b64decode(result['archive_base64'])))


def test_named_scenarios_and_exact_signed_grid_difference(experiment_source):
    base,path,_=experiment_source
    result=run(base,scenarios=[{'name':'Higher design','parameters':{'reference':95}},
                              {'name':'Balanced design','parameters':{'reference':100}}])
    assert [r['label'] for r in result['runs']]==['Baseline','Higher design','Balanced design']
    assert [r['metrics']['cut_m3'] for r in result['runs']]==pytest.approx([100000,50000,0])
    for i,item in enumerate(result['differences']):
        values,_,_=unpack(item['raster'])
        assert np.all(values==-5*(i+1))
        assert item['statistics']['common_cells']==100
        assert item['statistics']['changed_pct']==100
    assert result['manifest']['input']['expected_source_sha256']==file_sha256(path)
    with archive(result) as package:
        assert {'report.pdf','experiment.json','metrics.csv','manifest.json'}<=set(package.namelist())
        receipt=json.loads(package.read('manifest.json'))
        assert len(receipt['artifacts'])==5
        text='\n'.join(page.extract_text() for page in PdfReader(io.BytesIO(package.read('report.pdf'))).pages)
        assert 'Higher design' in text and 'NAVD88' in text and 'SHA-256' in text
        assert 'Source accuracy is not independently validated' in text
        replay=analyze_experiment(Experiment.model_validate_json(package.read('experiment.json')),image_file)
        assert replay['metric_table']==result['metric_table']
    row=next(r for r in result['metric_table'] if r['metric']=='cut_m3')
    assert row['relative_pct']==pytest.approx([0,-50,-100])


def test_sensitivity_matches_analytic_earthwork_derivative(experiment_source):
    base,_,_=experiment_source
    result=run(base,mode='sensitivity',parameter='reference',values=[85,90,95])
    points=result['sensitivity']
    assert [p['metrics']['cut_m3'] for p in points]==pytest.approx([150000,100000,50000])
    assert points[0]['derivatives']['cut_m3']==pytest.approx(-10000)
    assert points[1]['derivatives']=={}
    assert points[2]['derivatives']['cut_m3']==pytest.approx(-10000)
    with archive(result) as package:
        assert 'sensitivity.csv' in package.namelist()
        assert b'derivative_from_baseline' in package.read('sensitivity.csv')


def test_uncertainty_common_offset_matches_direct_seeded_normal_oracle(experiment_source):
    base,_,_=experiment_source;base={**base,'operation':'elevation'}
    result=run(base,mode='uncertainty',samples=100,sigma_m=2,seed=31,error_model='common_offset')
    normal=np.random.Generator(np.random.PCG64(31)).normal(0,2,100)
    observed=result['uncertainty']['metrics']['product_mean']
    # Production rasters serialize float32 while metrics retain float64.
    assert observed['mean']==pytest.approx(100+normal.mean(),abs=1e-5)
    assert observed['std']==pytest.approx(normal.std(ddof=1),abs=1e-5)
    assert observed['low']==pytest.approx(100+np.quantile(normal,.025),abs=1e-5)
    assert observed['high']==pytest.approx(100+np.quantile(normal,.975),abs=1e-5)
    sd=next(p for p in result['products'] if p['role']=='std')
    values,_,_=unpack(sd['raster'])
    assert values==pytest.approx(np.full((10,10),normal.std(ddof=1)),abs=1e-5)
    repeat=run(base,mode='uncertainty',samples=100,sigma_m=2,seed=31,error_model='common_offset')
    assert repeat['uncertainty']==result['uncertainty']
    assert repeat['products'][1]['raster']['geotiff']==result['products'][1]['raster']['geotiff']
    with archive(result) as package:
        assert 'uncertainty.csv' in package.namelist()
        assert json.loads(package.read('manifest.json'))['uncertainty']['seed']==31


def test_independent_error_reduces_uncertainty_of_regional_mean(experiment_source):
    base,_,_=experiment_source;base={**base,'operation':'elevation'}
    result=run(base,mode='uncertainty',samples=200,sigma_m=1,seed=42,error_model='independent')
    stats=result['uncertainty']['metrics']['product_mean']
    # Independent regional mean has sigma/sqrt(N), unlike common-offset noise.
    assert stats['std']==pytest.approx(.1,rel=.2)
    assert stats['mean']==pytest.approx(100,abs=.03)
    assert stats['low']<stats['mean']<stats['high']


def test_nodata_remains_missing_in_all_uncertainty_outputs(experiment_source):
    base,path,_=experiment_source
    with rasterio.open(path,'r+') as ds:
        values=ds.read(1);values[3,4]=np.nan;ds.write(values,1)
    result=run({**base,'operation':'elevation'},mode='uncertainty',samples=20)
    assert result['uncertainty']['common_cells']==99
    for product in result['products']:
        values,_,_=unpack(product['raster'])
        assert np.isnan(values[3,4])
        assert np.isfinite(values).sum()==99


def test_common_offset_does_not_change_slope(experiment_source):
    base,path,_=experiment_source
    with rasterio.open(path,'r+') as ds:
        ds.write(np.tile(np.arange(10)*3.,(10,1))+100,1)
    result=run({**base,'operation':'slope_map'},mode='uncertainty',samples=20,error_model='common_offset')
    sd=next(p for p in result['products'] if p['role']=='std')
    values,_,_=unpack(sd['raster'])
    assert np.nanmax(values)<1e-5


def test_categorical_transitions_and_shortest_circular_difference(experiment_source):
    _,_,affine=experiment_source
    def product(values,operation):
        return raster_product(np.array(values,float),operation,affine,'EPSG:32617')
    a=product([[0,1],[1,np.nan]],'suitability');b=product([[1,1],[0,0]],'suitability')
    result=difference(a,b,'suitability')
    assert result['kind']=='transition'
    assert result['statistics']['common_cells']==3
    assert result['statistics']['changed_cells']==2
    assert sum(t['cells'] for t in result['statistics']['transitions'])==3
    a=product([[350,10],[-1,np.nan]],'aspect_map');b=product([[10,350],[10,0]],'aspect_map')
    result=difference(a,b,'aspect_map')
    values,_,_=unpack(result['raster'])
    assert values[0]==pytest.approx([20,-20])
    assert np.isnan(values[1]).all()
    assert result['statistics']['common_cells']==2


def test_grid_and_units_must_match(experiment_source):
    _,_,affine=experiment_source
    a=raster_product(np.ones((3,3)),'elevation',affine,'EPSG:32617')
    b=raster_product(np.ones((2,2)),'elevation',affine,'EPSG:32617')
    with pytest.raises(RasterError,match='identical grids'):difference(a,b,'elevation')
    b={**a,'unit':'degrees'}
    with pytest.raises(RasterError,match='units differ'):difference(a,b,'elevation')


@pytest.mark.parametrize('options',[
 {'mode':'sensitivity','parameter':'reference','values':[1,1]},
 {'mode':'sensitivity','parameter':'max_slope','values':[10,20]},
 {'scenarios':[{'name':'Baseline','parameters':{'reference':100}}]},
 {'mode':'uncertainty','samples':2},
 {'mode':'uncertainty','sigma_m':0},
 {'mode':'uncertainty','seed':-1},
 {'mode':'uncertainty','coverage':1},
])
def test_experiment_validation_rejects_ambiguous_or_invalid_inputs(experiment_source,options):
    base,_,_=experiment_source
    with pytest.raises(ValueError):Experiment(base=base,**options)


def test_invalid_overrides_checksum_and_cancellation(experiment_source):
    base,_,_=experiment_source
    for parameters in [{'image_id':'other'},{'geometry':{}},{'operation':'elevation'},{'bogus':1}]:
        with pytest.raises((RasterError, ValueError)):run(base,scenarios=[{'name':'Invalid','parameters':parameters}])
    with pytest.raises(RasterError,match='checksum changed'):
        run(base,mode='uncertainty',expected_source_sha256='0'*64)
    cancel=Event();cancel.set()
    with pytest.raises(TerrainCancelled):
        analyze_experiment(Experiment(base=base,mode='uncertainty'),image_file,cancel)


def test_api_research_uses_the_production_engine(experiment_source):
    from core.main import app
    base,_,_=experiment_source
    with TestClient(app) as client:
        catalog=client.get('/terrain/research/catalog')
        assert catalog.status_code==200
        assert 'reference' in catalog.json()['scenario_parameters']['cutfill_map']
        response=client.post('/terrain/research/analyze',json={'base':base,'mode':'sensitivity','parameter':'reference','values':[85,95]})
        assert response.status_code==200,response.text
        assert response.json()['sensitivity'][1]['derivatives']['cut_m3']==pytest.approx(-10000)
        invalid=client.post('/terrain/research/analyze',json={'base':base,'mode':'sensitivity','parameter':'reference','values':[1,1]})
        assert invalid.status_code==422


def test_export_tags_describe_real_quantity_not_elevation(experiment_source):
    base,_,_=experiment_source
    result=run(base,scenarios=[{'name':'Higher','parameters':{'reference':95}}])
    product=result['differences'][0]['raster']
    from rasterio.io import MemoryFile
    with MemoryFile(base64.b64decode(product['geotiff'])) as memory,memory.open() as ds:
        assert ds.tags()['TERRAIN_OPERATION']=='research_difference'
        assert ds.tags()['TERRAIN_UNIT']==product['unit']
        assert ds.tags()['RESEARCH_TITLE']=='Candidate minus baseline'
        assert ds.crs.to_epsg()==32617


def test_two_gradient_algorithms_are_compared_on_identical_cells(experiment_source):
    base,path,_=experiment_source
    yy,xx=np.indices((10,10))
    with rasterio.open(path,'r+') as ds:ds.write(100+np.sin(xx)*np.cos(yy)*4,1)
    result=run({**base,'operation':'slope_map'},scenarios=[{'name':'Zevenbergen Thorne','parameters':{'gradient_method':'zevenbergen_thorne'}}])
    delta=result['differences'][0]
    # ZT requires a complete stencil: only the 8x8 interior is shared.
    assert delta['statistics']['common_cells']==64
    assert delta['statistics']['rms_difference']>0
    assert result['comparison_warning']
    assert next(row for row in result['metric_table'] if row['metric']=='product_mean')['deltas'][1] is None
    assert delta['raster']['unit'] in {'degree','degrees','deg'}


def test_surface_scenarios_share_a_display_range_without_changing_geotiff_values(experiment_source):
    base,path,_=experiment_source
    yy,xx=np.indices((10,10))
    with rasterio.open(path,'r+') as ds:ds.write(100+xx*xx+yy*yy,1)
    result=run({**base,'operation':'tri'},scenarios=[{'name':'Wider neighborhood','parameters':{'neighborhood_radius':2}}])
    a,b=result['products']
    assert a['raster']['preview_scale']==b['raster']['preview_scale']
    assert a['raster']['preview_scale']['shared_across_scenarios']
    z1,_,_=unpack(a['raster']);z2,_,_=unpack(b['raster'])
    assert not np.allclose(z1,z2,equal_nan=True)
    assert sum(x['cells'] for x in b['raster']['legend'])==np.isfinite(z2).sum()


def test_volume_uncertainty_uses_the_same_correlated_offset_in_every_cell(experiment_source):
    base,_,_=experiment_source
    result=run({**base,'operation':'volume'},mode='uncertainty',samples=40,error_model='common_offset',seed=7,sigma_m=.1)
    noise=np.random.Generator(np.random.PCG64(7)).normal(0,.1,40)
    stats=result['uncertainty']['metrics']['cut_m3']
    assert stats['std']==pytest.approx(noise.std(ddof=1)*10000)
    assert stats['mean']==pytest.approx(100000+noise.mean()*10000)
    assert result['products']==[]


def test_pixel_mask_overlap_is_required_and_zero_baselines_are_undefined(experiment_source):
    base,_,affine=experiment_source
    a=raster_product(np.array([[1.,np.nan],[1.,np.nan]]),'elevation',affine,'EPSG:32617')
    b=raster_product(np.array([[np.nan,2.],[np.nan,2.]]),'elevation',affine,'EPSG:32617')
    with pytest.raises(RasterError,match='No common valid'):difference(a,b,'elevation')
    result=run({**base,'reference':100},scenarios=[{'name':'Lower design','parameters':{'reference':95}}])
    assert next(r for r in result['metric_table'] if r['metric']=='cut_m3')['relative_pct']==[None,None]


def test_active_parameter_integer_sweeps_and_budget_limits_are_enforced(experiment_source,monkeypatch):
    import terrain.research as research
    base,_,_=experiment_source
    with pytest.raises(RasterError,match='integer'):
        run({**base,'operation':'tri'},mode='sensitivity',parameter='neighborhood_radius',values=[1,1.5])
    monkeypatch.setattr(research,'MAX_ENSEMBLE_CELLS',1000)
    with pytest.raises(RasterError,match='cell realizations'):
        run(base,mode='uncertainty',samples=20)
    monkeypatch.setattr(research,'MAX_ENSEMBLE_CELLS',100)
    with pytest.raises(RasterError,match='cell evaluations'):
        run(base,mode='sensitivity',parameter='reference',values=[85,95])


@pytest.mark.parametrize('change,options',[
 ({'bogus':1},{'mode':'uncertainty'}),
 ({'operation':'mesh'},{'mode':'uncertainty'}),
 ({'reference':float('nan')},{'mode':'uncertainty'}),
 ({},{'scenarios':[{'name':'Invalid','parameters':{'reference':float('inf')}}]}),
 ({},{'scenarios':[{'name':'Unchanged','parameters':{'reference':90}}]}),
 ({},{'expected_dependency_sha256':{'dem':'invalid'},'mode':'uncertainty'}),
 ({'elevation_sigma_m':1},{'mode':'uncertainty'}),
 ({'external_inflow_image_id':'abc'},{'mode':'uncertainty'}),
 ({'operation':'curvature'},{'mode':'sensitivity','parameter':'curvature_radius','values':[1,2]}),
 ({'operation':'visibility'},{'mode':'sensitivity','parameter':'refraction_coeff','values':[.1,.2]}),
 ({'operation':'curvature'},{'scenarios':[{'name':'Invalid','parameters':{'curvature_radius':3}}]}),
 ({'operation':'visibility'},{'scenarios':[{'name':'Invalid','parameters':{'refraction_coeff':.2}}]}),
 ({'operation':'flow_accumulation'},{'scenarios':[{'name':'Invalid','parameters':{'depression_method':'breach'}}]}),
])
def test_invalid_or_inactive_model_parameters_fail_before_computation(experiment_source,change,options):
    base,_,_=experiment_source
    with pytest.raises(ValueError):Experiment(base={**base,**change},**options)


def test_dsm_dependency_is_fingerprinted_and_locked_for_reproduction(experiment_source):
    base,_,affine=experiment_source
    from rasterio.warp import transform
    x,y=affine*(4.5,4.5)
    longitude,latitude=transform('EPSG:32617','EPSG:4326',[x],[y])
    base={**base,'operation':'visibility','point':[longitude[0],latitude[0]],'dsm_image_id':base['image_id']}
    result=run(base,scenarios=[{'name':'Tall observer','parameters':{'observer_height':3}}])
    receipt=result['manifest']
    assert receipt['dependencies'][0]['id']==base['image_id']
    assert receipt['input']['expected_dependency_sha256'][base['image_id']]==receipt['source']['sha256']
    with pytest.raises(RasterError,match='Dependency checksum changed'):
        run(base,scenarios=[{'name':'Tall observer','parameters':{'observer_height':3}}],expected_dependency_sha256={base['image_id']:'0'*64})


def test_api_numerical_error_is_a_clear_validation_response(experiment_source):
    from core.main import app
    base,_,_=experiment_source
    with TestClient(app) as client:
        reply=client.post('/terrain/research/analyze',json={'base':base,'mode':'uncertainty','expected_source_sha256':'0'*64})
        assert reply.status_code==422
        assert 'checksum changed' in reply.json()['detail']


def test_engine_version_fallback_and_source_mutation_detection(experiment_source,monkeypatch):
    import subprocess
    import terrain.research as research
    base,_,_=experiment_source
    def unavailable(*args,**kwargs):raise subprocess.SubprocessError('Git unavailable')
    monkeypatch.setattr(research.subprocess,'run',unavailable)
    monkeypatch.setenv('GEOFATHOM_BUILD_REVISION','packaged-build')
    assert research.software_revision()=={'geofathom_commit':'packaged-build','working_tree_modified':None}
    original=research.execute
    calls=0
    def mutate_after_execution(*args,**kwargs):
        nonlocal calls
        output=original(*args,**kwargs)
        calls+=1
        if calls==2:
            with rasterio.open(args[1],'r+') as ds:
                values=ds.read(1);values[0,0]+=1;ds.write(values,1)
        return output
    monkeypatch.setattr(research,'execute',mutate_after_execution)
    with pytest.raises(RasterError,match='Source bytes changed'):
        run(base,scenarios=[{'name':'Higher design','parameters':{'reference':95}}])
