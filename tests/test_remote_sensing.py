"""Independent numerical oracles and end-to-end remote sensing workflow tests."""
import base64
import hashlib
import json
import math

import numpy as np
import pytest
from fastapi.testclient import TestClient
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from core.main import app
from imagery.remote_catalog import BY_ID
from imagery.remote_routes import RemoteInput,execute
from terrain.studio_data import FigureInputError

CRS='EPSG:32617'
AFF=from_origin(500000,4500000,10,10)

def source(arrays,name='scene',aff=AFF,scales=None,offsets=None,unit=None):
    a=np.array(arrays,dtype=float)
    if a.ndim==2:a=a[None]
    with MemoryFile() as mem:
        with mem.open(driver='GTiff',width=a.shape[2],height=a.shape[1],count=len(a),dtype='float64',
                      crs=CRS,transform=aff,nodata=np.nan) as ds:
            ds.write(a)
            if scales is not None:ds.scales=scales
            if offsets is not None:ds.offsets=offsets
            if unit:ds.update_tags(TERRAIN_UNIT=unit)
        raw=mem.read()
    return {'name':name,'data':base64.b64encode(raw).decode()}

def constant(x):return np.full((3,4),x,dtype=float)

def run(kind,arrays,params=None,**kwargs):
    names=[r for r,_ in BY_ID[kind].roles]
    s=source([arrays[r] for r in names]);bindings={}
    for i,(r,q) in enumerate(BY_ID[kind].roles):
        bindings[r]={'source':0,'band':i+1,'unit':'m' if q=='numeric' else ''}
    body={'operation':kind,'sources':[s],'bindings':bindings,'parameters':params or {},**kwargs}
    return checked(execute(RemoteInput(**body)))

def checked(result):
    receipt=result['receipt'];assert receipt['operation']==result['operation']
    assert receipt['table_sha256']==hashlib.sha256(result['csv'].encode()).hexdigest()
    json.dumps(result,allow_nan=False)
    if result['raster']:
        product=result['raster'];raw=base64.b64decode(product['data'])
        assert hashlib.sha256(raw).hexdigest()==product['sha256']==receipt['raster_sha256']
        z=grid(result);assert receipt['raster_summary']['valid_cells']==int(np.isfinite(z).sum())
    return result

def grid(result):
    with MemoryFile(base64.b64decode(result['raster']['data'])) as mem,mem.open() as ds:
        assert ds.crs.to_string()==CRS and ds.transform==AFF
        return ds.read(1)

# Values are written out independently of the production formula dispatch.
N,R,B,G,RE,S1,S2=.6,.2,.1,.3,.4,.25,.35
OPTICAL={
 'ndvi':.4/.8,'evi':2.5*.4/(.6+1.2-.75+1),'evi2':2.5*.4/(.6+.48+1),
 'savi':1.5*.4/1.3,'msavi2':(2.2-math.sqrt(2.2**2-3.2))/2,
 'gndvi':.3/.9,'ndre':.2/1.,'ndwi':-.3/.9,'mndwi':.05/.55,
 'ndmi':.35/.85,'nbr':.25/.95,'nbr2':-.1/.6,'ndbi':-.35/.85,
 'bsi':(.45-.7)/1.15,'ndsi':.05/.55,'arvi':.3/.9,'osavi':1.16*.4/.96,
 'simple_ratio':3.,'nirv':.3,'ci_green':1.}

@pytest.mark.parametrize('kind',list(OPTICAL))
def test_optical_reference(kind):
    values={'nir':N,'red':R,'blue':B,'green':G,'rededge':RE,'swir1':S1,'swir2':S2}
    arrays={r:constant(values[r]) for r,_ in BY_ID[kind].roles}
    arrays[next(iter(arrays))][0,0]=np.nan
    result=run(kind,arrays);z=grid(result)
    assert np.isnan(z[0,0]);np.testing.assert_allclose(z[np.isfinite(z)],OPTICAL[kind],atol=1e-12)

