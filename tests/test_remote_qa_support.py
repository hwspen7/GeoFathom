"""QA-excluded detector values cannot invalidate otherwise usable physical bands."""
import base64
from contextlib import ExitStack

import numpy as np
import pytest
import rasterio

from imagery.remote_routes import RemoteInput,PrepareInput,execute
from imagery.remote_preprocess import prepare
from imagery.remote_windowed import process
from imagery.remote_cube import build_cube
from imagery.remote_model import Inputs
from terrain.studio_data import FigureInputError
from test_remote_sensing import source,grid


@pytest.mark.parametrize('path',['inline','disk','prepare','cube','model_inputs'])
def test_qa_exclusion_precedes_physical_range_validation(tmp_path,path):
    nir=np.full((64,64),.6);nir[0,0]=100.;red=np.full_like(nir,.2);qa=np.full_like(nir,4);qa[0,0]=9
    sources=[source(z) for z in (nir,red,qa)];files=[]
    for i,s in enumerate(sources):
        file=tmp_path/(str(i)+'.tif');file.write_bytes(base64.b64decode(s['data']));files.append(str(file))
    def run(masked):
        quality=[{'source':2,'scheme':'sentinel_clear'}] if masked else []
        disk_qa=[{'path':files[2],'scheme':'sentinel_clear'}] if masked else []
        bands={'nir':{'path':files[0]},'red':{'path':files[1]}}
        output=tmp_path/(path+('-masked' if masked else '-raw')+'.tif')
        if path=='inline':
            body=RemoteInput(operation='ndvi',sources=sources,bindings={'nir':{'source':0},'red':{'source':1}},quality=quality)
            return grid(execute(body)),.5
        if path=='prepare':
            result=prepare(PrepareInput(sources=sources,bindings={'nir':{'source':0},'red':{'source':1}},
                quantities={'nir':'reflectance','red':'reflectance'},target={'source':0},quality=quality))
            output.write_bytes(base64.b64decode(result['bands'][0]['data']))
        elif path=='disk':process('ndvi',bands,output,quality=disk_qa,tile=64)
        elif path=='cube':
            acquisitions=[{'id':'a'+str(i),'datetime':f'2024-01-0{i+1}T00:00:00Z','sensor':'fixture',
                'bands':{'nir':bands['nir']},'quality':disk_qa} for i in range(2)]
            build_cube({'target_path':files[0],'acquisitions':acquisitions,'tile':32},output)
        else:
            with ExitStack() as stack:
                inputs=Inputs(stack,bands,disk_qa)
                return inputs.read(rasterio.windows.Window(0,0,64,64))[0],.6
        with rasterio.open(output) as ds:return ds.read(1),.5 if path=='disk' else .6
    values,expected=run(True);assert np.isnan(values[0,0])
    np.testing.assert_allclose(values[np.isfinite(values)],expected,atol=1e-12)
    # The same unsupported values must still fail when QA does not exclude them.
    with pytest.raises(FigureInputError,match='Reflectance outside'):run(False)
