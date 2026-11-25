from threading import Event

import pytest

from terrain.advanced import run_terrain
from terrain.cancellation import TerrainCancelled
from terrain.engine import analyze_area, elevation_profile


@pytest.mark.parametrize("fn,args", [(run_terrain,("missing.tif",{},"contours")),
    (analyze_area,("missing.tif",{})),(elevation_profile,("missing.tif",{}))])
def test_cancelled_request_does_not_open_raster(fn,args):
    cancel=Event()
    cancel.set()
    with pytest.raises(TerrainCancelled):
        fn(*args,cancel=cancel)