@pytest.mark.parametrize('kind',['sentinel_clear','landsat_clear','landsat_unsaturated'])
def test_quality_reference(kind):
    if kind=='sentinel_clear':
        q=np.arange(12,dtype=float).reshape(3,4);expected=np.array([np.nan,0,0,0,1,1,1,0,0,0,0,0]).reshape(3,4)
    elif kind=='landsat_clear':
        q=np.array([0,1,2,4,8,16,32,64,128,256,65,192],float).reshape(3,4)
        expected=np.array([1,np.nan,0,0,0,0,0,1,1,1,np.nan,1]).reshape(3,4)
    else:
        q=np.array([0,1,2,4,8,16,32,64,128,256,0,192],float).reshape(3,4)
        expected=(q==0).astype(float)
    np.testing.assert_allclose(grid(run(kind,{'qa':q})),expected,equal_nan=True)

@pytest.mark.parametrize('kind',['difference','relative_change','change_classes','transition_matrix'])
def test_change_reference(kind):
    if kind=='transition_matrix':
        a=np.array([[1,1,2],[2,3,3]],float);b=np.array([[1,2,2],[3,3,1]],float)
        result=run(kind,{'before':a,'after':b});m=result['receipt']['metrics']
        assert m['changed_fraction']==.5 and m['valid_area_m2']==600
        assert result['rows']==[[1,1,1,100.,1/6],[1,2,1,100.,1/6],[2,2,1,100.,1/6],[2,3,1,100.,1/6],[3,1,1,100.,1/6],[3,3,1,100.,1/6]]
    else:
        a=np.array([[2,2,0],[2,2,np.nan]],float);b=np.array([[4,1,2],[2,2.5,3]],float)
        expected={'difference':[[2,-1,2],[0,.5,np.nan]],'relative_change':[[100,-50,np.nan],[0,25,np.nan]],
                  'change_classes':[[2,1,2],[0,0,np.nan]]}[kind]
        result=run(kind,{'before':a,'after':b},{'threshold':.5} if kind=='change_classes' else {})
        np.testing.assert_allclose(grid(result),expected,equal_nan=True)

@pytest.mark.parametrize('kind',['brightness_temperature','emissivity_temperature','temperature_celsius','sar_db','sar_linear','sar_ratio','dualpol_rvi'])
def test_thermal_radar_reference(kind):
    if kind=='brightness_temperature':
        a={'radiance':constant(10)};expected=1321.0789/math.log(1+774.8853/10)
    elif kind=='emissivity_temperature':
        a={'temperature':constant(300),'emissivity':constant(.95)};expected=300/(1+10.9e-6*300/.01438776877*math.log(.95))
    elif kind=='temperature_celsius':a={'temperature':constant(300)};expected=26.85
    elif kind=='sar_db':a={'power':constant(.01)};expected=-20
    elif kind=='sar_linear':a={'backscatter':constant(-20)};expected=.01
    else:
        a={'cross':constant(.02),'co':constant(.08)};expected=.25 if kind=='sar_ratio' else .8
    np.testing.assert_allclose(grid(run(kind,a)),expected,atol=1e-10)

@pytest.mark.parametrize('kind',['temporal_mean','temporal_median','temporal_count','temporal_trend'])
def test_temporal_reference(kind):
    t=np.array([0,2,5,9]);a={f'date{i+1}':constant(3+2*v) for i,v in enumerate(t)}
    a['date2'][0,0]=np.nan
    for v in a.values():v[0,1]=np.nan
    expected={'temporal_mean':(11, (3+13+21)/3),'temporal_median':(10,13),'temporal_count':(4,3),'temporal_trend':(2,2)}[kind]
    # Mean of [3,7,13,21] is 11; median is 10.
    params={f'time{i+1}':float(v) for i,v in enumerate(t)} if kind=='temporal_trend' else {}
    z=grid(run(kind,a,params));assert z[1,1]==pytest.approx(expected[0]);assert z[0,0]==pytest.approx(expected[1])
    if kind=='temporal_count':assert z[0,1]==0
    else:assert np.isnan(z[0,1])

