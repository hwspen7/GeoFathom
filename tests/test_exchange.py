"""Data integrity across real GDAL codecs, transactional batches and packages."""
import csv
import io
import json
import time
import zipfile
from threading import Event

import numpy as np
import pyogrio
import pytest
import shapely
from fastapi.testclient import TestClient
from core.main import app
from storage.vectorio import read_vector,write_vector,VectorIOError,dumps,inspect_vector
from storage.exchange import commit_import,snapshot

client=TestClient(app)

@pytest.fixture(autouse=True)
def isolated(monkeypatch,tmp_path):
    monkeypatch.setenv('GEOFATHOM_DATABASE_PATH',str(tmp_path/'exchange.sqlite'))
    monkeypatch.setenv('GEOFATHOM_IMAGERY_DIR',str(tmp_path/'rasters'))
    monkeypatch.setenv('GEOFATHOM_MODEL_ADMIN_TOKEN','test-operator')

def project():
    r=client.post('/projects',json={'name':'Exchange'});assert r.status_code==201,r.text
    return r.json()['id']

def feature(i=0,**props):
    return {'type':'Feature','geometry':{'type':'Point','coordinates':[-83+i*.00001,40]},
            'properties':{'name':f'Site {i}',**props}}

def collection(*features):return {'type':'FeatureCollection','features':list(features)}

def root(pid):return '/projects/'+pid

def wait(pid,job):
    until=time.monotonic()+15
    while time.monotonic()<until:
        r=client.get(root(pid)+'/jobs/'+job['id']);assert r.status_code==200,r.text
        j=r.json()
        if j['status'] not in {'queued','running'}:return j
        time.sleep(.02)
    raise AssertionError(j)

def upload(pid,*files):
    r=client.post(root(pid)+'/vector/uploads',files=[('files',(name,blob)) for name,blob in files]);assert r.status_code==201,r.text
    return r.json()

def run_import(pid,stage,options=None):
    body={'upload_id':stage['upload_id'],'files':[{'id':f['id'],'options':(options or {}).get(f['name'],{})} for f in stage['files']]}
    r=client.post(root(pid)+'/vector/import/jobs',json=body);assert r.status_code==202,r.text
    return wait(pid,r.json())

@pytest.mark.parametrize('fmt,extension',[('geojson','geojson'),('gpkg','gpkg'),('shapefile','zip'),('kml','kml'),('gpx','gpx')])
def test_real_roundtrip_preserves_every_property_and_type(fmt,extension):
    props={'name':'设施 香港 — α','nullable':None,'bool':True,'large':2**60,'decimal':12.125,
           'nested':{'a':[1,False,None]},'empty':'','long_field_name_原始':'value'}
    output,_,_=write_vector(collection(feature(**props),feature(1,missing='different')),fmt)
    rows=read_vector('test.'+extension,output)['features']
    assert rows[0]['properties']==props
    assert rows[1]['properties']=={'name':'Site 1','missing':'different'}
    assert type(rows[0]['properties']['bool']) is bool
    assert type(rows[0]['properties']['large']) is int

@pytest.mark.parametrize('fmt,extension',[('gpkg','gpkg'),('shapefile','zip'),('kml','kml')])
def test_mixed_geometry_families_survive(fmt,extension):
    features=[feature(),{'type':'Feature','properties':{'name':'area'},'geometry':{'type':'Polygon','coordinates':[[[0,0],[1,0],[1,1],[0,0]]]}},
              {'type':'Feature','properties':{'name':'multi'},'geometry':{'type':'MultiPoint','coordinates':[[2,2],[3,3]]}}]
    binary,_,_=write_vector(collection(*features),fmt)
    result=read_vector('mixed.'+extension,binary)
    assert {f['geometry']['type'] for f in result['features']}=={'Point','MultiPoint','Polygon'}
    assert result['count']==3

def test_multilayer_gpkg_inspect_select_and_projected_output(tmp_path):
    features=[{**feature(i),'geofathom_layer':name} for i,name in enumerate(['Sensors','Airports'])]
    binary,_,_=write_vector(collection(*features),'gpkg','EPSG:3857')
    meta=inspect_vector('sites.gpkg',binary)
    assert len(meta['layers'])==2
    assert all(l['source_crs']=='EPSG:3857' for l in meta['layers'])
    assert all('_gf_json' not in {f['name'] for f in l['fields']} for l in meta['layers'])
    one=read_vector('sites.gpkg',binary,{'layers':[meta['layers'][0]['name']]})
    assert one['count']==1
    assert one['features'][0]['geometry']['coordinates']==pytest.approx([-83,40],abs=1e-8)
    path=tmp_path/'out.gpkg';path.write_bytes(binary)
    _,_,_,arrays=pyogrio.raw.read(path,layer=meta['layers'][0]['name'])
    assert len(arrays)>0

