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
from imagery.remote_catalog import BY_ID,WINDOWED_IDS,WINDOWED_CUBES
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
    assert client.get('/analysis/remote-sensing/catalog').json()['operation_count']==len(BY_ID)==144

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


@pytest.mark.parametrize('kind',['surface_temperature_rte','topographic_c','ndvi_uncertainty','change_vector','change_mahalanobis','spatial_lda','series_median','series_count','series_slope','series_amplitude','series_harmonic_rmse'])
def test_research_depth_reference(kind):
    if kind=='surface_temperature_rte':
        t=310.;k1=774.8853;k2=1321.0789;e=.95;tau=.8;up=1.2;down=2.
        l=tau*(e*k1/np.expm1(k2/t)+(1-e)*down)+up
        a={r:constant(x) for r,x in [('radiance',l),('emissivity',e),('transmittance',tau),('upwelling',up),('downwelling',down)]}
        np.testing.assert_allclose(grid(run(kind,a)),t,atol=1e-10)
    elif kind=='topographic_c':
        s=np.arange(12,dtype=float).reshape(3,4)*3;aspect=constant(135.)
        cos=np.cos(np.deg2rad(s-30));r=.4*cos+.1
        result=run(kind,{'reflectance':r,'slope':s,'aspect':aspect,'calibration':constant(1)})
        np.testing.assert_allclose(grid(result),.4*np.cos(np.deg2rad(30))+.1,atol=1e-12)
        assert result['receipt']['metrics']['c']==pytest.approx(.25)
    elif kind=='ndvi_uncertainty':
        a={'nir':constant(.6),'red':constant(.2),'nir_sd':constant(.01),'red_sd':constant(.02)}
        for rho in (-1,0,1):
            expected=np.sqrt((.4/.64*.01)**2+(1.2/.64*.02)**2-2*rho*(.4/.64*.01)*(1.2/.64*.02))
            np.testing.assert_allclose(grid(run(kind,a,{'correlation':rho})),expected,atol=1e-12)
    elif kind in {'change_vector','change_mahalanobis'}:
        rng=np.random.default_rng(17);d=rng.normal(0,.02,(3,3,4));a={}
        for i,r in enumerate(('red','nir','swir')):
            a[r+'_before']=constant(.3);a[r+'_after']=constant(.3)+d[i]
        if kind=='change_vector':
            np.testing.assert_allclose(grid(run(kind,a)),np.linalg.norm(d,axis=0),atol=1e-12)
        else:
            a['calibration']=constant(1);a['calibration'][0,0]=0
            ref=d.reshape(3,-1).T[1:];cov=np.cov(ref,rowvar=False);cov=.98*cov+.02*np.trace(cov)/3*np.eye(3)
            delta=d.reshape(3,-1).T-ref.mean(axis=0)
            expected=np.sqrt(np.einsum('ij,jk,ik->i',delta,np.linalg.inv(cov),delta)).reshape(3,4)
            np.testing.assert_allclose(grid(run(kind,a)),expected,atol=1e-10)
    elif kind=='spatial_lda':
        rng=np.random.default_rng(27);row,col=np.indices((24,24));labels=1+(row%2)
        a={r:np.where(labels==1,.2,.8)+rng.normal(0,.01,labels.shape) for r in ('blue','green','red','nir')};a['training']=labels
        result=run(kind,a,{'block_m':40,'folds':5,'heldout_fold':0})
        np.testing.assert_array_equal(grid(result),labels)
        m=result['receipt']['metrics'];hold=((col//4+2*(row//4))%5)==0
        assert m['heldout_cells']==int(hold.sum()) and m['training_cells']==int((~hold).sum())
        assert m['overall_accuracy']==1
        # Changed held-out labels must not change the trained map.
        a['training']=np.where(hold,3-labels,labels)
        other=run(kind,a,{'block_m':40,'folds':5,'heldout_fold':0})
        np.testing.assert_array_equal(grid(other),labels);assert other['receipt']['metrics']['overall_accuracy']==0
    else:
        t=np.arange(12,dtype=float);y=3+2*t
        if kind in {'series_amplitude','series_harmonic_rmse'}:y=y+4*np.cos(2*np.pi*t/6)+3*np.sin(2*np.pi*t/6)
        arrays=np.array([constant(v) for v in y]);arrays[2,0,0]=np.nan
        s=source(arrays);bindings={f'date{i+1}':{'source':0,'band':i+1,'unit':'index'} for i in range(len(t))}
        result=checked(execute(RemoteInput(operation=kind,sources=[s],bindings=bindings,times=t.tolist(),parameters={'period':6} if kind in {'series_amplitude','series_harmonic_rmse'} else {})))
        z=grid(result)
        if kind=='series_count':assert z[0,0]==11 and z[1,1]==12
        elif kind=='series_median':assert z[0,0]==np.median(np.delete(y,2)) and z[1,1]==np.median(y)
        else:np.testing.assert_allclose(z,{'series_slope':2,'series_amplitude':5,'series_harmonic_rmse':0}[kind],atol=1e-10)
        assert result['receipt']['metrics']['acquisitions']==12
        assert len(result['rows'])==12


def test_windowed_scene_above_inline_budget(tmp_path):
    import rasterio
    from imagery.remote_windowed import process
    from rasterio.transform import from_origin
    shape=(1501,1503)
    # 2.25 million cells per band, larger than the inline API ceiling.
    row,col=np.indices(shape);nir=.3+(col%97)/200;red=.1+(row%53)/200
    nir[254:258,254:258]=np.nan
    qa=np.ones(shape);qa[510:514,700:704]=0
    inputs={}
    for role,z in [('nir',nir),('red',red),('qa',qa)]:
        path=tmp_path/(role+'.tif')
        with rasterio.open(path,'w',driver='GTiff',width=shape[1],height=shape[0],count=1,dtype='float64',crs=CRS,transform=AFF,nodata=np.nan) as ds:ds.write(z,1)
        inputs[role]={'path':str(path),'band':1}
    bindings={k:inputs[k] for k in ('nir','red')};quality=[{**inputs['qa'],'scheme':'binary'}]
    out=tmp_path/'ndvi.tif';receipt=process('ndvi',bindings,out,quality=quality,tile=256)
    expected=(nir-red)/(nir+red);expected[qa==0]=np.nan
    with rasterio.open(out) as ds:
        actual=ds.read(1);assert ds.transform==AFF and ds.crs.to_string()==CRS
    np.testing.assert_allclose(actual,expected,equal_nan=True,atol=1e-12)
    assert receipt['valid_cells']==int(np.isfinite(expected).sum()) and receipt['windows']==36
    assert receipt['sha256']==hashlib.sha256(out.read_bytes()).hexdigest()
    assert receipt['mean']==pytest.approx(np.nanmean(expected))
    with pytest.raises(FigureInputError):process('ndvi',bindings,out)
    # A failure in a late tile cannot leave a partial destination.
    with rasterio.open(inputs['nir']['path'],'r+') as ds:
        ds.write(np.array([[100.]]),1,window=rasterio.windows.Window(1500,1500,1,1))
    bad=tmp_path/'bad.tif'
    with pytest.raises(FigureInputError):process('ndvi',bindings,bad,quality=quality,tile=256)
    assert not bad.exists() and not list(tmp_path.glob('.remote-*'))


@pytest.mark.parametrize('kind',['sar_gamma_map','sar_log_change','sar_gamma0_flat','mad_distance'])
def test_sar_mad_reference(kind):
    if kind=='sar_gamma_map':
        a=np.array([[.5,.5,.5],[.5,1.6,.5],[.5,.5,.5]])
        result=run(kind,{'power':a},{'radius':1,'enl':4});mu=a.mean();cv2=a.var()/mu**2
        alpha=1.25/(cv2-.25);b=alpha-5
        expected=(b*mu+np.sqrt((b*mu)**2+16*alpha*mu*a[1,1]))/(2*alpha)
        assert .25<cv2<.5
        assert grid(result)[1,1]==pytest.approx(expected)
        np.testing.assert_allclose(grid(run(kind,{'power':constant(.5)})),.5)
    elif kind=='sar_log_change':
        a=constant(.1);b=constant(.2);a[0,0]=0
        z=grid(run(kind,{'before':a,'after':b}));assert np.isnan(z[0,0])
        assert z[1,1]==pytest.approx(10*np.log10(2))
    elif kind=='sar_gamma0_flat':
        a=constant(60);a[0,0]=90
        z=grid(run(kind,{'sigma0':constant(.2),'incidence':a}));assert np.isnan(z[0,0]);assert z[1,1]==pytest.approx(.4)
    else:
        rng=np.random.default_rng(91);x=rng.normal(.4,.05,(100,3));y=x+rng.normal(0,.01,x.shape)
        y[99]+=.2;cal=np.ones(100);cal[99]=0
        a={r+'_before':x[:,i].reshape(10,10) for i,r in enumerate(('red','nir','swir'))}
        a.update({r+'_after':y[:,i].reshape(10,10) for i,r in enumerate(('red','nir','swir'))});a['calibration']=cal.reshape(10,10)
        r=run(kind,a);out=grid(r).ravel()
        # Each of the three standardized stable canonical differences has
        # sample variance one and mean zero by construction.
        assert np.sum(out[:99])==pytest.approx(3*98,abs=1e-7)
        assert out[99]>np.quantile(out[:99],.99)
        assert all(0<=q<1 for q in r['receipt']['metrics']['canonical_correlations'])


@pytest.mark.parametrize('kind',['atmospheric_reflectance','robust_harmonization','irmad','cloud_buffer','series_break_time','series_break_jump','series_break_strength'])
def test_inference_reference(kind):
    if kind=='atmospheric_reflectance':
        surface=np.linspace(.05,.8,12).reshape(3,4);path=.06;trans=.7;albedo=.15
        toa=path+trans*surface/(1-albedo*surface)
        np.testing.assert_allclose(grid(run(kind,{'toa':toa,'path':constant(path),'transmission':constant(trans),'spherical_albedo':constant(albedo)})),surface,atol=1e-12)
    elif kind=='robust_harmonization':
        x=np.linspace(.1,.7,100).reshape(10,10);truth=.04+.9*x;y=truth.copy();y[2,3]=1.;y[3,4]=.01
        mask=np.ones(x.shape);mask[-1]=2
        r=run(kind,{'candidate':x,'reference':y,'calibration':mask})
        np.testing.assert_allclose(grid(r),truth,atol=1e-7)
        assert r['receipt']['metrics']['heldout_cells']==10 and r['receipt']['metrics']['heldout_rmse']<1e-7
    elif kind=='irmad':
        rng=np.random.default_rng(32);x=rng.normal(.4,.055,(400,3));y=x+rng.normal(0,.012,x.shape);y[-20:]+=.16
        a={r+'_before':x[:,i].reshape(20,20) for i,r in enumerate(('red','nir','swir'))}
        a.update({r+'_after':y[:,i].reshape(20,20) for i,r in enumerate(('red','nir','swir'))})
        r=run(kind,a,{'iterations':2});out=grid(r).ravel()
        # Independent first iteration and exact chi-square(3) weighting, then a second fit.
        def ref(w):
            mx=np.average(x,axis=0,weights=w);my=np.average(y,axis=0,weights=w)
            a=x-mx;b=y-my;cov=(a*w[:,None]).T@a/w.sum();cy=(b*w[:,None]).T@b/w.sum()
            la=np.linalg.cholesky(cov);lb=np.linalg.cholesky(cy)
            aa=np.linalg.solve(la,a.T).T;bb=np.linalg.solve(lb,b.T).T
            u,s,vt=np.linalg.svd((aa*w[:,None]).T@bb/w.sum())
            return np.sum((aa@u-bb@vt.T)**2/(2*(1-s)),axis=1)
        d=ref(np.ones(len(x)));q=np.sqrt(d/2)
        w=np.array([math.erfc(z) for z in q])+2/np.sqrt(np.pi)*q*np.exp(-q*q)
        np.testing.assert_allclose(out,ref(w),rtol=1e-9,atol=1e-9)
        assert np.median(out[-20:])>np.quantile(out[:-20],.9)
        assert len(r['rows'])==2
    elif kind=='cloud_buffer':
        z=np.ones((7,7));z[3,3]=0;z[0,0]=np.nan
        rr,cc=np.indices(z.shape);expected=(((rr-3)**2+(cc-3)**2>4)&(rr**2+cc**2>4)).astype(float);expected[0,0]=np.nan
        np.testing.assert_array_equal(grid(run(kind,{'qa':z},{'radius':2})),expected)
    else:
        t=[0,1,2,3,5,6,7,8,10,11];y=[2]*5+[7]*5;data=np.array([constant(v) for v in y])
        data[1,0,0]=np.nan;s=source(data);bindings={f'date{i+1}':{'source':0,'band':i+1,'unit':'index'} for i in range(len(t))}
        result=checked(execute(RemoteInput(operation=kind,sources=[s],bindings=bindings,times=t,parameters={'min_segment':3})))
        np.testing.assert_allclose(grid(result),{'series_break_time':5.5,'series_break_jump':5,'series_break_strength':1}[kind],atol=1e-12)


@pytest.mark.parametrize('kind',['spatial_rf_cv','spatial_svm_cv','spatial_lda_cv'])
def test_blocked_classifier_reference(kind):
    rng=np.random.default_rng(17);row,col=np.indices((24,24));labels=1+(row%2)
    a={r:np.where(labels==1,.2,.8)+rng.normal(0,.01,labels.shape) for r in ('blue','green','red','nir')}
    a['training']=labels.copy();params={'block_m':40,'folds':5}
    if kind=='spatial_rf_cv':params.update(trees=32,seed=7)
    r=run(kind,a,params);m=r['receipt']['metrics']
    np.testing.assert_array_equal(grid(r),labels)
    assert m['oof_confusion_matrix_reference_rows']==[[288,0],[0,288]]
    assert m['oof_cells']==576 and m['oof_macro_f1']==1
    assert sum(row[2] for row in r['rows'])==576
    assert all(row[1]+row[2]==576 and row[4]==1 for row in r['rows'])
    assert run(kind,a,params)['rows']==r['rows']
    with pytest.raises(FigureInputError,match='Each spatial fold'):
        run(kind,a,{**params,'block_m':10000})


@pytest.mark.parametrize('kind',['lst_uncertainty','sar_terrain_volume','sar_terrain_validity','register_translation'])
def test_physical_depth_reference(kind):
    if kind=='lst_uncertainty':
        names=('radiance','emissivity','transmittance','upwelling','downwelling');vals=np.array([10.,.95,.8,1.2,2.]);sd=np.array([.1,.01,.02,.05,.07])
        a={r:constant(v) for r,v in zip(names,vals)};a.update({r+'_sd':constant(v) for r,v in zip(names,sd)})
        def reference(q):
            l,e,t,u,d=q;b=(l-u-t*(1-e)*d)/(t*e)
            return 1321.0789/np.log1p(774.8853/b)
        jac=[]
        for j in range(5):
            delta=np.zeros(5);delta[j]=1e-5;jac.append((reference(vals+delta)-reference(vals-delta))/2e-5)
        np.testing.assert_allclose(grid(run(kind,a)),np.linalg.norm(np.array(jac)*sd),rtol=1e-8)
    elif kind in {'sar_terrain_volume','sar_terrain_validity'}:
        slope=np.array([[0,10,50],[0,10,60]],float);aspect=np.array([[90,90,90],[270,270,270]],float)
        a={'sigma0':np.full(slope.shape,.2),'incidence':np.full(slope.shape,40.),'slope':slope,'aspect':aspect}
        z=grid(run(kind,a,{'look_azimuth':90,'margin_deg':0}))
        if kind=='sar_terrain_validity':np.testing.assert_array_equal(z,[[1,1,0],[1,1,0]])
        else:
            expected=np.array([[.2/np.cos(np.deg2rad(40)),.2/np.cos(np.deg2rad(40))*np.tan(np.deg2rad(50))/np.tan(np.deg2rad(60)),np.nan],
                               [.2/np.cos(np.deg2rad(40)),.2/np.cos(np.deg2rad(40))*np.tan(np.deg2rad(50))/np.tan(np.deg2rad(40)),np.nan]])
            np.testing.assert_allclose(z,expected,equal_nan=True)
    else:
        rng=np.random.default_rng(81);ref=rng.normal(size=(32,32));candidate=np.full_like(ref,np.nan)
        candidate[2:,:-3]=ref[:-2,3:];mask=np.zeros_like(ref);mask[5:-5,5:-5]=1
        r=run(kind,{'reference':ref,'candidate':candidate,'calibration':mask});m=r['receipt']['metrics']
        assert (m['row_shift'],m['column_shift'])==(-2,3)
        assert m['correlation']==pytest.approx(1)
        z=grid(r);np.testing.assert_allclose(z[:-2,3:],ref[:-2,3:])
        assert np.isnan(z[-2:]).all() and np.isnan(z[:,:3]).all()
        with pytest.raises(FigureInputError):run(kind,{'reference':np.ones_like(ref),'candidate':np.ones_like(ref),'calibration':mask})


@pytest.mark.parametrize('kind',['spectral_absorption_depth','spectral_absorption_center','spectral_absorption_area','spectral_endmembers'])
def test_hyperspectral_reference(kind):
    w=[400,450,520,600,700,900];n=len(w)
    if kind=='spectral_endmembers':
        a=np.array([.8,.1,.1,.1,.1,.1]);b=np.array([.1,.8,.1,.1,.1,.1]);c=np.array([.1,.1,.8,.1,.1,.1])
        spectra=np.stack([a,b,c,(a+b)/2,(b+c)/2,(a+c)/2]*2).T.reshape(n,3,4)
    else:
        y=np.array([.8,.72,.4,.64,.72,.8]);spectra=np.broadcast_to(y[:,None,None],(n,3,4)).copy();spectra[2,0,0]=np.nan
    s=source(spectra);bindings={f'band{i+1}':{'source':0,'band':i+1} for i in range(n)}
    r=checked(execute(RemoteInput(operation=kind,sources=[s],bindings=bindings,times=w,parameters={'endmembers':3} if kind=='spectral_endmembers' else {})))
    if kind=='spectral_endmembers':
        selected=np.array([row[-1] for row in r['rows']]).reshape(3,n)
        assert {tuple(row) for row in selected}=={tuple(a),tuple(b),tuple(c)}
        assert len(r['figures'])>=3
    else:
        z=grid(r);assert np.isnan(z[0,0]);expected={'spectral_absorption_depth':.5,'spectral_absorption_center':520,'spectral_absorption_area':np.trapezoid(1-y/.8,w)}[kind]
        np.testing.assert_allclose(z[np.isfinite(z)],expected,atol=1e-12)


@pytest.mark.parametrize('kind',['lst_correlated_uncertainty'])
def test_correlated_thermal_reference(kind):
    names=('radiance','emissivity','transmittance','upwelling','downwelling');vals=np.array([10.,.95,.8,1.2,2.]);sd=np.array([.1,.01,.02,.05,.07])
    a={r:constant(v) for r,v in zip(names,vals)};a.update({r+'_sd':constant(v) for r,v in zip(names,sd)})
    def temperature(q):
        l,e,t,u,d=q;return 1321.0789/np.log1p(774.8853/((l-u-t*(1-e)*d)/(t*e)))
    jac=[]
    for j in range(5):
        delta=np.zeros(5);delta[j]=1e-5;jac.append((temperature(vals+delta)-temperature(vals-delta))/2e-5)
    corr=np.eye(5);corr[0,3]=corr[3,0]=.5;corr[1,2]=corr[2,1]=-.3
    g=np.array(jac)*sd
    np.testing.assert_allclose(grid(run(kind,a,{'rho03':.5,'rho12':-.3})),np.sqrt(g@corr@g),rtol=1e-8)
    with pytest.raises(FigureInputError,match='positive semidefinite'):
        run(kind,a,{'rho01':1,'rho02':1,'rho12':-1})


@pytest.mark.parametrize('kind',['season_peak','season_start','season_end','season_duration','segmented_count','segmented_first_break'])
def test_temporal_model_extension(kind):
    t=np.arange(18,dtype=float)
    if kind.startswith('season_'):
        y=10+.2*t+2*np.cos(2*np.pi*(t-2)/6);params={'period':6,'season_fraction':.5}
        expected={'season_peak':2,'season_start':.5,'season_end':3.5,'season_duration':3}[kind]
    else:
        y=np.repeat([2.,8.,-2.],6);params={'penalty':1,'min_segment':3}
        expected=2 if kind=='segmented_count' else 5.5
    data=np.array([constant(v) for v in y]);s=source(data)
    result=checked(execute(RemoteInput(operation=kind,sources=[s],bindings={f'date{i+1}':{'source':0,'band':i+1,'unit':'index'} for i in range(len(t))},times=t.tolist(),parameters=params)))
    np.testing.assert_allclose(grid(result),expected,atol=1e-9)


@pytest.mark.parametrize('kind',['register_subpixel'])
def test_subpixel_registration_reference(kind):
    from scipy.ndimage import gaussian_filter,map_coordinates
    rng=np.random.default_rng(163);ref=gaussian_filter(rng.normal(size=(64,64)),1.5)
    rr,cc=np.indices(ref.shape,dtype=float);candidate=map_coordinates(ref,[rr-1.25,cc+2.4],order=3,mode='constant',cval=np.nan)
    mask=np.zeros_like(ref);mask[8:-8,8:-8]=1;mask[20:24,20:24]=2
    result=run(kind,{'reference':ref,'candidate':candidate,'calibration':mask},{'peak_margin':.001})
    m=result['receipt']['metrics']
    assert m['subpixel_row_shift']==pytest.approx(-1.25,abs=.15)
    assert m['subpixel_column_shift']==pytest.approx(2.4,abs=.15)
    assert m['refined_correlation']>.98
    assert m['heldout_cells']==16 and m['heldout_rmse']<.05


@pytest.mark.parametrize('kind',['spatial_nested_svm'])
def test_nested_spatial_reference(kind):
    rng=np.random.default_rng(17);row,col=np.indices((24,24));labels=1+(row%2)
    a={r:np.where(labels==1,.2,.8)+rng.normal(0,.01,labels.shape) for r in ('blue','green','red','nir')}
    a['training']=labels.copy();params={'block_m':40,'folds':5}
    result=run(kind,a,params);m=result['receipt']['metrics']
    assert m['oof_confusion_matrix_reference_rows']==[[288,0],[0,288]]
    assert m['oof_cells']==576 and len(result['rows'])==5
    assert sum(row[2] for row in result['rows'])==576
    np.testing.assert_array_equal(grid(result),labels)
    # Corrupt only one outer fold: its hyperparameter selection must not change.
    hold=((col//4+2*(row//4))%5)==0
    a['training']=np.where(hold,3-labels,labels)
    changed=run(kind,a,params)
    assert changed['rows'][0][3:5]==result['rows'][0][3:5]
    assert changed['rows'][0][5]==0


@pytest.mark.parametrize('kind',['sar_calibrated_power','insar_wrapped_phase','insar_coherence','cloud_candidates'])
def test_sar_complex_cloud_reference(kind):
    if kind=='sar_calibrated_power':
        a=constant(2);a[0,0]=0
        z=grid(run(kind,{'amplitude':a,'gain':constant(.5),'noise':constant(.1)}))
        assert np.isnan(z[0,0]);np.testing.assert_allclose(z[np.isfinite(z)],.9)
    elif kind.startswith('insar_'):
        rng=np.random.default_rng(54);master=rng.normal(size=(7,7))+1j*rng.normal(size=(7,7))
        slave=master*np.exp(-.7j);master[0,0]=np.nan
        a={'master_real':master.real,'master_imag':master.imag,'slave_real':slave.real,'slave_imag':slave.imag}
        z=grid(run(kind,a));assert np.isnan(z[0,0]);np.testing.assert_allclose(z[np.isfinite(z)],.7 if kind=='insar_wrapped_phase' else 1,atol=1e-12)
        if kind=='insar_coherence':
            slave=rng.normal(size=(7,7))+1j*rng.normal(size=(7,7))
            a.update(slave_real=slave.real,slave_imag=slave.imag)
            z=grid(run(kind,a,{'radius':1,'min_samples':3}))
            x=master[2:5,2:5].ravel();y=slave[2:5,2:5].ravel()
            assert z[3,3]==pytest.approx(abs(x@np.conj(y))/np.sqrt((abs(x)**2).sum()*(abs(y)**2).sum()))
    else:
        a={r:constant(.5) for r in ('blue','green','red','nir','swir1')}
        a['blue'][0,0]=.1;a['swir1'][0,1]=.05;a['nir'][0,2]=np.nan
        z=grid(run(kind,a));assert z[0,0]==0 and z[0,1]==0 and np.isnan(z[0,2])
        assert z[1,1]==1


def test_external_reference_comparison(tmp_path):
    from scripts.remote_scene_reference import compare
    a=tmp_path/'actual.tif';b=tmp_path/'reference.tif'
    z=np.arange(12,dtype=float).reshape(3,4);z[0,0]=np.nan
    a.write_bytes(base64.b64decode(source(z)['data']));b.write_bytes(base64.b64decode(source(z+.01)['data']))
    report=compare(a,b,.011,minimum=10);assert report['passed'] and report['paired_cells']==11
    assert report['rmse']==pytest.approx(.01)
    assert not compare(a,b,.005)['passed']
    z[0,0]=0;b.write_bytes(base64.b64decode(source(z)['data']))
    assert not compare(a,b,1)['passed'] and compare(a,b,1)['mask_disagreement']==1


def test_new_research_figure_rendering():
    from terrain.studio_routes import StudioInput
    from terrain.studio_render import render
    rng=np.random.default_rng(42);row,col=np.indices((24,24));labels=1+(row%2)
    a={r:np.where(labels==1,.2,.8)+rng.normal(0,.01,labels.shape) for r in ('blue','green','red','nir')};a['training']=labels
    results=[run('spatial_nested_svm',a,{'block_m':40,'folds':5})]
    t=np.arange(12,dtype=float);data=np.array([constant(2+np.sin(2*np.pi*q/6)) for q in t]);s=source(data)
    results.append(execute(RemoteInput(operation='season_peak',sources=[s],bindings={f'date{i+1}':{'source':0,'band':i+1,'unit':'index'} for i in range(len(t))},times=t.tolist(),parameters={'period':6})))
    x=rng.normal(.4,.05,(100,3));y=x+rng.normal(0,.015,x.shape)
    a={r+'_before':x[:,i].reshape(10,10) for i,r in enumerate(('red','nir','swir'))};a.update({r+'_after':y[:,i].reshape(10,10) for i,r in enumerate(('red','nir','swir'))})
    results.append(run('irmad',a,{'iterations':3}))
    labels=np.resize([1.,2.,3.],(6,8));spectra={r:labels*.2 for r in ('blue','green','red','nir')}
    results.append(run('spectral_kmeans',spectra,{'clusters':3}))
    results.append(run('continuous_reference_error',{'prediction':constant(.3),'reference':constant(.4)}))
    results.append(run('binary_reference_error',{'prediction':np.resize([0.,0.,1.,1.],(3,4)),'reference':np.resize([0.,1.,0.,1.],(3,4))}))
    titles=set()
    for result in results:
        for figure in result['figures']:
            if figure['raster']:continue
            image,_,_=render(StudioInput(recipe=figure['recipe'],csv=figure['csv'],**figure['bindings']))
            assert image.startswith(b'\x89PNG') and len(image)>100
            titles.add(figure['title'])
    assert {'Nested spatial outer-fold accuracy','Nested spatial selected C','Acquisition mean time series','Canonical correlation convergence','Spectral cluster population','Cluster 1 mean spectrum','Reference residual quantiles','Reference error by outcome'}<=titles


def test_managed_disk_job_snapshot_and_cancellation(tmp_path,monkeypatch):
    import rasterio
    from imagery.remote_managed import run_managed
    from imagery import remote_managed
    from uuid import uuid4
    ids=[str(uuid4()),str(uuid4())]
    monkeypatch.setenv('GEOFATHOM_IMAGERY_DIR',str(tmp_path))
    for uid,z in zip(ids,(np.full((130,130),.6),np.full((130,130),.2))):
        (tmp_path/(uid+'.tif')).write_bytes(base64.b64decode(source(z)['data']))
    target=tmp_path/'out.tif';monkeypatch.setattr(remote_managed,'result_path',lambda _:target)
    payload={'operation':'ndvi','bindings':{'nir':{'image_id':ids[0]},'red':{'image_id':ids[1]}},'tile':64}
    progress=[];r=run_managed(payload,str(uuid4()),progress.append,lambda:None)
    assert progress[-1]==1 and r['windows']==9
    assert r['bands']['nir']['image_id']==ids[0] and 'path' not in r['bands']['nir']
    with rasterio.open(target) as ds:np.testing.assert_allclose(ds.read(1),.5)
    target.unlink()
    def cancel(value):raise RuntimeError('cancelled')
    with pytest.raises(RuntimeError,match='cancelled'):run_managed(payload,str(uuid4()),cancel,lambda:None)
    assert not target.exists()


@pytest.mark.parametrize('kind',['cloud_shadow_candidates','cloud_shadow_clear'])
def test_cloud_shadow_reference(kind):
    cloud=np.zeros((9,9));cloud[3,5]=1;nir=np.full(cloud.shape,.4);nir[3,3]=.1;nir[3,2]=.1
    land=np.ones_like(cloud);land[3,2]=0;nir[0,0]=np.nan
    result=run(kind,{'cloud':cloud,'nir':nir,'land':land},{'solar_zenith':45,'solar_azimuth':90,'cloud_height_m':20})
    out=grid(result);m=result['receipt']['metrics'];assert m['column_displacement']==-2 and m['row_displacement']==0
    assert m['candidate_shadow_cells']==1 and np.isnan(out[0,0])
    if kind=='cloud_shadow_candidates':
        assert out[3,3]==1 and out[3,5]==0 and np.nansum(out)==1
    else:
        assert out[3,3]==0 and out[3,5]==0 and out[3,2]==1 and np.count_nonzero(out==0)==2


@pytest.mark.parametrize('kind',['fusion_gls','fusion_gls_sd','fusion_discrepancy','canopy_lai','canopy_fpar_proxy','spectral_kmeans','spectral_kmeans_distance'])
def test_fusion_biophysical_reference(kind):
    if kind.startswith('fusion_'):
        a={r:constant(v) for r,v in [('first',10),('second',14),('first_sd',2),('second_sd',3)]}
        rho=.4;cov=np.array([[4,6*rho],[6*rho,9]]);inverse=np.linalg.inv(cov);ones=np.ones(2)
        expected={'fusion_gls':(ones@inverse@np.array([10,14]))/(ones@inverse@ones),'fusion_gls_sd':np.sqrt(1/(ones@inverse@ones)),
                  'fusion_discrepancy':4/np.sqrt(13-12*rho)}[kind]
        np.testing.assert_allclose(grid(run(kind,a,{'correlation':rho})),expected,atol=1e-12)
        a['first_sd'][0,0]=0
        with pytest.raises(FigureInputError,match='positive'):run(kind,a)
    elif kind.startswith('canopy_'):
        lai=np.linspace(0,5,12).reshape(3,4);gap=np.exp(-.6*.8*lai)
        params={'extinction':.6,'clumping':.8,'par_extinction':.7}
        np.testing.assert_allclose(grid(run(kind,{'gap':gap},params)),lai if kind=='canopy_lai' else 1-np.exp(-.7*.8*lai),atol=1e-12)
    else:
        labels=np.repeat([1,2,3],16).reshape(6,8);x=labels*.2
        a={r:x.copy() for r in ('blue','green','red','nir')}
        r=run(kind,a,{'clusters':3,'seed':12})
        np.testing.assert_allclose(grid(r),labels if kind=='spectral_kmeans' else 0,atol=1e-12)
        assert [row[1] for row in r['rows']]==[16,16,16]


@pytest.mark.parametrize('kind',['sar_lee','sar_gamma_map','cloud_buffer','ndvi_change','surface_temperature_rte','fusion_gls','canopy_lai'])
def test_windowed_science_matches_inline_across_seams(kind,tmp_path):
    import rasterio
    from imagery.remote_windowed import process
    rng=np.random.default_rng(12);shape=(131,137)
    a={}
    for role,quantity in BY_ID[kind].roles:
        if quantity=='class':z=np.ones(shape);z[62:66,62:66]=0
        elif quantity=='reflectance':z=rng.uniform(.15,.7,shape)
        elif quantity in {'emissivity','transmittance','fraction'}:z=rng.uniform(.7,.98,shape)
        elif quantity=='radiance':z=np.full(shape,10. if role=='radiance' else 1.)
        else:z=rng.uniform(.5,1.5,shape)
        z[63:65,65:67]=np.nan;a[role]=z
    expected=grid(run(kind,a))
    bindings={}
    for role,quantity in BY_ID[kind].roles:
        path=tmp_path/(role+'.tif');path.write_bytes(base64.b64decode(source(a[role])['data']))
        bindings[role]={'path':str(path),'unit':'m' if quantity=='numeric' else ''}
    for tile in (64,96):
        out=tmp_path/(str(tile)+'.tif');report=process(kind,bindings,out,tile=tile)
        with rasterio.open(out) as ds:
            assert ds.transform==AFF and ds.crs.to_string()==CRS
            np.testing.assert_allclose(ds.read(1),expected,atol=1e-12,rtol=1e-12,equal_nan=True)
        assert report['valid_cells']==np.isfinite(expected).sum()


@pytest.mark.parametrize('kind',sorted(WINDOWED_IDS-WINDOWED_CUBES))
def test_every_disk_method_matches_inline(kind,tmp_path):
    import rasterio
    from imagery.remote_windowed import process
    rng=np.random.default_rng(17);shape=(67,69);a={};bindings={}
    for role,q in BY_ID[kind].roles:
        if q=='class':
            code={'sentinel_clear':4,'landsat_clear':64,'landsat_unsaturated':0}.get(kind,1)
            z=np.full(shape,float(code));z[31:34,61:66]=9 if kind=='sentinel_clear' else 8 if kind.startswith('landsat_') else 0
        elif q=='reflectance':z=rng.uniform(.2,.6,shape)
        elif q in {'emissivity','transmittance','fraction'}:z=rng.uniform(.7,.95,shape)
        elif q=='radiance':z=rng.uniform(9,11,shape) if role=='radiance' else rng.uniform(.8,1.2,shape)
        elif q=='kelvin':z=rng.uniform(280,320,shape)
        elif q=='db':z=rng.uniform(-20,-3,shape)
        elif q in {'radiance_sd','fraction_sd','nonnegative'}:z=rng.uniform(.01,.03,shape)
        elif role.endswith('_sd'):z=rng.uniform(.2,1.2,shape)
        else:z=rng.uniform(.1,2,shape)
        z[33,64]=np.nan;a[role]=z
        path=tmp_path/(role+'.tif');path.write_bytes(base64.b64decode(source(z)['data']))
        bindings[role]={'path':str(path),'unit':'m' if q=='numeric' else ''}
    expected=grid(run(kind,a))
    output=tmp_path/'disk.tif';receipt=process(kind,bindings,output,tile=64)
    with rasterio.open(output) as ds:
        assert ds.transform==AFF and ds.crs.to_string()==CRS
        np.testing.assert_allclose(ds.read(1),expected,rtol=1e-11,atol=1e-11,equal_nan=True)
    assert receipt['valid_cells']==int(np.isfinite(expected).sum())
    assert receipt['sha256']==hashlib.sha256(output.read_bytes()).hexdigest()


def test_disk_per_role_qa_and_calibration(tmp_path):
    import rasterio
    from imagery.remote_windowed import process
    shape=(67,69);a=np.full(shape,24000.);b=np.full(shape,14000.)
    mask=np.ones(shape);mask[62:65,63:66]=0
    arrays={'nir':a,'red':b,'qa':mask};paths={}
    for role,z in arrays.items():
        path=tmp_path/(role+'.tif');path.write_bytes(base64.b64decode(source(z)['data']));paths[role]=path
    bindings={r:{'path':str(paths[r]),'encoding':'landsat_sr'} for r in ('nir','red')}
    quality=[{'path':str(paths['qa']),'scheme':'binary','roles':['nir']}]
    report=process('ndvi',bindings,tmp_path/'ndvi.tif',quality=quality,tile=64)
    expected=(.46-.185)/(.46+.185)
    with rasterio.open(tmp_path/'ndvi.tif') as ds:
        z=ds.read(1);assert np.isnan(z[mask==0]).all()
        np.testing.assert_allclose(z[mask==1],expected,atol=1e-12)
    assert report['quality_masks'][0]['roles']==['nir']
    # Conflicting native physical calibration must fail before publication.
    paths['nir'].write_bytes(base64.b64decode(source(a,scales=[.001],offsets=[0])['data']))
    with pytest.raises(FigureInputError,match='conflicts'):
        process('ndvi',bindings,tmp_path/'invalid.tif')
    assert not (tmp_path/'invalid.tif').exists()


def test_public_fixture_transport_fallback_and_checksum(tmp_path,monkeypatch):
    import io
    import urllib.error
    from scripts import remote_scene_reference as scene
    data=b'example fixture bytes';expected=hashlib.md5(data).hexdigest();calls=[]
    def request(req,timeout):
        calls.append(req.full_url)
        if len(calls)==1:raise urllib.error.HTTPError(req.full_url,403,'Forbidden',None,None)
        return io.BytesIO(data)
    monkeypatch.setattr(scene.urllib.request,'urlopen',request)
    path=scene.obtain(tmp_path,'B04.tif',expected)
    assert path.read_bytes()==data and '/api/records/' in calls[0] and '?download=1' in calls[1]
    assert not list(tmp_path.glob('*.part'))
    path.unlink()
    monkeypatch.setattr(scene.urllib.request,'urlopen',lambda *a,**k:io.BytesIO(b'wrong'))
    with pytest.raises(ValueError,match='checksum'):scene.obtain(tmp_path,'B04.tif',expected)
    assert not path.exists() and not list(tmp_path.glob('*.part'))


@pytest.mark.parametrize('kind',sorted(WINDOWED_CUBES))
def test_disk_cube_matches_inline(kind,tmp_path):
    import rasterio
    from imagery.remote_catalog import HYPER_IDS
    from imagery.remote_windowed import process
    shape=(67,69);n=18;row,col=np.indices(shape)
    spectral=kind in HYPER_IDS
    times=np.linspace(400,900,n).tolist() if spectral else list(range(n))
    names=[('band' if spectral else 'date')+str(i+1) for i in range(n)]
    if spectral:
        values=.7-.3*np.exp(-((np.arange(n)-8)/3)**2);p={}
    elif kind.startswith('segmented_'):
        values=np.repeat([2.,8.,-2.],6);p={'penalty':1}
    elif kind.startswith('series_break_'):
        values=np.repeat([2.,8.],9);p={}
    else:
        values=3+.1*np.arange(n)+np.cos(2*np.pi*(np.arange(n)-2)/6)
        p={'period':6} if kind.startswith('season_') or kind in {'series_amplitude','series_harmonic_rmse'} else {}
    stack=np.broadcast_to(values[:,None,None],(n,*shape)).copy()
    stack[3,30:34,62:66]=np.nan
    stack[:,0,0]=np.nan
    # Independent per-acquisition QA crosses a tile edge.
    qa=np.ones(shape);qa[62:65,63:66]=0
    s=source(stack);q=source(qa)
    bindings={r:{'source':0,'band':i+1,'unit':'' if spectral else 'index'} for i,r in enumerate(names)}
    expected=grid(checked(execute(RemoteInput(operation=kind,sources=[s,q],bindings=bindings,
        times=times,parameters=p,quality=[{'source':1,'scheme':'binary','roles':[names[1]]}]))))
    data=tmp_path/'cube.tif';data.write_bytes(base64.b64decode(s['data']))
    mask=tmp_path/'qa.tif';mask.write_bytes(base64.b64decode(q['data']))
    spec={r:{'path':str(data),'band':i+1,'unit':'' if spectral else 'index'} for i,r in enumerate(names)}
    out=tmp_path/'out.tif'
    report=process(kind,spec,out,parameters=p,times=times,tile=64,quality=[{'path':str(mask),'scheme':'binary','roles':[names[1]]}])
    with rasterio.open(out) as ds:np.testing.assert_allclose(ds.read(1),expected,atol=1e-10,rtol=1e-10,equal_nan=True)
    assert report['axis_values']==times and report['valid_cells']==int(np.isfinite(expected).sum())


@pytest.mark.parametrize('kind',['align_area_mean','align_area_coverage','continuous_reference_error','binary_reference_error'])
def test_resolution_and_reference_accuracy(kind):
    if kind.startswith('align_area_'):
        fine=np.arange(48,dtype=float).reshape(6,8)
        fine[0,0]=np.nan;fine[2:4,2:4]=np.nan
        target=np.ones((3,4));target[2,3]=np.nan
        sources=[source(target),source(fine,aff=from_origin(500000,4500000,5,5))]
        r=execute(RemoteInput(operation=kind,sources=sources,bindings={'target':{'source':0},'source':{'source':1,'unit':'m'}},parameters={'minimum_coverage':.8}))
        z=grid(r);expected=np.full((3,4),np.nan)
        for i,j in np.ndindex(expected.shape):
            sub=fine[2*i:2*i+2,2*j:2*j+2];valid=np.isfinite(sub);coverage=valid.sum()/4
            if np.isfinite(target[i,j]):
                if kind=='align_area_coverage':expected[i,j]=coverage
                elif coverage>=.8:expected[i,j]=sub[valid].mean()
        np.testing.assert_allclose(z,expected,equal_nan=True)
        sources[1]=source(fine,aff=from_origin(500001,4500000,5,5))
        with pytest.raises(FigureInputError,match='align'):
            execute(RemoteInput(operation=kind,sources=sources,bindings={'target':{'source':0},'source':{'source':1,'unit':'m'}}))
    elif kind=='continuous_reference_error':
        reference=np.arange(12,dtype=float).reshape(3,4);prediction=reference+np.resize([1,-1,2,-2],reference.shape)
        prediction[0,0]=np.nan;d=(prediction-reference)[np.isfinite(prediction)]
        r=run(kind,{'prediction':prediction,'reference':reference});m=r['receipt']['metrics']
        np.testing.assert_allclose(grid(r),prediction-reference,equal_nan=True)
        assert m['bias']==pytest.approx(d.mean()) and m['rmse']==pytest.approx(np.sqrt((d*d).mean()))
        assert m['mask_disagreement']==1 and m['paired_cells']==11
        assert m['mae']==pytest.approx(abs(d).mean())
    else:
        reference=np.array([[0,0,1,1],[0,1,1,0],[0,0,1,1]],float)
        prediction=np.array([[0,1,0,1],[0,1,1,0],[1,0,1,1]],float)
        r=run(kind,{'prediction':prediction,'reference':reference});m=r['receipt']['metrics']
        np.testing.assert_array_equal(grid(r),2*reference+prediction)
        assert m['confusion_matrix_reference_rows']==[[4,2],[1,5]]
        assert m['iou']==pytest.approx(5/8) and m['recall']==pytest.approx(5/6)


def test_external_reference_streaming_across_windows(tmp_path):
    from scripts.remote_scene_reference import compare
    z=np.arange(519*521,dtype=float).reshape(519,521)/1000
    ref=z.copy();ref[510:515,510:515]=np.nan;z[510:515,510:515]=np.nan
    z[-1,-1]+=.5
    a=tmp_path/'a.tif';b=tmp_path/'b.tif'
    a.write_bytes(base64.b64decode(source(z)['data']));b.write_bytes(base64.b64decode(source(ref)['data']))
    n=int(np.isfinite(ref).sum());report=compare(a,b,.1,minimum=1000)
    assert not report['passed'] and report['paired_cells']==n
    assert report['maximum_absolute_error']==pytest.approx(.5)
    assert report['rmse']==pytest.approx(.5/np.sqrt(n))
    assert report['bias']==pytest.approx(.5/n)
    assert compare(a,b,.51)['passed']


def test_native_public_scene_crop_calibration(tmp_path,monkeypatch):
    import rasterio
    from imagery import remote_scene
    from rasterio.warp import transform_bounds
    names={'red':2000.,'nir':6000.};paths={}
    for role,value in names.items():
        path=tmp_path/(role+'.tif');path.write_bytes(base64.b64decode(source(np.full((10,10),value))['data']));paths[role]=path
    host='e84-earth-search-sentinel-data.s3.us-west-2.amazonaws.com'
    hrefs={role:'https://'+host+'/'+role+'.tif' for role in names}
    monkeypatch.setattr(remote_scene,'fetch_stac_item',lambda *args:{'properties':{'datetime':'2023-09-07T00:00:00Z'},'assets':{r:{'href':href,'raster:bands':[{'scale':.0001,'offset':-.1}]} for r,href in hrefs.items()}})
    actual_open=rasterio.open
    def mapped(path,*args,**kwargs):
        for role,href in hrefs.items():
            if path=='/vsicurl/'+href:return actual_open(paths[role],*args,**kwargs)
        return actual_open(path,*args,**kwargs)
    monkeypatch.setattr(remote_scene.rasterio,'open',mapped)
    bbox=transform_bounds(CRS,'EPSG:4326',500020,4499920,500080,4499980)
    result=remote_scene.read_scene('sentinel-2-c1-l2a','S2_test_scene',bbox,['red','nir'])
    assert [b['role'] for b in result['bands']]==['red','nir']
    for band,value in zip(result['bands'],(.1,.5)):
        with MemoryFile(base64.b64decode(band['data'])) as mem,mem.open() as ds:
            assert ds.transform.a==10 and ds.transform.e==-10
            np.testing.assert_allclose(ds.read(1),value)
        assert band['calibration']['offset']==-.1
    with pytest.raises(ValueError):remote_scene.read_scene('sentinel-2-c1-l2a','S2_test_scene',bbox,['invalid'])


@pytest.mark.parametrize('kind',['spectral_rx','spectral_mnf','spectral_matched_filter','lai_library_mean','lai_library_sd','lai_library_misfit'])
def test_spectral_inference_reference(kind):
    rng=np.random.default_rng(132)
    if kind.startswith('lai_'):
        library=[[1.,1.,.2,.3,.4,.5],[3.,2.,.4,.5,.6,.7],[5.,1.,.6,.7,.8,.9]]
        a={r:constant(z) for r,z in zip(('blue','green','red','nir'),(.31,.41,.51,.61))}
        p={r+'_sd':.15 for r in a};p['max_chi2']=100
        r=run(kind,a,p,library=library)
        t=np.asarray(library);chi=np.sum(((t[:,2:]-np.array([.31,.41,.51,.61]))/.15)**2,axis=1)
        weight=t[:,1]*np.exp(-chi/2);weight/=weight.sum();mean=weight@t[:,0]
        expected={'lai_library_mean':mean,'lai_library_sd':np.sqrt(weight@((t[:,0]-mean)**2)),'lai_library_misfit':chi.min()}[kind]
        np.testing.assert_allclose(grid(r),expected,atol=1e-12)
        assert len(r['receipt']['metrics']['library_sha256'])==64
    elif kind=='spectral_matched_filter':
        a=rng.uniform(.2,.4,(4,8,8));mask=np.ones((8,8));mask[-1]=2;a[:,-1]+=.3
        r=run(kind,{**dict(zip(('blue','green','red','nir'),a)),'calibration':mask})
        z=grid(r);assert z[mask==1].mean()==pytest.approx(0,abs=1e-12);assert z[mask==2].mean()==pytest.approx(1)
        b=a[:,mask==1].T;mu=b.mean(axis=0);delta=a[:,mask==2].mean(axis=1)-mu;c=np.cov(b,rowvar=False);c=.95*c+.05*np.trace(c)/4*np.eye(4)
        w=np.linalg.inv(c)@delta;np.testing.assert_allclose(z,((a.reshape(4,-1).T-mu)@w/(delta@w)).reshape(8,8))
    else:
        a=rng.uniform(.2,.6,(6,8,8));s=source(a);wavelength=[400,450,500,600,700,800]
        result=checked(execute(RemoteInput(operation=kind,sources=[s],bindings={f'band{i+1}':{'source':0,'band':i+1} for i in range(6)},times=wavelength)))
        z=grid(result);x=a.reshape(6,-1).T;center=x-x.mean(axis=0);c=np.cov(x,rowvar=False)
        if kind=='spectral_rx':
            c=.95*c+.05*np.trace(c)/6*np.eye(6)
            np.testing.assert_allclose(z.ravel(),np.einsum('ni,ij,nj->n',center,np.linalg.inv(c),center),atol=1e-10)
        else:
            d=np.concatenate([(a[:,:,1:]-a[:,:,:-1]).reshape(6,-1).T,(a[:,1:,:]-a[:,:-1,:]).reshape(6,-1).T])
            noise=np.cov(d,rowvar=False)/2;noise=.95*noise+.05*np.trace(noise)/6*np.eye(6)
            eig=np.linalg.eigvals(np.linalg.solve(noise,c)).real.max()
            assert result['rows'][0][1]==pytest.approx(eig)
            assert np.var(z,ddof=1)==pytest.approx(eig)


@pytest.mark.parametrize('kind',['sar_dual_entropy','sar_dual_purity','sar_dual_minor_fraction','brdf_ross_li','fusion_support_temporal','cloud_probability_model','shadow_probability_model'])
def test_advanced_analysis_ready_reference(kind):
    if kind.startswith('sar_dual_'):
        a={'c11':constant(3),'c22':constant(1),'c12_real':constant(1),'c12_imag':constant(.5)}
        eigen=np.linalg.eigvalsh([[3,1+.5j],[1-.5j,1]])/4
        expected={'sar_dual_entropy':-sum(eigen*np.log2(eigen)),'sar_dual_purity':eigen[1]-eigen[0],'sar_dual_minor_fraction':eigen[0]}[kind]
        np.testing.assert_allclose(grid(run(kind,a)),expected,atol=1e-12)
        a['c12_real']=constant(3)
        with pytest.raises(FigureInputError,match='positive semidefinite'):run(kind,a)
    elif kind=='brdf_ross_li':
        a={'reflectance':constant(.3),'f_iso':constant(.3),'f_vol':constant(.05),'f_geo':constant(.02)}
        # At nadir with sun at zenith both kernels vanish; source geometry
        # uses a nonzero phase. Independent direct special-case calculation.
        s=np.deg2rad(30);vol=((np.pi/2-s)*np.cos(s)+np.sin(s))/(np.cos(s)+1)-np.pi/4
        t=np.arccos(np.clip(2*np.tan(s)/(1+1/np.cos(s)),-1,1))
        geo=(t-np.sin(t)*np.cos(t))*(1+1/np.cos(s))/np.pi-(1+1/np.cos(s))+(1+np.cos(s))/(2*np.cos(s))
        params={'solar_zenith':30,'view_zenith':0,'target_solar_zenith':0,'target_view_zenith':0}
        np.testing.assert_allclose(grid(run(kind,a,params)),.3*.3/(.3+.05*vol+.02*geo),atol=1e-12)
        params['target_solar_zenith']=30
        np.testing.assert_allclose(grid(run(kind,a,params)),.3,atol=1e-12)
    elif kind=='fusion_support_temporal':
        fine=np.tile([[.2,.3],[.4,.5]],(3,3));coarse=np.repeat(np.repeat(np.array([[.35,.35,.35],[.35,.35,.35],[.35,.35,.35]]),2,0),2,1)
        a={'fine_before':fine,'coarse_before':coarse,'coarse_after':coarse+.1}
        z=grid(run(kind,a));np.testing.assert_allclose(z,fine+.1,atol=1e-12)
        target=coarse.copy();target[:2,:2]+=.2;a['coarse_after']=target
        z=grid(run(kind,a));np.testing.assert_allclose(z.reshape(3,2,3,2).mean(axis=(1,3)),target[::2,::2],atol=1e-12)
        a['coarse_after'][0,0]+=.01
        with pytest.raises(FigureInputError,match='replicated'):run(kind,a)
    else:
        rng=np.random.default_rng(42);row,col=np.indices((30,30));label=1+row%3
        a={r:.15+.25*(label-1)+rng.normal(0,.005,label.shape) for r in ('blue','green','red','nir','swir1','swir2')};a['training']=label
        r=run(kind,a,{'block_m':40,'iterations':80});m=r['receipt']['metrics'];z=grid(r)
        target=2 if kind=='cloud_probability_model' else 3
        assert np.mean(z[label==target])>.9 and np.mean(z[label!=target])<.1
        assert m['oof_cells']==900 and m['oof_accuracy']>.98
        assert m['oof_multiclass_brier']<.05 and m['oof_log_loss']<.15


@pytest.mark.parametrize('kind',['insar_phase_wls','insar_relative_range'])
def test_anchored_phase_reference(kind):
    row,col=np.indices((12,14));truth=.8*row+.65*col
    phase=np.angle(np.exp(1j*truth));coherence=np.full(truth.shape,.9)
    coherence[:,9]=0
    params={'reference_row':0,'reference_col':0,'reference_phase':0}
    if kind=='insar_relative_range':params.update(wavelength_m=.06,range_sign=-1)
    r=run(kind,{'phase':phase,'coherence':coherence},params);z=grid(r);m=r['receipt']['metrics']
    expected=truth[:,:9] if kind=='insar_phase_wls' else -truth[:,:9]*.06/(4*np.pi)
    np.testing.assert_allclose(z[:,:9],expected,atol=1e-7)
    assert np.isnan(z[:,9:]).all() and m['excluded_disconnected_cells']==48
    assert m['wrapped_consistency_rmse_rad']<1e-7
    with pytest.raises(FigureInputError,match='congruent'):
        run(kind,{'phase':phase,'coherence':coherence},{**params,'reference_phase':.5})


def test_prosail_library_response_integration():
    from scripts.build_prosail_library import simulate,WAVELENGTH,BOUNDS
    responses={r:[[w-10,0],[w,1],[w+10,0]] for r,w in zip(('blue','green','red','nir'),(480,550,660,840))}
    sample={name:(lo+hi)/2 for name,(lo,hi) in BOUNDS.items()}
    config={'sensor':'synthetic response fixture','responses':responses,'samples':[{**sample,'lai':1,'prior':2},{**sample,'lai':3,'prior':1}]}
    calls=[]
    def model(**kwargs):
        calls.append(kwargs)
        return .1+WAVELENGTH*.0001+kwargs['lai']*.02
    rows=simulate(config,model)
    assert len(calls)==2 and calls[0]['prospect_version']=='D' and calls[0]['factor']=='SDR'
    np.testing.assert_allclose(rows,[[1,2,.168,.175,.186,.204],[3,1,.208,.215,.226,.244]],atol=1e-12)
    with pytest.raises(ValueError,match='two distinct'):
        simulate({**config,'samples':[config['samples'][0]]*2},model)
    bad={**responses,'blue':[[470,1],[480,1],[490,0]]}
    with pytest.raises(ValueError,match='zero'):simulate({**config,'responses':bad},model)


@pytest.mark.parametrize('kind',['joint_lai','joint_cab','joint_lai_sd','joint_cab_sd','joint_parameter_correlation','joint_effective_hypotheses','fusion_two_anchor','fusion_anchor_disagreement','cloud_calibrated_probability','shadow_calibrated_probability'])
def test_joint_research_reference(kind):
    if kind.startswith('joint_'):
        lib=np.array([[1,20,1,.2,.3,.4,.5],[1,60,2,.3,.4,.5,.6],[4,20,3,.4,.5,.6,.7],[4,60,1,.5,.6,.7,.8]])
        x=np.array([.34,.44,.54,.64]);a={r:constant(z) for r,z in zip(('blue','green','red','nir'),x)}
        p={r+'_sd':.15 for r in a};p.update(band_correlation=.3,max_chi2=100)
        c=.15**2*(.7*np.eye(4)+.3*np.ones((4,4)));d=lib[:,3:]-x
        weight=lib[:,2]*np.exp(-.5*np.einsum('ni,ij,nj->n',d,np.linalg.inv(c),d));weight/=weight.sum()
        mean=weight@lib[:,:2];center=lib[:,:2]-mean;cov=(center*weight[:,None]).T@center
        expected={'joint_lai':mean[0],'joint_cab':mean[1],'joint_lai_sd':np.sqrt(cov[0,0]),'joint_cab_sd':np.sqrt(cov[1,1]),'joint_parameter_correlation':cov[0,1]/np.sqrt(cov[0,0]*cov[1,1]),'joint_effective_hypotheses':1/(weight@weight)}[kind]
        r=run(kind,a,p,library=lib.tolist());np.testing.assert_allclose(grid(r),expected,atol=1e-12)
        assert sum(q[-1] for q in r['receipt']['metrics']['joint_posterior'])==pytest.approx(1)
    elif kind.startswith('fusion_'):
        fine=np.tile([[.2,.3],[.4,.5]],(3,3));after=np.tile([[.4,.5],[.6,.7]],(3,3));target=np.full(fine.shape,.45)
        a={'fine_before':fine,'coarse_before':np.full(fine.shape,.35),'fine_after':after,'coarse_after':np.full(fine.shape,.55),'coarse_target':target}
        r=run(kind,a);np.testing.assert_allclose(grid(r),fine+.1 if kind=='fusion_two_anchor' else 0,atol=1e-12)
        assert r['receipt']['metrics']['maximum_coarse_mean_error']<1e-12
    else:
        rng=np.random.default_rng(9);row,col=np.indices((30,30));label=1+row%3
        a={r:.15+.25*(label-1)+rng.normal(0,.015,label.shape) for r in ('blue','green','red','nir','swir1','swir2')};a['training']=label
        r=run(kind,a,{'block_m':40,'iterations':40});m=r['receipt']['metrics']
        assert m['oof_cells']==900 and sum(q[2] for q in m['reliability'])==900
        assert m['roc_auc']>.98 and m['binary_brier']<.05
        assert all(q[1]+q[2]+q[3]==900 for q in r['rows'])
        assert all(0<=q<=1 for q in grid(r).ravel())
        # Outer labels can affect scores, not the temperature learned for that fold.
        hold=(col//4+2*(row//4))%5==0
        a['training']=np.where(hold,1+label%3,label)
        changed=run(kind,a,{'block_m':40,'iterations':40})
        assert changed['rows'][0][4]==pytest.approx(r['rows'][0][4])


def test_joint_research_result_figures_render():
    from terrain.studio_routes import StudioInput
    from terrain.studio_render import render
    lib=[[1,20,1,.2,.3,.4,.5],[1,60,1,.3,.4,.5,.6],[4,20,1,.4,.5,.6,.7],[4,60,1,.5,.6,.7,.8]]
    a={r:constant(z) for r,z in zip(('blue','green','red','nir'),(.34,.44,.54,.64))}
    retrieval=run('joint_lai',a,{**{r+'_sd':.15 for r in a},'max_chi2':100},library=lib)
    fine=np.tile([[.2,.3],[.4,.5]],(3,3));coarse=np.full(fine.shape,.35)
    fusion=run('fusion_two_anchor',{'fine_before':fine,'coarse_before':coarse,'fine_after':fine+.1,'coarse_after':coarse+.1,'coarse_target':coarse+.05})
    row,col=np.indices((30,30));labels=1+row%3;rng=np.random.default_rng(9)
    a={r:.15+.25*(labels-1)+rng.normal(0,.015,labels.shape) for r in ('blue','green','red','nir','swir1','swir2')};a['training']=labels
    cloud=run('cloud_calibrated_probability',a,{'block_m':40,'iterations':40})
    recipes=set()
    for result in (retrieval,fusion,cloud):
        for figure in result['figures']:
            if figure['raster']:continue
            body=StudioInput(recipe=figure['recipe'],csv=figure['csv'],**figure['bindings'])
            png,meta,table=render(body);assert png.startswith(b'\x89PNG') and meta['used_count']>0
            svg,_,t2=render(body.model_copy(update={'format':'svg'}));assert svg.startswith(b'<?xml') and t2==table
            recipes.add(figure['recipe'])
    assert {'remote_reliability','remote_roc','remote_joint_posterior','remote_posterior_marginal','remote_anchor_quantiles','basic_table_heatmap'}<=recipes


def test_joint_ambiguity_and_nonzero_anchor_disagreement():
    # Equal spectra with different physical parameters remain unidentifiable.
    lib=[[1,20,1,.3,.4,.5,.6],[1,60,1,.3,.4,.5,.6],[5,20,1,.3,.4,.5,.6],[5,60,1,.3,.4,.5,.6]]
    a={r:constant(z) for r,z in zip(('blue','green','red','nir'),(.3,.4,.5,.6))}
    for kind,value in [('joint_lai',3),('joint_cab',40),('joint_lai_sd',2),('joint_cab_sd',20),('joint_effective_hypotheses',4),('joint_parameter_correlation',0)]:
        np.testing.assert_allclose(grid(run(kind,a,library=lib)),value,atol=1e-12)
    # Unequal subpixel structures but equal native block means: both anchors
    # must conserve the target coarse measurement without erasing disagreement.
    fine=np.tile([[.2,.3],[.4,.5]],(3,3));after=np.tile([[.5,.4],[.3,.2]],(3,3))
    c=np.full(fine.shape,.35);v={'fine_before':fine,'coarse_before':c,'fine_after':after,'coarse_after':c,'coarse_target':c}
    r=run('fusion_two_anchor',v,{'target_fraction':.25})
    np.testing.assert_allclose(grid(r),.75*fine+.25*after,atol=1e-12)
    disagreement=run('fusion_anchor_disagreement',v)
    np.testing.assert_allclose(grid(disagreement),abs(after-fine),atol=1e-12)
    assert disagreement['receipt']['metrics']['anchor_disagreement_rmse']==pytest.approx(np.sqrt(np.mean((after-fine)**2)))
    assert r['receipt']['metrics']['maximum_coarse_mean_error']<1e-12


def test_joint_prosail_adapter_retains_cab():
    from scripts.build_prosail_library import simulate,WAVELENGTH,BOUNDS
    responses={r:[[w-10,0],[w,1],[w+10,0]] for r,w in zip(('blue','green','red','nir'),(480,550,660,840))}
    sample={name:(lo+hi)/2 for name,(lo,hi) in BOUNDS.items()}
    config={'sensor':'synthetic response fixture','responses':responses,'samples':[{**sample,'lai':1,'cab':20,'prior':2},{**sample,'lai':3,'cab':60,'prior':1}]}
    rows=simulate(config,lambda **kw: .1+WAVELENGTH*.0001+kw['lai']*.02,joint=True)
    np.testing.assert_allclose(rows,[[1,20,2,.168,.175,.186,.204],[3,60,1,.208,.215,.226,.244]],atol=1e-12)


@pytest.mark.parametrize('kind',['sar_gamma_change_p','sar_gamma_ratio_low','sar_gamma_ratio_high'])
def test_gamma_change_reference(kind):
    # For one independent look in each epoch, F(2,2) has CDF r/(1+r).
    result=run(kind,{'before':constant(1.),'after':constant(3.)},
               {'enl_before':1,'enl_after':1,'confidence':.95})
    expected={'sar_gamma_change_p':.5,'sar_gamma_ratio_low':10*np.log10(3/39),
              'sar_gamma_ratio_high':10*np.log10(3*39)}[kind]
    np.testing.assert_allclose(grid(result),expected,atol=1e-12)

@pytest.mark.parametrize('kind',['align_overlap_mean','align_overlap_coverage'])
def test_exact_overlap_reference(kind):
    # A shifted 10 m target intersects two source cells by 5 m each.
    target=source(constant(1.),'target',aff=AFF)
    moving=source(np.tile([2.,4.,6.,8.],(3,1)),'source',aff=from_origin(500005,4500000,10,10))
    body=RemoteInput(operation=kind,sources=[target,moving],
        bindings={'target':{'source':0,'unit':'m'},'source':{'source':1,'unit':'m'}},
        parameters={'minimum_coverage':.5})
    result=checked(execute(body))
    expected=[2.,3.,5.,7.] if kind=='align_overlap_mean' else [.5,1.,1.,1.]
    np.testing.assert_allclose(grid(result),np.tile(expected,(3,1)))
    assert result['receipt']['metrics']['observed_support_area_m2']==1050


def test_disk_non_nested_overlap_matches_inline_across_windows(tmp_path):
    import rasterio
    from imagery.remote_support_disk import transfer
    from types import SimpleNamespace
    from imagery.remote_satellite import area_overlap
    from rasterio.transform import from_origin
    shape=(70,73);rng=np.random.default_rng(82)
    a=rng.uniform(2,7,shape);a[20:24,30:35]=np.nan
    b=np.ones((52,60));b[14,10]=np.nan
    ta=from_origin(500000,4500000,10,10)
    tb=from_origin(499997,4500003,12,13)
    paths=[tmp_path/'source.tif',tmp_path/'target.tif']
    paths[0].write_bytes(base64.b64decode(source(a,aff=ta,unit='m')['data']))
    paths[1].write_bytes(base64.b64decode(source(b,aff=tb,unit='m')['data']))
    for mode in ('mean','coverage'):
        expected,_=area_overlap(SimpleNamespace(values=a,transform=ta,crs=CRS,is_meter=True),
            SimpleNamespace(values=b,transform=tb,crs=CRS,is_meter=True),{'minimum_coverage':.5},'align_overlap_'+mode)
        for tile in (16,32):
            out=tmp_path/f'{mode}-{tile}.tif'
            receipt=transfer(*paths,out,mode=mode,minimum_coverage=.5,tile=tile)
            with rasterio.open(out) as ds:
                assert ds.transform==tb
                np.testing.assert_allclose(ds.read(1),expected,rtol=1e-10,atol=1e-10,equal_nan=True)
            assert receipt['output_sha256']==hashlib.sha256(out.read_bytes()).hexdigest()
            assert receipt['maximum_source_window_cells']<2000
    with pytest.raises(FigureInputError):
        transfer(*paths,tmp_path/'mean-16.tif')

def test_satellite_affine_control_checkpoints_and_robustness():
    from imagery.satellite_geometry import fit_affine
    from affine import Affine
    x,y=np.meshgrid(np.arange(5.)*100,np.arange(5.)*100)
    pixels=np.column_stack((x.ravel(),y.ravel()))
    matrix=np.array([[10.,.2],[-.1,-10.]])
    offset=np.array([500000.,4500000.])
    mapxy=lambda z:z@matrix.T+offset
    controls=np.column_stack((pixels,mapxy(pixels)))
    checkpoints=np.array([[50.,50.],[150.,220.],[330.,120.],[280.,330.]])
    b=np.column_stack((checkpoints,mapxy(checkpoints)))
    fit=fit_affine(controls,b,32617)
    assert fit['checkpoint_rmse_m']<1e-8
    t=Affine(*fit['affine'])
    np.testing.assert_allclose(t*(50.5,50.5),b[0,2:],atol=1e-8)
    controls[12,2:]+=[200.,-200.]
    robust=fit_affine(controls,b,32617,huber_m=.1)
    assert robust['checkpoint_rmse_m']<.01
    b2=b.copy();b2[:,2:]+=1000
    assert fit_affine(controls,b2,32617,huber_m=.1)['affine']==robust['affine']
    with pytest.raises(FigureInputError):
        fit_affine(controls,controls[:3],32617)