@pytest.mark.parametrize('kind',['pca','spectral_angle','minimum_distance','classification_accuracy'])
def test_spectral_classification_reference(kind):
    if kind=='pca':
        x=np.arange(12,dtype=float).reshape(3,4)/20
        a={r:x*c+.05 for r,c in zip(('blue','green','red','nir'),(1,.5,.25,.125))}
        r=run(kind,a);scores=grid(r)
        expected=(x-x.mean())*np.linalg.norm([1,.5,.25,.125])
        np.testing.assert_allclose(scores,expected,atol=1e-12)
        assert r['rows'][0][2]==pytest.approx(1)
        assert sum(row[2] for row in r['rows'])==pytest.approx(1)
    elif kind=='spectral_angle':
        a={r:constant(v) for r,v in zip(('red_before','nir_before','swir_before','red_after','nir_after','swir_after'),(1,0,0,0,1,0))}
        np.testing.assert_allclose(grid(run(kind,a)),90)
    elif kind=='minimum_distance':
        v=np.array([[.1,.11,.12,.1],[.1,.11,.8,.81],[.82,.8,.81,.82]])
        a={r:v.copy() for r in ('blue','green','red','nir')};a['training']=np.array([[1,1,0,0],[0,0,2,2],[0,0,0,0]],float)
        r=run(kind,a);np.testing.assert_array_equal(grid(r),np.where(v<.5,1,2))
        assert r['receipt']['metrics']['training_cells']==4
    else:
        a=np.array([[1,1,2],[2,2,1]],float);b=np.array([[1,2,2],[2,1,1]],float)
        r=run(kind,{'prediction':a,'reference':b});m=r['receipt']['metrics']
        assert m['confusion_matrix_reference_rows']==[[2,1],[1,2]]
        assert m['overall_accuracy']==pytest.approx(2/3) and m['kappa']==pytest.approx(1/3)

def test_sensor_calibration_and_quality_roles():
    # Landsat C2 raw DN and metadata encoding must agree, never double scale.
    raw=np.array([constant(24000),constant(14000),constant(0),constant(0)])
    raw[0,0,0]=0;raw[2,0,1]=8;raw[3,0,2]=1
    s=source(raw)
    body={'operation':'ndvi','sources':[s],'bindings':{'nir':{'source':0,'band':1,'encoding':'landsat_sr'},'red':{'source':0,'band':2,'encoding':'landsat_sr'}},
          'quality':[{'source':0,'band':3,'scheme':'landsat_clear'},{'source':0,'band':4,'scheme':'landsat_unsaturated'}]}
    r=checked(execute(RemoteInput(**body)));z=grid(r);assert np.isnan(z[0,:3]).all()
    n=24000*.0000275-.2;red=14000*.0000275-.2
    assert z[1,1]==pytest.approx((n-red)/(n+red));assert len(r['receipt']['quality_masks'])==2
    meta=source(raw[:2],scales=[.0000275]*2,offsets=[-.2]*2)
    body['sources']=[meta];body['quality']=[]
    assert grid(execute(RemoteInput(**body)))[1,1]==pytest.approx(z[1,1])
    # Custom Sentinel radiometric correction uses supplied scale AND offset.
    s2=source([constant(7000),constant(3000)])
    result=execute(RemoteInput(operation='ndvi',sources=[s2],bindings={
      'nir':{'source':0,'band':1,'encoding':'custom','scale':.0001,'offset':-.1},
      'red':{'source':0,'band':2,'encoding':'custom','scale':.0001,'offset':-.1}}))
    assert grid(result)[1,1]==pytest.approx(.5)

def test_thermal_landsat_surface_temperature_preset():
    s=source(constant(45000));r=execute(RemoteInput(operation='temperature_celsius',sources=[s],bindings={
        'temperature':{'source':0,'encoding':'landsat_st'}}))
    np.testing.assert_allclose(grid(r),45000*.00341802+149-273.15)

