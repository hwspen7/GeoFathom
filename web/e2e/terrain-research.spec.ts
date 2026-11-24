import {activateWorkspaceModule} from './workspace-ui';
import {test,expect} from './coverage-fixture';
import {execFileSync} from 'node:child_process';
import {resolve} from 'node:path';
const API='http://127.0.0.1:8000';
const tile=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/ZecAAAAASUVORK5CYII=','base64');

test('research scenarios, sensitivity, uncertainty, portable reports and restoration use real terrain calculations',async({page},testInfo)=>{
 test.setTimeout(180000);
 const fixture=JSON.parse(execFileSync('python',['-c',`
import json,tempfile
from pathlib import Path
import numpy as np,rasterio
from rasterio.transform import from_origin
from rasterio.warp import transform_geom
from shapely.geometry import box,mapping
from imagery.store import store_upload
with tempfile.TemporaryDirectory() as directory:
 p=Path(directory)/'research-dem.tif'
 with rasterio.open(p,'w',driver='GTiff',width=24,height=24,count=1,dtype='float32',
   crs='EPSG:32617',transform=from_origin(500000,4500000,10,10),nodata=-9999) as ds:
  ds.write(np.full((24,24),100,dtype='float32'),1)
  ds.update_tags(VERTICAL_DATUM='NAVD88')
 meta=store_upload(p,'Research reference DEM.tif')
 geometry=transform_geom('EPSG:32617','EPSG:4326',mapping(box(500020,4499780,500220,4499980)))
 print(json.dumps({'id':meta['id'],'geometry':geometry}))
`],{cwd:resolve('..'),env:{...process.env,GEOFATHOM_IMAGERY_DIR:resolve('..',process.env.GEOFATHOM_E2E_DATABASE_PATH||'data/e2e-geofathom.sqlite')+'.imagery'},encoding:'utf8'}));
 await page.route('**/tile.openstreetmap.org/**',r=>r.fulfill({contentType:'image/png',body:tile}));
 const project=await page.request.post(API+'/projects',{data:{name:'Research acceptance '+Date.now()}});
 expect(project.status()).toBe(201);const projectId=(await project.json()).id;
 expect((await page.request.post(API+'/projects/'+projectId+'/features',{data:{name:'Research study area',geometry:fixture.geometry,source:'Analytic fixture'}})).status()).toBe(201);
 await page.goto('/');await page.getByLabel('Active project').selectOption(projectId);
 await activateWorkspaceModule(page,'Terrain');
 await page.getByLabel('DEM elevation layer').selectOption(fixture.id);
 await page.getByLabel('Confirm DEM meter elevations').check();
 await page.locator('.workspace-objects > summary').click();
 await page.getByRole('button',{name:/Research study area/}).click();
 await page.getByLabel('Choose terrain analysis').selectOption('cutfill_map');
 await page.getByLabel('Reference elevation').fill('90');
 await page.getByRole('button',{name:'Run terrain operation'}).click();
 await expect(page.getByLabel('Choose terrain result')).not.toHaveValue('');
 await page.getByRole('button',{name:'Research analysis',exact:true}).click();
 const dialog=page.getByRole('dialog',{name:'Terrain research analysis'});
 await expect(dialog).toBeVisible();
 await dialog.getByLabel('Experiment title').fill('Earthwork design alternatives');
 await dialog.getByLabel('Scenario name').fill('Higher design');
 await dialog.getByLabel('Parameter',{exact:true}).selectOption('reference');
 await dialog.getByLabel('Parameter value').fill('95');
 await dialog.getByRole('button',{name:'Apply parameter'}).click();
 await dialog.getByRole('button',{name:'Add scenario'}).click();
 await dialog.getByLabel('Scenario name').fill('Balanced design');
 await dialog.getByLabel('Parameter value').fill('100');
 await dialog.getByRole('button',{name:'Apply parameter'}).click();
 async function run(){
  const response=page.waitForResponse(r=>r.url().endsWith('/terrain/research/analyze')&&r.request().method()==='POST');
  await dialog.getByRole('button',{name:'Run experiment',exact:true}).click();
  const reply=await response;expect(reply.status(),await reply.text()).toBe(200);
  await expect(dialog.getByRole('button',{name:'Results',exact:true})).toHaveAttribute('aria-pressed','true');
  return await reply.json();
 }
 const comparison=await run();
 expect(comparison.runs.map((r:{metrics:{cut_m3:number}})=>r.metrics.cut_m3)).toEqual([400000,200000,0]);
 await dialog.getByLabel('Result metric').selectOption('cut_m3');
 await expect(dialog.getByRole('table')).toContainText('200,000');
 await expect(dialog.getByRole('table')).toContainText('Higher design');
 await dialog.getByRole('button',{name:'Figures',exact:true}).click();
 await expect(dialog.getByAltText('Higher design map')).toBeVisible();
 await dialog.getByLabel('Figure',{exact:true}).selectOption('swipe');
 await expect(dialog.getByAltText('Baseline map',{exact:true})).toBeVisible();
 await dialog.getByLabel('Baseline reveal').fill('70');
 await expect(dialog.getByAltText('Baseline map',{exact:true})).toHaveCSS('clip-path','inset(0px 30% 0px 0px)');
 await dialog.getByRole('button',{name:'Report',exact:true}).click();
 const downloadEvent=page.waitForEvent('download');
 await dialog.getByRole('button',{name:'Download research package'}).click();
 const download=await downloadEvent;expect(download.suggestedFilename()).toBe('terrain-research.zip');
 const path=await download.path();expect(path).toBeTruthy();
 const checked=execFileSync('python',['-c',`
import zipfile,json,sys,io
from pypdf import PdfReader
with zipfile.ZipFile(sys.argv[1]) as archive:
 data=json.loads(archive.read('manifest.json'))
 assert len(data['runs'])==3
 assert len(data['artifacts'])==5
 text=' '.join(page.extract_text() for page in PdfReader(io.BytesIO(archive.read('report.pdf'))).pages)
 assert 'Earthwork design alternatives' in text
 assert 'Higher design' in text
 assert data['manifest']['source']['sha256']
 print('portable report verified')
`,path!],{encoding:'utf8'});
 expect(checked).toContain('verified');
 await dialog.getByRole('button',{name:'Experiment',exact:true}).click();
 await dialog.getByLabel('Analysis method').selectOption('sensitivity');
 await dialog.getByLabel('Sweep parameter').selectOption('reference');
 await dialog.getByLabel('Sweep values').fill('85, 90, 95');
 const sensitivity=await run();
 expect(sensitivity.sensitivity[0].derivatives.cut_m3).toBe(-40000);
 await dialog.getByRole('button',{name:'Figures',exact:true}).click();
 await dialog.getByLabel('Figure',{exact:true}).selectOption('response');
 await dialog.getByLabel('Result metric').selectOption('cut_m3');
 await expect(dialog.getByRole('img',{name:'Sensitivity response: cut_m3'})).toBeVisible();
 await page.screenshot({path:testInfo.outputPath('research-sensitivity.png')});
 await dialog.getByRole('button',{name:'Experiment',exact:true}).click();
 await dialog.getByLabel('Analysis method').selectOption('uncertainty');
 await dialog.getByLabel('Realizations').fill('20');
 await dialog.getByLabel('Spatial error model').selectOption('common_offset');
 const uncertainty=await run();
 expect(uncertainty.uncertainty.seed).toBe(42);
 await dialog.getByLabel('Result metric').selectOption('cut_m3');
 await expect(dialog).toContainText('95% model coverage interval');
 await dialog.getByRole('button',{name:'Close research analysis'}).click();
 await page.reload();await activateWorkspaceModule(page,'Terrain');
 await page.getByRole('button',{name:'Research analysis',exact:true}).click();
 await expect(dialog.getByRole('button',{name:'Report',exact:true})).toBeEnabled();
 await dialog.getByRole('button',{name:'Results',exact:true}).click();
 await expect(dialog).toContainText('95% model coverage interval');
 await dialog.getByRole('button',{name:'Figures',exact:true}).click();
 await dialog.getByLabel('Map output').selectOption({label:'Uncertainty std · std'});
 await dialog.getByRole('button',{name:'Show on map'}).click();
 await expect(dialog).toBeHidden();
 await expect(page.getByRole('button',{name:'Clear research map'})).toBeVisible();
 await page.getByRole('button',{name:'Clear research map'}).click();
 await expect(page.getByRole('button',{name:'Clear research map'})).toHaveCount(0);
});
