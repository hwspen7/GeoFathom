/** Real-browser acceptance for previously unexercised Terrain analysis modes.
 *
 * Uses a small georeferenced DEM in the same file store as the API. No result,
 * error or response body is faked; mode validation and numerical outputs are
 * checked through the same controls used by an analyst.
 */
import {test,expect} from './coverage-fixture';
import {execFileSync} from 'node:child_process';
import {resolve} from 'node:path';

const API='http://127.0.0.1:8000';
const png=Buffer.from(
 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/ZecAAAAASUVORK5CYII=',
 'base64',
);

async function setup(page:import('@playwright/test').Page){
 const result=execFileSync('python',['-c',`
import json,tempfile
from pathlib import Path
import numpy as np,rasterio
from rasterio.transform import from_origin
from pyproj import Transformer
from imagery.store import store_upload
with tempfile.TemporaryDirectory() as directory:
 root=Path(directory)
 original=np.full((24,24),120,dtype=np.float32)
 yy,xx=np.indices((24,24))
 original+=xx*.5+yy*.2
 metadata=[]
 for index,delta in enumerate([0,-2]):
  p=root/('advanced-fixture-'+str(index)+'.tif')
  with rasterio.open(p,'w',driver='GTiff',width=24,height=24,count=1,
      dtype='float32',crs='EPSG:32617',
      transform=from_origin(500000,4500000,10,10),nodata=-9999) as ds:
   ds.write(original+delta,1)
   ds.update_tags(VERTICAL_DATUM='NAVD88')
  metadata.append(store_upload(p,'Advanced terrain reference '+str(index)+'.tif')['id'])
 convert=Transformer.from_crs('EPSG:32617','EPSG:4326',always_xy=True)
 ring=[convert.transform(x,y) for x,y in [
  (500020,4499980),(500220,4499980),(500220,4499780),
  (500020,4499780),(500020,4499980)]]
 a=convert.transform(500055,4499945)
 b=convert.transform(500165,4499855)
 print(json.dumps({'ids':metadata,'polygon':{'type':'Polygon','coordinates':[ring]},
                   'start':a,'end':b}))
`],{cwd:resolve('..'),env:{
  ...process.env,GEOFATHOM_IMAGERY_DIR:resolve('..',process.env.GEOFATHOM_E2E_DATABASE_PATH||'data/e2e-geofathom.sqlite')+'.imagery'
 },encoding:'utf8'});
 const fixture=JSON.parse(result) as {
  ids:string[];polygon:GeoJSON.Polygon;start:number[];end:number[]
 };
 const project=await page.request.post(API+'/projects',{
  data:{name:'Advanced Terrain workbench '+Date.now()+Math.random()},
 });
 expect(project.status(),await project.text()).toBe(201);
 const id=(await project.json()).id as string;
 const feature=await page.request.post(API+'/projects/'+id+'/features',{
  data:{name:'Advanced terrain study area',source:'Numerical fixture',geometry:fixture.polygon},
 });
 expect(feature.status(),await feature.text()).toBe(201);
 await page.route('**/tile.openstreetmap.org/**',route=>
  route.fulfill({contentType:'image/png',body:png}));
 await page.goto('/');
 await page.getByLabel('Active project').selectOption(id);
 await page.getByRole('navigation',{name:'Workspace tools'}).getByRole('button',{name:'Terrain',exact:true}).click();
 await page.getByLabel('DEM elevation layer').selectOption(fixture.ids[0]);
 await page.getByLabel('Confirm DEM meter elevations').check();
 await page.getByRole('button',{name:/Advanced terrain study area/}).click();
 await expect(page.getByLabel('DEM fetch area')).toHaveValue('selection');
 return fixture;
}