def test_remote_invalid_inputs_and_recovery():
    client=TestClient(app);s=source([constant(.6),constant(.2)])
    good={'operation':'ndvi','sources':[s],'bindings':{'nir':{'source':0,'band':1},'red':{'source':0,'band':2}}}
    for bad in [
       {**good,'sources':[source([constant(6000),constant(2000)])]},
       {**good,'bindings':{'nir':{'source':0,'band':1},'red':{'source':0,'band':3}}},
       {**good,'bindings':{'nir':{'source':0,'band':1},'red':{'source':1,'band':1}},'sources':[s,source(constant(.2),aff=from_origin(500001,4500000,10,10))]},
       {**good,'parameters':{'unknown':1}},
       {**good,'quality':[{'source':0,'band':1,'scheme':'binary'}]},
       {**good,'operation':'unknown'},
       {**good,'sources':[{'name':'bad','data':'not a tiff'}]},
    ]:
        response=client.post('/analysis/remote-sensing/run',json=bad);assert response.status_code==422,response.text
    response=client.post('/analysis/remote-sensing/run',json=good);assert response.status_code==200,response.text
    np.testing.assert_allclose(grid(response.json()),.5)
    assert client.get('/analysis/remote-sensing/catalog').json()['operation_count']==len(BY_ID)==55

def test_temporal_independent_quality_masks():
    # Cloud at one date does not erase the other valid acquisitions.
    data=[constant(1),constant(3),constant(5),constant(7),constant(1)]
    data[-1][0,0]=0
    s=source(data);bindings={f'date{i+1}':{'source':0,'band':i+1,'unit':'index'} for i in range(4)}
    result=execute(RemoteInput(operation='temporal_mean',sources=[s],bindings=bindings,
        quality=[{'source':0,'band':5,'scheme':'binary','roles':['date4']}]))
    z=grid(result);assert z[0,0]==3 and z[1,1]==4

def test_remote_to_spatial_and_figure_workflow():
    client=TestClient(app);x=np.arange(16,dtype=float).reshape(4,4)/20+.1
    s=source([x,constant(.2)[:1,:1]*np.ones_like(x)])
    body={'operation':'ndvi','sources':[s],'bindings':{'nir':{'source':0,'band':1},'red':{'source':0,'band':2}}}
    r=client.post('/analysis/remote-sensing/run',json=body);assert r.status_code==200,r.text
    result=checked(r.json());z=grid(result);np.testing.assert_allclose(z,(x-.2)/(x+.2))
    product=result['raster'];src={k:product[k] for k in ('name','data','unit','band')}
    spatial=client.post('/analysis/science/run',json={'operation':'raster_threshold','rasters':[src],'parameters':{'threshold':.3}})
    assert spatial.status_code==200,spatial.text
    classified=spatial.json();np.testing.assert_array_equal(grid(classified),(z>=.3).astype(float))
    assert classified['receipt']['raster_sources'][0]['sha256']==product['sha256']
    plot=next(p for p in result['figures'] if 'quantile' in p['title'].lower())
    for fmt in ('png','svg','pdf'):
        response=client.post('/terrain/studio/render',json={'recipe':plot['recipe'],'csv':plot['csv'],'format':fmt,**plot['bindings']})
        assert response.status_code==200,response.text
        raw=base64.b64decode(response.json()['figure']);assert len(raw)>100
        assert raw.startswith(b'\x89PNG') if fmt=='png' else b'<svg' in raw if fmt=='svg' else raw.startswith(b'%PDF')

def test_remote_medium_grid_and_undefined_ratio():
    z=np.linspace(.1,.8,512*512).reshape(512,512);red=np.full_like(z,.2)
    z[0,0]=0;red[0,0]=0;z[1,1]=np.nan
    r=run('ndvi',{'nir':z,'red':red});out=grid(r)
    assert np.isnan(out[0,0]) and np.isnan(out[1,1])
    assert np.isfinite(out).sum()==z.size-2
    assert out[300,300]==pytest.approx((z[300,300]-.2)/(z[300,300]+.2))


