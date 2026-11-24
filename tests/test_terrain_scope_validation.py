"""P0 scientific semantics: in-scope cells are not confused with invisible cells."""
import base64

import numpy as np
import pytest
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from terrain.advanced import _visibility, _visibility_scope, run_terrain


def test_single_observer_sector_has_exact_population_and_coverage():
    z=np.zeros((9,9),float)
    mask=np.ones_like(z,bool)
    transform=from_origin(0,90,10,10)
    scope=_visibility_scope(mask,(4,4),transform,25,0,90)
    assert scope[4,4] and scope[2,4]
    assert not scope[4,1] and not scope[6,4]
    visible,known=_visibility(z,mask,(4,4),transform,1.7,0.,
                              max_distance_m=25,view_azimuth=0,view_width=90)
    assert known[4,1] and not visible[4,1]  # Ray engine preserves known contract.
    assert (visible&scope).sum()==scope.sum()  # Flat in-scope surface is visible.
    assert int((mask&~scope).sum())==mask.size-int(scope.sum())


@pytest.fixture
def dem(tmp_path):
    import rasterio
    from pyproj import Transformer
    path=tmp_path/'flat.tif'
    tx=from_origin(500000,4500000,10,10)
    with rasterio.open(path,'w',driver='GTiff',height=20,width=20,count=1,
                       dtype='float32',transform=tx,crs='EPSG:32617',nodata=-9999) as ds:
        ds.write(np.full((20,20),100,dtype='float32'),1)
    geo=Transformer.from_crs('EPSG:32617','EPSG:4326',always_xy=True)
    coords=[geo.transform(x,y) for x,y in [(500010,4499990),(500190,4499990),
            (500190,4499810),(500010,4499810),(500010,4499990)]]
    return path,{"type":"Polygon","coordinates":[coords]}


def test_multi_observer_out_of_scope_has_nodata_and_exact_population(dem):
    path,polygon=dem
    from pyproj import Transformer
    to_geo=Transformer.from_crs('EPSG:32617','EPSG:4326',always_xy=True)
    observers=[to_geo.transform(500070,4499930),to_geo.transform(500120,4499880)]
    result=run_terrain(path,polygon,'viewshed_multi',observer_points=observers,
                       max_distance_m=25,view_azimuth=0,view_width=90)
    metrics=result['metrics']
    assert metrics['eligible_cells']>0
    assert metrics['out_of_scope_cells']>0
    assert metrics['eligible_cells']+metrics['out_of_scope_cells']==result['valid_cells']
    assert metrics['unknown_cells']==0
    assert metrics['known_eligible_cells']==metrics['eligible_cells']
    assert 0<=metrics['visibility_pct_of_known_eligible']<=100
    with MemoryFile(base64.b64decode(result['raster']['geotiff'])) as mem:
        with mem.open() as image:
            grid=image.read(1)
            assert np.isfinite(grid).sum()==metrics['eligible_cells']
            assert np.isnan(grid).sum()>=metrics['out_of_scope_cells']