test('advanced surface families retain distinct real results and scientific exports',async({page})=>{
 test.setTimeout(180000);
 const fixture=await setup(page);
 const tools=page.getByLabel('Terrain tools');
 const run=page.getByRole('button',{name:'Run terrain operation'});
 const select=async(group:string,title:string)=>{
  await page.getByLabel('Terrain tool group').selectOption(group);
  await tools.getByRole('button',{name:title,exact:true}).click();
  await expect(run).toBeEnabled();
 };
 const execute=async(title:string)=>{
  const oldCount=await page.getByLabel('Analysis result layers').locator('.scratch-row').count();
  await run.click();
  await expect(page.getByLabel('Analysis result layers').locator('.scratch-row'))
   .toHaveCount(oldCount+1,{timeout:15000});
  await expect(page.getByLabel('Terrain results')).toBeVisible();
  // Match the literal title: names like "Ruggedness (TRI)" have regex
  // metacharacters, which must not change accessible-name matching.
  await expect(page.getByLabel('Analysis result layers')
    .getByRole('button',{name:new RegExp('^'+title.replace(/[.*+?^${}()|[\]\\]/g,'\\  await expect(page.getByLabel('Analysis result layers')
    .getByRole('button',{name:new RegExp('^'+title+' ·')})).toBeVisible();')+' ·')})).toBeVisible();
 };
 for(const name of [
  'Elevation map','Aspect map','Ruggedness (TRI)','Position (TPI)',
  'Curvature (Laplacian)','Plan curvature','Profile curvature',
 ]){
  await select('Surface',name);
  await execute(name);
  await expect(page.getByAltText('Derived terrain raster')).toBeVisible();
 }
 await select('Surface','DEM difference');
 await expect(run).toBeDisabled();
 await page.getByLabel('Reference comparison DEM').selectOption(fixture.ids[1]);
 await expect(run).toBeEnabled();
 await execute('DEM difference');
 await page.getByLabel('Terrain run provenance').locator('summary').click();
 await expect(page.getByLabel('Terrain run provenance')).toContainText('Reference DEM:');
 await expect(page.getByLabel('Terrain results')).toContainText('Mean elevation difference');
 for(const name of ['Flow direction','Flow accumulation']){
  await select('Hydrology',name);
  await execute(name);
 }
 await select('Hydrology','Drainage network');
 await page.getByLabel('Condition drainage DEM').uncheck();
 const threshold=page.getByLabel('Minimum upstream cells');
 await threshold.fill('0');
 await expect(run).toBeDisabled();
 await threshold.fill('2');
 await expect(run).toBeEnabled();
 await execute('Drainage network');
 await select('Engineering','Cut / fill map');
 await page.getByLabel('Reference elevation').fill('110');
 await execute('Cut / fill map');
 await select('Engineering','Site suitability');
 await page.getByLabel('Maximum slope (°)').fill('-1');
 await expect(run).toBeDisabled();
 await page.getByLabel('Maximum slope (°)').fill('45');
 await page.getByLabel('Min elevation (m)').fill('150');
 await page.getByLabel('Max elevation (m)').fill('100');
 await expect(run).toBeDisabled();
 await page.getByLabel('Min elevation (m)').fill('90');
 await page.getByLabel('Max elevation (m)').fill('200');
 await expect(run).toBeEnabled();
 await execute('Site suitability');
 await select('Engineering','Least-cost route');
 await expect(run).toBeDisabled();
 await page.getByLabel('Terrain origin longitude').fill(String(fixture.start[0]));
 await page.getByLabel('Terrain origin latitude').fill(String(fixture.start[1]));
 await page.getByLabel('Route end longitude').fill(String(fixture.end[0]));
 await page.getByLabel('Route end latitude').fill(String(fixture.end[1]));
 await expect(run).toBeEnabled();
 await execute('Least-cost route');
 await expect(page.getByLabel('Terrain results')).toContainText(/route length/i);
 const exportEvent=page.waitForEvent('download');
 await page.getByRole('button',{name:'Export',exact:true}).click();
 const exported=await exportEvent;
 expect(exported.suggestedFilename()).toMatch(/terrain-least_cost.*geojson/);
});

test('invalid terrain inputs are blocked and DEM resampling uses real configured options',async({page})=>{
 test.setTimeout(120000);
 const fixture=await setup(page);
 const tool=page.getByLabel('Terrain tools');
 const run=page.getByRole('button',{name:'Run terrain operation'});
 await tool.getByRole('button',{name:'Contours',exact:true}).click();
 await page.getByLabel('Contour interval').fill('-1');
 await expect(run).toBeDisabled();
 await page.getByLabel('Contour interval').fill('5');
 await expect(run).toBeEnabled();
 await page.getByLabel('Terrain tool group').selectOption('Surface');
 await tool.getByRole('button',{name:'Hillshade',exact:true}).click();
 const azimuth=page.getByLabel('Sun azimuth (°)');
 await azimuth.fill('361');
 await expect(run).toBeDisabled();
 await azimuth.fill('315');
 await expect(run).toBeEnabled();
 await page.getByLabel('Terrain tool group').selectOption('Quick');
 await tool.getByRole('button',{name:'Viewshed',exact:true}).click();
 await page.getByRole('button',{name:'Area center',exact:true}).click();
 const refraction=page.getByLabel('Terrain refraction coefficient');
 await refraction.fill('0.8');
 await expect(run).toBeDisabled();
 await refraction.fill('0.13');
 await expect(run).toBeEnabled();
 await page.getByLabel('Consider Earth curvature').uncheck();
 await expect(page.getByLabel('Terrain refraction coefficient')).toHaveCount(0);
 await expect(run).toBeEnabled();

 await page.locator('.terrain-dem-tools summary').click();
 await page.getByLabel('DEM processing operation').selectOption('mosaic');
 await expect(page.getByRole('button',{name:'Create processed DEM'})).toBeDisabled();
 await page.getByLabel('DEM mosaic second source').selectOption(fixture.ids[1]);
 await page.getByLabel('DEM processing operation').selectOption('resample');
 await page.getByLabel('DEM processing sampling').selectOption('average');
 const spacing=page.getByLabel('DEM processing resolution');
 await spacing.fill('50000');
 await page.getByRole('button',{name:'Create processed DEM'}).click();
 await expect(page.getByRole('alert')).toContainText('1–1,000 m');
 await spacing.fill('20');
 await page.getByRole('button',{name:'Create processed DEM'}).click();
 // The output raster is the durable outcome. Status messages can be
 // replaced by the parent selection notification during this transition.
 await expect(page.getByLabel('DEM elevation layer')).not.toHaveValue(fixture.ids[0],{timeout:25000});
 await expect(page.locator('.terrain-source .compact-notice[title]')).toContainText('12 × 12');
});


test('3D DEM remains inspectable using the CPU preview if WebGL2 is unavailable',async({page})=>{
 test.setTimeout(60000);
 // Disable WebGL only for the dedicated terrain surface canvas. MapLibre
 // retains its independent accelerated map context and normal click handling.
 await page.addInitScript(()=>{
  const original=HTMLCanvasElement.prototype.getContext;
  Object.defineProperty(HTMLCanvasElement.prototype,'getContext',{
   configurable:true,
   value:function(this:HTMLCanvasElement,kind:string,...options:unknown[]){
    if(kind==='webgl2'&&this.getAttribute('aria-label')==='Interactive 3D terrain preview')
      return null;
    return Reflect.apply(original,this,[kind,...options]);
   },
  });
 });
 await setup(page);
 await page.getByLabel('Terrain tools').getByRole('button',{name:'3D terrain',exact:true}).click();
 await page.getByRole('button',{name:'Run terrain operation'}).click();
 await expect(page.getByText('WebGL2 unavailable · CPU preview')).toBeVisible();
 const canvas=page.getByLabel('Interactive 3D terrain preview');
 await expect(canvas).toBeVisible();
 await expect(canvas).not.toHaveAttribute('data-renderer','webgl2');
 const exaggeration=page.getByLabel('Terrain vertical exaggeration');
 await expect(exaggeration).toHaveValue('1');
 await exaggeration.focus();
 await exaggeration.press('ArrowRight');
 await expect(exaggeration).toHaveValue('1.5');
 const bbox=(await canvas.boundingBox())!;
 await page.mouse.move(bbox.x+30,bbox.y+30);
 await page.mouse.down();
 await page.mouse.move(bbox.x+80,bbox.y+60,{steps:5});
 await page.mouse.up();
 await page.getByRole('button',{name:'Reset view'}).click();
 await expect(exaggeration).toHaveValue('1');
});
