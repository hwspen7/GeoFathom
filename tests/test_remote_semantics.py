"""Mixed physical features and acquisition semantics survive research workflows."""
import base64
import json

import numpy as np
import pytest
import rasterio

from imagery.remote_cube import build_cube
from imagery.remote_model import train,predict
from imagery.remote_routes import RemoteInput,execute
from imagery.remote_windowed import process
from terrain.studio_data import FigureInputError
from test_remote_cube import cube_fixture
from test_remote_sensing import source,grid


def test_cube_time_semantics_survive_inline_and_disk_analysis(tmp_path):
    config=cube_fixture(tmp_path);cube=tmp_path/'cube.tif';receipt=build_cube(config,cube)
    bands=[b for b in receipt['band_layout'] if b['role']=='red']
    bindings={f'date{i+1}':{'path':str(cube),'band':b['band'],'unit':'reflectance'} for i,b in enumerate(bands)}
    output=tmp_path/'days.tif';result=process('series_slope',bindings,output,times=receipt['times'],tile=64)
    assert result['time_context']['time_origin']==receipt['time_origin'] and result['unit']=='reflectance/day'
    with rasterio.open(output) as ds:
        assert ds.tags()['TIME_UNIT']=='day' and ds.tags()['TIME_ORIGIN']==receipt['time_origin']
        np.testing.assert_allclose(ds.read(1),.01,atol=1e-12)
    context={'time_unit':'hour','time_origin':receipt['time_origin'],'acquisition_datetimes':receipt['utc_datetimes']}
    hours=[t*24 for t in receipt['times']]
    with pytest.raises(FigureInputError,match='Numeric times disagree'):
        process('series_slope',bindings,tmp_path/'wrong.tif',times=hours)
    hourly=process('series_slope',bindings,tmp_path/'hours.tif',times=hours,time_context=context)
    assert hourly['unit']=='reflectance/hour'
    body=RemoteInput(operation='series_slope',sources=[{'name':'cube','data':base64.b64encode(cube.read_bytes()).decode()}],
        bindings={r:{'source':0,'band':b['band'],'unit':'reflectance'} for r,b in zip(bindings,bands)},times=hours,time_context=context)
    inline=execute(body);np.testing.assert_allclose(grid(inline),.01/24,atol=1e-12)
    assert inline['receipt']['time_context']['time_unit']=='hour' and inline['raster']['unit']=='reflectance/hour'


def test_mixed_physical_feature_training_and_unit_conflict(tmp_path):
    row,col=np.indices((48,80));classes=1+row%3;rng=np.random.default_rng(71)
    features={}
    for role,quantity,unit,values in (
        ('optical','reflectance','reflectance',np.full(row.shape,.3)),
        ('terrain_slope','slope','degree',classes*20.),
        ('lidar_height','distance_m','m',classes*100.),
        ('sar_power','power','linear_power',classes*.03)):
        path=tmp_path/(role+'.tif');path.write_bytes(base64.b64decode(source(values+rng.normal(0,.0001,row.shape),unit=unit)['data']))
        features[role]={'path':str(path),'quantity':quantity,'unit':unit}
    labels=tmp_path/'labels.tif';labels.write_bytes(base64.b64decode(source(np.where(col%4==0,classes,0))['data']))
    config={'features':features,'labels':{'path':str(labels)},'parameters':{'trees':16,'block_m':40}}
    model=tmp_path/'model.json';result=train(config,model)
    assert result['validation']['overall_accuracy']==1
    artifact=json.loads(model.read_text());assert artifact['features'][1]['training_source']['unit']=='degree'
    prediction=tmp_path/'prediction.tif';predict({'model_path':str(model),'features':features},prediction)
    with rasterio.open(prediction) as ds:np.testing.assert_array_equal(ds.read(1),classes)
    features['lidar_height']['unit']='ft'
    with pytest.raises(FigureInputError,match='unit conflicts'):
        predict({'model_path':str(model),'features':features},tmp_path/'wrong.tif')