def test_remote_acceptance_gate_rejects_missing_and_skipped(tmp_path):
    from scripts.remote_sensing_gate import expected_tests,required_tests,evaluate
    from xml.etree import ElementTree as ET
    root=ET.Element('testsuite')
    for name in [*expected_tests().values(),*required_tests()]:ET.SubElement(root,'testcase',name=name)
    path=tmp_path/'remote.xml';ET.ElementTree(root).write(path)
    assert evaluate(path)['passed']
    ET.SubElement(root[0],'skipped');ET.ElementTree(root).write(path);assert not evaluate(path)['passed']
    root.remove(root[0]);ET.ElementTree(root).write(path);assert not evaluate(path)['passed']


@pytest.mark.parametrize('kind',['calibrated_reflectance','align_continuous','align_categorical','ndvi_change','dnbr','sar_lee','temporal_sen','temporal_trend_se','spectral_unmix','spectral_unmix_rmse','stratified_accuracy'])
def test_advanced_remote_reference(kind):
    if kind=='calibrated_reflectance':
        np.testing.assert_allclose(grid(run(kind,{'band':constant(.4)})),.4)
    elif kind in {'align_continuous','align_categorical'}:
        target=np.ones((4,4));target[0,0]=np.nan
        src=np.array([[1,2],[3,4]],float)
        sources=[source(target),source(src,aff=from_origin(500000,4500000,20,20))]
        result=execute(RemoteInput(operation=kind,sources=sources,bindings={'target':{'source':0},'source':{'source':1,'unit':'m' if kind=='align_continuous' else ''}}))
        out=grid(result);assert np.isnan(out[0,0])
        if kind=='align_categorical':expected=np.repeat(np.repeat(src,2,axis=0),2,axis=1);expected[0,0]=np.nan;np.testing.assert_allclose(out,expected,equal_nan=True)
        else:assert out[1,1]==pytest.approx(1.75) and out[-1,-1]==pytest.approx(4)
    elif kind in {'ndvi_change','dnbr'}:
        band='red' if kind=='ndvi_change' else 'swir'
        a={'nir_before':constant(.6),band+'_before':constant(.2),'nir_after':constant(.4),band+'_after':constant(.4)}
        np.testing.assert_allclose(grid(run(kind,a)),-.5 if kind=='ndvi_change' else .5)
    elif kind=='sar_lee':
        a=constant(.5);a[0,0]=np.nan;a[1,1]=1
        result=grid(run(kind,{'power':a},{'radius':1,'enl':4}))
        assert np.isnan(result[0,0]);window=a[:3,:3];mu=np.nanmean(window);var=np.nanvar(window)
        expected=mu+max((var-mu**2/4)/1.25,0)/var*(a[1,1]-mu)
        assert result[1,1]==pytest.approx(expected)
        np.testing.assert_allclose(grid(run(kind,{'power':constant(.5)})),.5)
    elif kind in {'temporal_sen','temporal_trend_se'}:
        t=np.array([0,1,3,7],float);obs=np.array([1,2,4,14],float)
        a={f'date{i+1}':constant(v) for i,v in enumerate(obs)}
        params={f'time{i+1}':v for i,v in enumerate(t)}
        z=grid(run(kind,a,params))
        if kind=='temporal_sen':
            slopes=[(obs[j]-obs[i])/(t[j]-t[i]) for i in range(4) for j in range(i+1,4)]
            np.testing.assert_allclose(z,np.median(slopes))
        else:
            coef=np.polyfit(t,obs,1);rss=np.sum((obs-np.polyval(coef,t))**2)
            np.testing.assert_allclose(z,np.sqrt(rss/(len(t)-2)/np.sum((t-t.mean())**2)))
    elif kind in {'spectral_unmix','spectral_unmix_rmse'}:
        fractions=np.array([[0,0,.25,.5],[1,1,.75,.25],[.5,.5,0,1]])
        end1=np.array([.1,.2,.3,.4]);end2=np.array([.8,.6,.4,.2])
        a={r:(1-fractions)*v+fractions*w for r,v,w in zip(('blue','green','red','nir'),end1,end2)}
        labels=np.zeros_like(fractions);labels[0,:2]=1;labels[1,:2]=2;a['training']=labels
        r=run(kind,a,{'target_class':2} if kind=='spectral_unmix' else {})
        np.testing.assert_allclose(grid(r),fractions if kind=='spectral_unmix' else 0,atol=2e-5)
        assert r['receipt']['metrics']['maximum_fraction_sum_error']<1e-10
    else:
        pred=np.array([[1,1,1,1],[2,2,2,2]],float);ref=np.array([[1,2,np.nan,np.nan],[2,2,np.nan,np.nan]])
        r=run(kind,{'prediction':pred,'reference':ref});m=r['receipt']['metrics']
        assert m['area_adjusted_matrix_map_rows']==[[.25,.25],[0,.5]]
        assert m['area_adjusted_overall_accuracy']==.75
        assert m['overall_accuracy_standard_error']==pytest.approx(np.sqrt(.25*.5*.5*.5))


