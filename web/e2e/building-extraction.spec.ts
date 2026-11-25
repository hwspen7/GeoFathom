import {test,expect} from './coverage-fixture';
import {activateWorkspaceModule} from './workspace-ui';
import {execFileSync} from 'node:child_process';
import {resolve} from 'node:path';

test('building model inference is previewed, saved, plotted and downloaded through the workbench',async({page})=>{
  test.setTimeout(120000);
  // A real tiny ONNX graph verifies transport; it is not a trained building model.
  const fixture=JSON.parse(execFileSync('python',['-c',`
import json,tempfile,os
from pathlib import Path
import numpy as np,rasterio,onnx
from onnx import helper,numpy_helper,TensorProto
from rasterio.transform import from_origin
from imagery.store import store_upload
from vision.semantic import model_directory
root=model_directory();root.mkdir(parents=True,exist_ok=True)
w=np.zeros((1,3,1,1),np.float32);w[0,0,0,0]=20
g=helper.make_graph([helper.make_node('Conv',['x','w','b'],['y'])],'numerical-browser-fixture',
 [helper.make_tensor_value_info('x',TensorProto.FLOAT,[1,3,128,128])],
 [helper.make_tensor_value_info('y',TensorProto.FLOAT,[1,1,128,128])],
 [numpy_helper.from_array(w,'w'),numpy_helper.from_array(np.array([-10],np.float32),'b')])
m=helper.make_model(g,opset_imports=[helper.make_opsetid('',17)]);m.ir_version=9
onnx.save(m,root/'browser-buildings.onnx')
(root/'browser-buildings.json').write_text(json.dumps({'task':'building_extraction',
 'classes':['background','building'],'tile_size':128,'halo':16,
 'output_type':'binary_logits','output_channels':1,'output_channel':0}))
with tempfile.TemporaryDirectory(dir=root) as temp:
 p=Path(temp)/'building-browser.tif';a=np.full((3,128,160),20,np.uint8);a[0]=0
 a[0,20:100,30:140]=255;a[0,45:65,60:80]=0
 with rasterio.open(p,'w',driver='GTiff',width=160,height=128,count=3,dtype='uint8',
  crs='EPSG:32617',transform=from_origin(500000,4500000,1,1)) as d:d.write(a)
 asset=store_upload(p,'Building numerical browser fixture.tif')
 print(json.dumps(asset))
`],{cwd:resolve('..'),encoding:'utf8',env:{...process.env,
    GEOFATHOM_IMAGERY_DIR:resolve('..',process.env.GEOFATHOM_E2E_DATABASE_PATH||'data/e2e-geofathom.sqlite')+'.imagery',
    GEOFATHOM_VISION_MODELS_DIR:resolve('..',process.env.GEOFATHOM_E2E_DATABASE_PATH||'data/e2e-geofathom.sqlite')+'.models'}}));
  await page.route('**/tile.openstreetmap.org/**',r=>r.fulfill({contentType:'image/png',body:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/ZecAAAAASUVORK5CYII=','base64')}));
  const response=await page.request.post('http://127.0.0.1:8000/projects',{data:{name:'Building browser '+Date.now()}});
  expect(response.status()).toBe(201);
  const project=(await response.json()).id;
  await page.goto('/');
  await page.getByLabel('Active project').selectOption(project);
  await activateWorkspaceModule(page,'Raster / AI',true);
  await page.getByLabel('Select georeferenced imagery').selectOption(fixture.id);
  await page.getByText('GeoAI raster analysis & change detection').click();
  await page.getByLabel('GeoAI analysis operation').selectOption('building_extraction');
  await page.getByLabel('Local ONNX vision model').selectOption('browser-buildings');
  await page.getByLabel('Building instance separation').selectOption('connected');
  await page.getByLabel('GeoAI administration token').fill(process.env.GEOFATHOM_MODEL_ADMIN_TOKEN||'building-browser-admin');
  await page.getByRole('button',{name:'Run georeferenced analysis'}).click();
  await expect(page.getByLabel('Building extraction summary')).toContainText('1 building candidates',{timeout:45000});
  await page.getByRole('button',{name:'Preview on map',exact:true}).click();
  await expect(page.getByText('Previewing 1 candidate regions. Review before saving.')).toBeVisible();
  await page.getByRole('button',{name:'Save candidates',exact:true}).click();
  await expect(page.getByText('Saved 1 candidates to project for review. You can edit their boundaries.')).toBeVisible();
  const downloadEvent=page.waitForEvent('download');
  await page.getByRole('button',{name:'Download probability.tif',exact:true}).click();
  expect((await downloadEvent).suggestedFilename()).toBe('probability.tif');
  await page.getByRole('button',{name:'Open scientific figures',exact:true}).click();
  await expect(page.getByRole('dialog',{name:'Scientific figure studio'})).toBeVisible();
  await page.getByRole('button',{name:'Render figure',exact:true}).click();
  await expect(page.getByLabel('Studio figure preview').getByRole('img')).toBeVisible({timeout:30000});
  const features=await page.request.get('http://127.0.0.1:8000/projects/'+project+'/features');
  expect(features.ok()).toBeTruthy();
  await page.screenshot({path:'test-results/building-extraction-workbench.png',fullPage:true});
});
