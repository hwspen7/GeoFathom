"""Pipeline corrections, area-support arithmetic and stable-reference quality gates."""
import base64
import copy

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from imagery.remote_cube import build_cube
from imagery.remote_harmonization import correct_band,registration_diagnostics
from imagery.remote_advanced_models import ross_li
from terrain.studio_data import FigureInputError
from test_remote_sensing import source


def test_cross_sensor_cube_applies_numeric_corrections_and_area_support(tmp_path):
    fine=.1+np.arange(64*96).reshape(64,96)%11*.02
    target=tmp_path/'target.tif';target.write_bytes(base64.b64decode(source(np.full((32,48),.3),aff=from_origin(500000,4500000,20,20))['data']))
    path=tmp_path/'fine.tif';path.write_bytes(base64.b64decode(source(fine)['data']))
    acqs=[{'id':'a','sensor':'reference','datetime':'2024-01-01T00:00:00Z','bands':{'red':{'path':str(path)}}},
        {'id':'b','sensor':'candidate','datetime':'2024-01-03T00:00:00Z','bands':{'red':{'path':str(path)}},
         'corrections':{'red':{'gain':1.1,'offset':.02,'reference_sensor':'reference','coefficient_source':'Independent coefficient fixture'}}}]
    config={'target_path':str(target),'acquisitions':acqs,'resampling':'area','tile':32,'harmonization':'Explicit fixture cross-sensor bandpass correction.'}
    cube=tmp_path/'cube.tif';receipt=build_cube(config,cube)
    expected=fine.reshape(32,2,48,2).mean(axis=(1,3))
    with rasterio.open(cube) as ds:
        np.testing.assert_allclose(ds.read(1),expected,atol=1e-12)
        np.testing.assert_allclose(ds.read(2),expected*1.1+.02,atol=1e-12)
    assert receipt['band_layout'][1]['correction']['gain']==1.1
    del acqs[1]['corrections']
    with pytest.raises(FigureInputError,match='numerical corrections'):build_cube(config,tmp_path/'unverified.tif')


def test_brdf_then_bandpass_matches_independent_kernel_ratio():
    b={'f_iso':.3,'f_vol':.04,'f_geo':.01,'solar_zenith':40,'view_zenith':10,'relative_azimuth':120,
        'target_solar_zenith':30,'target_view_zenith':0,'target_relative_azimuth':0}
    correction={'gain':1.02,'offset':-.01,'reference_sensor':'target','coefficient_source':'Known BRDF coefficient fixture','brdf':b}
    z=np.full((5,6),.4);out,evidence=correct_band(z,correction)
    vol,geo=ross_li(40,10,120);tvol,tgeo=ross_li(30,0,0)
    expected=.4*(.3+.04*tvol+.01*tgeo)/(.3+.04*vol+.01*geo)*1.02-.01
    np.testing.assert_allclose(out,expected,atol=1e-12)
    assert 'brdf_diagnostics' in evidence


def test_registration_gate_rejects_shifted_acquisitions():
    from scipy.ndimage import gaussian_filter,shift
    rng=np.random.default_rng(72);z=.3+gaussian_filter(rng.normal(0,.1,(64,64)),.7)
    mask=np.zeros(z.shape);mask[8:48,8:48]=1;mask[50:58,8:48]=2
    good=registration_diagnostics(z,z,mask)
    assert abs(good['subpixel_row_shift'])<1e-4 and good['original_heldout_rmse']==0
    moved=shift(z,(1,0),order=1,mode='constant',cval=np.nan)
    with pytest.raises(FigureInputError,match='realignment'):registration_diagnostics(z,moved,mask)


def test_cube_stable_mask_quality_check_runs_before_publication(tmp_path):
    from scipy.ndimage import gaussian_filter
    rng=np.random.default_rng(19);z=.3+gaussian_filter(rng.normal(0,.1,(64,64)),.7)
    band=tmp_path/'scene.tif';band.write_bytes(base64.b64decode(source(z)['data']))
    mask=np.zeros(z.shape);mask[8:48,8:48]=1;mask[50:58,8:48]=2
    controls=tmp_path/'controls.tif';controls.write_bytes(base64.b64decode(source(mask)['data']))
    acqs=[{'id':str(i),'sensor':'same','datetime':f'2024-01-0{i+1}T00:00:00Z','bands':{'red':{'path':str(band)}}} for i in range(2)]
    receipt=build_cube({'target_path':str(band),'acquisitions':acqs,'registration':{'mask_path':str(controls),'role':'red','window':[0,0,64,64]}},tmp_path/'cube.tif')
    assert receipt['registration'][0]['heldout_cells']>16