@pytest.mark.parametrize('kind',['true_color','false_color'])
def test_rgb_reference(kind):
    roles=[r for r,_ in BY_ID[kind].roles];a={role:constant(v) for role,v in zip(roles,(.8,.4,.2))}
    a[roles[0]][0,0]=np.nan
    r=run(kind,a)
    assert r['raster']['band_count']==3 and r['receipt']['metrics']['display_channel_order']==roles
    with MemoryFile(base64.b64decode(r['raster']['data'])) as mem,mem.open() as ds:
        assert ds.count==3 and list(ds.descriptions)==roles
        data=ds.read();assert np.isnan(data[:,0,0]).all()
        np.testing.assert_allclose(data[:,1,1],[.8,.4,.2])
    assert r['preview'] is not None
    assert r['figures'][0]['bands']==[1,2,3]


def test_rgb_actual_figure_workflow():
    client=TestClient(app);r=run('true_color',{'red':constant(.8),'green':constant(.4),'blue':constant(.2)})
    p=r['figures'][0];raster=r['raster']
    rasters=[{'name':raster['name']+' band '+str(b),'data':raster['data'],'band':b,'unit':'reflectance'} for b in p['bands']]
    response=client.post('/terrain/studio/render',json={'recipe':p['recipe'],'rasters':rasters,'format':'png'})
    assert response.status_code==200,response.text
    assert base64.b64decode(response.json()['figure']).startswith(b'\x89PNG')


def test_remote_gdal_reference(tmp_path):
    import os,shutil,subprocess
    import rasterio
    executable=shutil.which('gdalwarp')
    if executable is None:
        if os.environ.get('GEOFATHOM_REQUIRE_REMOTE_GDAL')=='1':pytest.fail('GDAL CLI required.')
        pytest.skip('GDAL CLI not installed.')
    target=np.ones((4,4));target[0,0]=np.nan
    s=source(np.array([[1,2],[3,4]],float),aff=from_origin(500000,4500000,20,20))
    src=tmp_path/'source.tif';src.write_bytes(base64.b64decode(s['data']))
    for kind,mode in [('align_continuous','bilinear'),('align_categorical','near')]:
        dst=tmp_path/(kind+'.tif')
        call=subprocess.run([executable,'-overwrite','-t_srs',CRS,'-te','500000','4499960','500040','4500000','-ts','4','4','-r',mode,'-srcnodata','nan','-dstnodata','nan','-ot','Float64',str(src),str(dst)],capture_output=True,text=True,timeout=45)
        assert call.returncode==0,call.stderr
        with rasterio.open(dst) as ds:expected=ds.read(1)
        expected[0,0]=np.nan
        result=execute(RemoteInput(operation=kind,sources=[source(target),s],bindings={'target':{'source':0},'source':{'source':1,'unit':'m' if mode=='bilinear' else ''}}))
        np.testing.assert_allclose(grid(result),expected,equal_nan=True,atol=1e-10)
