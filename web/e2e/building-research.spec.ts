import {test,expect} from './coverage-fixture';
import {activateWorkspaceModule} from './workspace-ui';
import {execFileSync} from 'node:child_process';
import {resolve} from 'node:path';

test('frozen building study trains a real model, installs it and compares validation regions',async({page})=>{
  test.setTimeout(120000);
  const fixture=JSON.parse(execFileSync('python',['-c',`
import json,tempfile,base64
from pathlib import Path
import numpy as np,rasterio,torch
from rasterio.transform import from_origin
from vision.semantic import model_directory
from vision.building_training import make_network,export_model
from vision.building_dataset import freeze_dataset
from vision.building_research_store import package_dataset
from imagery.store import file_sha256
root=model_directory();root.mkdir(parents=True,exist_ok=True);torch.manual_seed(73);torch.set_num_threads(2)
meta={'task':'building_extraction','architecture':'compact_unet','classes':['background','building'],
 'bands':[1,2,3],'tile_size':128,'halo':16,'input_scale':255.,'mean':[0,0,0],'std':[1,1,1],
 'output_type':'binary_logits','output_channels':3,'output_channel':0,'boundary_channel':1,'distance_channel':2}
name='research-browser-base';stage=root/'research-browser-export'
export_model(make_network('compact_unet'),stage,meta)
for source,suffix in [('model.onnx','.onnx'),('model.json','.json'),('model.safetensors','.safetensors')]:
 (stage/source).replace(root/(name+suffix))
stage.rmdir()
with tempfile.TemporaryDirectory(dir=root) as temporary:
 d=Path(temporary);rows=[]
 for i in range(6):
  split=['train','validation','test'][i//2];a=np.full((3,64,64),10+i,np.uint8);a[0]=0;a[0,16:48,16:48]=255
  mask=np.zeros((64,64),np.uint8);mask[16:48,16:48]=1
  profile={'driver':'GTiff','width':64,'height':64,'crs':'EPSG:32617','transform':from_origin(500000+i*10000,4500000,1,1)}
  for file,data in [(f'image-{i}.tif',a),(f'labels-{i}.tif',mask[None])]:
   with rasterio.open(d/file,'w',**profile,count=data.shape[0],dtype='uint8') as out:out.write(data)
  rows.append({'id':f'fixture-{i}','region':split+'-city','group':f'group-{i}','split':split,
   'image':f'image-{i}.tif','labels':f'labels-{i}.tif',
   'image_sha256':file_sha256(d/f'image-{i}.tif'),'labels_sha256':file_sha256(d/f'labels-{i}.tif')})
 p=freeze_dataset(d,rows,provenance={'source':'numerical browser regression fixture'})
 package_dataset(p,d/'study.zip')
 print(json.dumps({'package':base64.b64encode((d/'study.zip').read_bytes()).decode(),'id':json.loads(p.read_text())['fingerprint']}))
`],{cwd:resolve('..'),encoding:'utf8',env:{...process.env,
    GEOFATHOM_VISION_MODELS_DIR:resolve('..',process.env.GEOFATHOM_E2E_DATABASE_PATH||'data/e2e-geofathom.sqlite')+'.models'}}));
  await page.route('**/tile.openstreetmap.org/**',r=>r.fulfill({contentType:'image/png',body:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/ZecAAAAASUVORK5CYII=','base64')}));
  const response=await page.request.post('http://127.0.0.1:8000/projects',{data:{name:'Building research browser '+Date.now()}});
  const project=(await response.json()).id;expect(response.status()).toBe(201);
  await page.goto('/');await page.getByLabel('Active project').selectOption(project);
  await activateWorkspaceModule(page,'Raster',true);
  await page.getByText('GeoAI raster analysis & change detection').click();
  await page.getByLabel('GeoAI analysis operation').selectOption('building_extraction');
  await page.getByLabel('GeoAI administration token').fill(process.env.GEOFATHOM_MODEL_ADMIN_TOKEN||'building-browser-admin');
  await page.getByRole('button',{name:'Model training and validation',exact:true}).click();
  const panel=page.getByRole('region',{name:'Building model research'});
  await panel.getByLabel('Building study ZIP').setInputFiles({name:'frozen-study.zip',mimeType:'application/zip',buffer:Buffer.from(fixture.package,'base64')});
  await expect(panel.getByLabel('Frozen building dataset')).toHaveValue(fixture.id);
  await panel.getByText('Train or fine-tune a model').click();
  await panel.getByLabel('Initial trainable building model').selectOption('research-browser-base');
  await panel.getByLabel('Building training epochs').fill('2');
  await panel.getByRole('button',{name:'Train building model',exact:true}).click();
  await expect(panel.getByLabel('Building training results')).toBeVisible({timeout:45000});
  await expect(panel.getByLabel('Building training results')).toContainText('Test data used for training: no');
  await panel.getByRole('button',{name:'Install trained building model',exact:true}).click();
  await expect(panel.getByText(/Installed local-building-/)).toBeVisible();
  await panel.getByText('Compare models and validate instances').click();
  const choices=panel.getByRole('group',{name:'Comparison models'});
  for(const checkbox of await choices.getByRole('checkbox').all())await checkbox.uncheck();
  await choices.getByLabel('research-browser-base',{exact:true}).check();
  await choices.getByLabel(/local-building-/).last().check();
  await panel.getByRole('button',{name:'Compare building models',exact:true}).click();
  await expect(panel.getByLabel('Building comparison results')).toBeVisible({timeout:45000});
  await expect(panel.getByLabel('Building comparison results')).toContainText('test regions remain unscored');
  await expect(panel.getByLabel('Building comparison results').getByRole('row')).toHaveCount(3);
  const download=page.waitForEvent('download');
  await panel.getByRole('button',{name:'Download building research bundle',exact:true}).click();
  expect((await download).suggestedFilename()).toBe('research.zip');
  await panel.getByRole('button',{name:'Open building research figures',exact:true}).click();
  await expect(page.getByRole('dialog',{name:'Scientific figure studio'})).toBeVisible();
  await page.getByRole('button',{name:'Render figure',exact:true}).click();
  await expect(page.getByLabel('Studio figure preview').getByRole('img')).toBeVisible({timeout:30000});
  await page.screenshot({path:'test-results/building-research-workbench.png',fullPage:true});
});