def test_csv_encoding_mapping_types_errors_and_formula_safety():
    blob='x;y;site;population;enabled\n-83;40;香港;123;true\nbad;40;invalid;4;false\n'.encode('utf-16')
    opts={'encoding':'utf-16','delimiter':';','longitude_field':'x','latitude_field':'y','field_map':{'site':'name'},
          'field_types':{'population':'integer','enabled':'boolean'}}
    with pytest.raises(VectorIOError,match='Validation failed'):read_vector('x.csv',blob,opts)
    result=read_vector('x.csv',blob,{**opts,'error_policy':'skip'})
    assert result['count']==1 and result['rejected']==1 and result['errors'][0]['row']==2
    assert result['features'][0]['properties']['population']==123
    assert result['features'][0]['properties']['enabled'] is True
    assert inspect_vector('x.csv',blob,opts)['layers'][0]['feature_count']==2
    out,_,_=write_vector(collection(feature(name=' =HYPERLINK("bad")',negative=-2)),'csv')
    rows=list(csv.DictReader(io.StringIO(out.decode('utf-8-sig'))))
    assert rows[0]['name'].startswith("'") and rows[0]['negative']=='-2'
    parsed=read_vector('x.csv',out,{'geometry_field':'geometry_wkt'})
    assert parsed['count']==1

@pytest.mark.parametrize('crs',['EPSG:4978','EPSG:4979','EPSG:999999','bad'])
def test_unsupported_crs_rejected(crs):
    with pytest.raises(ValueError):write_vector(collection(feature()),'gpkg',crs)

def test_field_selection_collision_and_precision_failure():
    out,_,_=write_vector(collection(feature(a=2,b='secret')),'geojson',fields=['a'])
    assert json.loads(out)['features'][0]['properties']=={'a':2}
    with pytest.raises(ValueError,match='fields'):write_vector(collection(feature()),'geojson',fields=['missing'])
    with pytest.raises(ValueError,match='overwrite'):read_vector('x.geojson',dumps(collection(feature(a=1,b=2))).encode(),{'field_map':{'a':'b'}})
    poly={'type':'Polygon','coordinates':[[[0,0],[.0001,0],[.0001,.0001],[0,0]]]}
    with pytest.raises(ValueError,match='precision'):write_vector(collection({'type':'Feature','geometry':poly,'properties':{}}),'geojson',precision=0)
    with pytest.raises(ValueError,match='WGS84'):write_vector(collection(feature()),'geojson','EPSG:3857')

def test_large_import_export_and_report_never_use_workspace_200_row_page():
    pid=project();data=dumps(collection(*(feature(i,category='station') for i in range(620)))).encode()
    r=client.post(root(pid)+'/vector/import',files={'file':('many.geojson',data)})
    assert r.status_code==201,r.text
    assert r.json()['created']==620
    workspace=client.get(root(pid)+'/workspace').json()
    assert workspace['total']==620 and len(workspace['features'])==200
    preflight=client.post(root(pid)+'/vector/export/preflight',json={'format':'gpkg'})
    assert preflight.status_code==200,preflight.text
    assert preflight.json()['count']==620
    csvout=client.post(root(pid)+'/vector/export',json={'format':'csv','include_measurements':True})
    assert csvout.status_code==200,csvout.text
    assert len(list(csv.DictReader(io.StringIO(csvout.content.decode('utf-8-sig')))))==620
    report=client.post(root(pid)+'/vector/export',json={'format':'report'})
    assert report.status_code==200,report.text
    assert len(report.json()['measurements'])==620
    assert 'method' in report.json()['measurements'][0]
    job=client.post(root(pid)+'/vector/export/jobs',json={'format':'gpkg'}).json()
    finished=wait(pid,job);assert finished['status']=='completed',finished
    download=client.get(root(pid)+'/vector/jobs/'+job['id']+'/download')
    assert download.status_code==200,download.text
    assert read_vector('result.gpkg',download.content)['count']==620

def test_batch_failure_is_atomic_and_skip_has_downloadable_report():
    pid=project();valid=dumps(collection(feature())).encode();bad=dumps(collection({'type':'Feature','properties':{},'geometry':None})).encode()
    staged=upload(pid,('ok.geojson',valid),('bad.geojson',bad))
    result=run_import(pid,staged);assert result['status']=='failed',result
    assert snapshot(pid)['features']==[]
    staged=upload(pid,('mixed.geojson',dumps(collection(feature(),{'type':'Feature','properties':{},'geometry':None})).encode()))
    result=run_import(pid,staged,{'mixed.geojson':{'error_policy':'skip'}})
    assert result['status']=='completed',result
    assert result['result']['created']==1 and result['result']['rejected']==1
    report=client.get(root(pid)+'/vector/jobs/'+result['id']+'/download')
    assert report.status_code==200,report.text
    assert report.json()['files'][0]['errors'][0]['row']==2
    assert len(snapshot(pid)['layers'])==2

def test_transaction_cancellation_rolls_back_all_rows_and_layers():
    pid=project();plan=read_vector('x.geojson',dumps(collection(*(feature(i) for i in range(600)))).encode());plan['name']='x.geojson'
    calls=0
    def cancel():
        nonlocal calls
        calls+=1
        if calls==2:raise RuntimeError('cancelled at row 256')
    with pytest.raises(RuntimeError):commit_import(pid,[plan],cancelled=cancel)
    assert snapshot(pid)['features']==[]
    assert len(snapshot(pid)['layers'])==1

def test_export_scope_project_ownership_extent_layer_and_fields():
    pid=project();other=project()
    for i in range(3):
        plan=read_vector('x.geojson',dumps(collection(feature(i,a=i))).encode());plan['name']=str(i)+'.geojson'
        commit_import(pid,[plan])
    data=snapshot(pid);layer=data['features'][1]['layer_id'];fid=data['features'][1]['id']
    for options in [{'layer_ids':[layer]},{'feature_ids':[fid]},{'viewport':[-82.999995,39.9,-82.999985,40.1]}]:
        response=client.post(root(pid)+'/vector/export',json={'format':'geojson','fields':['a'],**options})
        assert response.status_code==200,response.text
        assert len(response.json()['features'])==1
        assert response.json()['features'][0]['properties']=={'a':1}
    assert client.post(root(other)+'/vector/export',json={'format':'geojson','feature_ids':[fid]}).status_code==422
    staged=upload(pid,('x.geojson',dumps(collection(feature())).encode()))
    assert client.post(root(other)+'/vector/import/jobs',json={'upload_id':staged['upload_id']}).status_code==422
    assert client.get(root(pid)+'/vector/jobs/no-such-job/download').status_code==404

def test_project_package_roundtrip_styles_crs_history_and_rejects_tampering():
    pid=project();plan=read_vector('x.geojson',dumps(collection(feature(3,nested={'a':[True,None]}))).encode());plan['name']='x.geojson'
    commit_import(pid,[plan]);before=snapshot(pid);layer=before['features'][0]['layer_id'];fid=before['features'][0]['id']
    from storage.database import _connect
    from storage.crs import update_crs
    from storage.cartography import change_style
    update_crs(pid,'EPSG:3857',True)
    change_style(pid,layer,{'labels':{'enabled':True,'field':'name'}})
    # Record a real revision through the edit endpoint.
    r=client.patch(root(pid)+'/features/'+fid,json={'name':'Renamed','expected_revision':0})
    assert r.status_code==200,r.text
    before=snapshot(pid,include_history=True)
    response=client.post(root(pid)+'/package/export',json={'rasters':[]});assert response.status_code==200,response.text
    target=project();headers={'X-GeoFathom-Admin-Token':'test-operator','X-GeoFathom-Local-Import':'1'}
    restored=client.post(root(target)+'/package/import',files={'file':('project.zip',response.content)},headers=headers)
    assert restored.status_code==201,restored.text
    after=snapshot(target,include_history=True)
    assert len(after['features'])==1 and len(after['revisions'])==len(before['revisions'])
    assert after['features'][0]['properties']==before['features'][0]['properties']
    assert after['crs']['epsg']=='EPSG:3857' and after['crs']['grid_visible']==1
    assert [l['style'] for l in after['layers']]==[l['style'] for l in before['layers']]
    assert client.post(root(target)+'/package/import',files={'file':('project.zip',response.content)},headers=headers).status_code==422
    changed=io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(response.content)) as source,zipfile.ZipFile(changed,'w') as output:
        for name in source.namelist():output.writestr(name,source.read(name)+(b' ' if name=='project.json' else b''))
    empty=project()
    bad=client.post(root(empty)+'/package/import',files={'file':('project.zip',changed.getvalue())},headers=headers)
    assert bad.status_code==422,bad.text
    assert 'checksum' in bad.text
    assert snapshot(empty)['features']==[]

def test_real_running_import_can_be_cancelled_inside_sql_transaction(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from storage import exchange
    from jobs import queue
    entered=Event();release=Event();reached=0;original=exchange._record_feature
    def slow(*args,**kwargs):
        nonlocal reached
        result=original(*args,**kwargs);reached+=1
        if reached==256:entered.set();assert release.wait(5)
        return result
    monkeypatch.setattr(exchange,'_record_feature',slow)
    pid=project();stage=upload(pid,('x.geojson',dumps(collection(*(feature(i) for i in range(620)))).encode()))
    response=client.post(root(pid)+'/vector/import/jobs',json={'upload_id':stage['upload_id']});assert response.status_code==202,response.text
    job=response.json();assert entered.wait(5)
    try:
        with ThreadPoolExecutor(1) as pool:
            future=pool.submit(queue.cancel_job,pid,job['id'])
            until=time.monotonic()+3
            while not queue._cancel_marker(job['id']).exists() and time.monotonic()<until:time.sleep(.01)
            assert queue._cancel_marker(job['id']).exists()
            release.set();cancelled=future.result(5)
    finally:release.set()
    result=wait(pid,job);assert result['status']=='cancelled',result
    assert snapshot(pid)['features']==[]
    assert len(snapshot(pid)['layers'])==1

def test_import_receipt_and_features_commit_together_even_if_worker_exits_after_commit(monkeypatch):
    from jobs import queue
    original=queue._execute
    def exiting(kind,*args):
        result=original(kind,*args)
        if kind=='vector_import':raise RuntimeError('Simulated worker exit after durable commit')
        return result
    monkeypatch.setattr(queue,'_execute',exiting)
    pid=project();stage=upload(pid,('x.geojson',dumps(collection(feature())).encode()))
    result=run_import(pid,stage)
    assert result['status']=='completed',result
    assert result['result']['created']==1
    assert len(snapshot(pid)['features'])==1
    assert client.get(root(pid)+'/vector/jobs/'+result['id']+'/download').status_code==200

def test_package_preserves_original_properties_and_actual_source_geotiff(tmp_path):
    import rasterio
    from rasterio.transform import from_origin
    from imagery.store import store_upload,image_file
    from storage.project_package import build_package,restore_package
    from storage.database import add_features
    pid=project()
    add_features(pid,[{'geometry':feature()['geometry'],'name':'Metadata name','source':'Metadata source','properties':{'category':'site'}}])
    path=tmp_path/'height.tif'
    with rasterio.open(path,'w',driver='GTiff',width=4,height=4,count=1,dtype='float32',crs='EPSG:4326',transform=from_origin(-83,40,.001,.001)) as dataset:
        dataset.write(np.arange(16,dtype=np.float32).reshape(1,4,4))
    asset=store_upload(path,'真实DEM.tif');original=image_file(asset['id']).read_bytes()
    package=build_package(pid,[{'id':asset['id'],'kind':'dem'}]);target=project()
    result=restore_package(target,package)
    assert len(result['rasters'])==1
    restored=result['rasters'][0];assert restored['asset']['id']!=asset['id']
    assert restored['asset']['name']=='真实DEM.tif' and restored['kind']=='dem'
    assert image_file(restored['asset']['id']).read_bytes()==original
    from storage.database import _connect
    with _connect() as c:
        record=c.execute('SELECT * FROM features WHERE project_id=?',(target,)).fetchone()
    assert record['name']=='Metadata name' and record['source']=='Metadata source'
    assert json.loads(record['properties'])=={'category':'site'}

def test_scoped_tokens_can_export_but_cannot_import_or_restore_other_projects(monkeypatch):
    from core.access import create_user,grant
    pid=project();other=project();uid,token=create_user('Viewer');grant(uid,pid,'viewer')
    client.post(root(pid)+'/vector/import',files={'file':('x.geojson',dumps(collection(feature())).encode())})
    monkeypatch.setenv('GEOFATHOM_AUTH_MODE','required');monkeypatch.setenv('GEOFATHOM_API_TOKEN','operator-'+'a'*40);headers={'X-GeoFathom-API-Key':token}
    assert client.post(root(pid)+'/vector/export',json={'format':'geojson'},headers=headers).status_code==200
    assert client.post(root(pid)+'/vector/export/preflight',json={'format':'gpkg'},headers=headers).status_code==200
    assert client.post(root(other)+'/vector/export',json={'format':'geojson'},headers=headers).status_code==403
    assert client.post(root(pid)+'/vector/import',files={'file':('x.geojson',dumps(collection(feature())).encode())},headers=headers).status_code==403
    assert client.post(root(pid)+'/package/import',files={'file':('x.zip',b'PK')},headers=headers).status_code==403


def test_xml_source_layer_filter_and_three_dimensional_projection():
    features=[{**feature(i),'geofathom_layer':layer} for i,layer in enumerate(['one','two'])]
    for fmt in ['kml','gpx']:
        binary,_,_=write_vector(collection(*features),fmt)
        assert {l['name'] for l in inspect_vector('x.'+fmt,binary)['layers']}=={'one','two'}
        assert read_vector('x.'+fmt,binary,{'layers':['two']})['features'][0]['properties']['name']=='Site 1'
    f=feature();f['geometry']['coordinates'].append(123.25)
    binary,_,_=write_vector(collection(f),'gpkg','EPSG:3857')
    assert read_vector('x.gpkg',binary)['features'][0]['geometry']['coordinates']==pytest.approx([-83,40,123.25])

def test_gpkg_external_native_column_edits_take_precedence(tmp_path):
    binary,_,_=write_vector(collection(feature(nested={'a':[1,None]},nullable=None,height=12,huge=2**60+1),feature(1,height=None,huge=None)),'gpkg')
    path=tmp_path/'edited.gpkg';path.write_bytes(binary)
    import sqlite3
    layer=pyogrio.list_layers(path)[0][0]
    with sqlite3.connect(path) as c:
        # SQLite needs the spatial trigger functions even when only attributes
        # change. The test points/geometry are unchanged by this statement.
        for fn,value in [('ST_IsEmpty',0),('ST_MinX',-83),('ST_MaxX',-83),('ST_MinY',40),('ST_MaxY',40)]:c.create_function(fn,1,lambda _,v=value:v)
        c.execute('UPDATE "'+layer+'" SET height=99,nested=? WHERE fid=1',('{"a":[2]}',))
    result=read_vector('edited.gpkg',path.read_bytes())['features']
    assert result[0]['properties']['height']==99
    assert result[0]['properties']['nested']=={'a':[2]}
    assert result[0]['properties']['huge']==2**60+1
    assert result[1]['properties']['huge'] is None

@pytest.mark.parametrize('fmt,extension',[('geojson','geojson'),('gpkg','gpkg'),('shapefile','zip'),('kml','kml'),('gpx','gpx')])
def test_altitude_is_preserved_without_vertical_reprojection(fmt,extension):
    one=feature();one['geometry']['coordinates'].append(123.25)
    line={'type':'Feature','geometry':{'type':'LineString','coordinates':[[-83,40,5],[-82.9,40.1,10]]},'properties':{'name':'3D line'}}
    binary,_,_=write_vector(collection(one,line),fmt)
    features=read_vector('height.'+extension,binary)['features']
    assert next(f for f in features if f['name']=='Site 0')['geometry']['coordinates']==pytest.approx([-83,40,123.25])
    assert list(next(f for f in features if f['name']=='3D line')['geometry']['coordinates'][1])==[-82.9,40.1,10]

def test_export_preflight_rejects_geometry_collapsing_precision():
    pid=project()
    poly={'type':'Feature','properties':{},'geometry':{'type':'Polygon','coordinates':[[[0,0],[.0001,0],[.0001,.0001],[0,0]]]}}
    response=client.post(root(pid)+'/vector/export/preflight',json={'format':'geojson','precision':0,'collection':collection(poly)})
    assert response.status_code==422,response.text
    assert 'precision' in response.text
