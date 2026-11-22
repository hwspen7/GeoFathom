import {test,expect} from './coverage-fixture';
import {execFileSync} from 'node:child_process';
import {resolve} from 'node:path';
import {readFileSync} from 'node:fs';
const API='http://127.0.0.1:8000';
const tile=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/ZecAAAAASUVORK5CYII=','base64');

test('real DEM is imported, analyzed, visualized and saved through workbench',async({page})=>{
 test.setTimeout(120000);
 const fixture=JSON.parse(execFileSync('python',['-c',`
import json,tempfile
from pathlib import Path
import numpy as np,rasterio
from rasterio.transform import from_origin
from pyproj import Transformer
from imagery.store import store_upload
with tempfile.TemporaryDirectory() as directory:
 p=Path(directory)/'synthetic-dem.tif'
 with rasterio.open(p,'w',driver='GTiff',width=24,height=24,count=1,dtype='float32',
     crs='EPSG:32617',transform=from_origin(500000,4500000,10,10),nodata=-9999) as ds:
  ds.write(np.tile(np.arange(24,dtype=np.float32)+100,(24,1)),1)
 meta=store_upload(p,'Synthetic DEM acceptance.tif')
 conv=Transformer.from_crs('EPSG:32617','EPSG:4326',always_xy=True)
 ring=[conv.transform(x,y) for x,y in [(500020,4499980),(500220,4499980),(500220,4499780),(500020,4499780),(500020,4499980)]]
 print(json.dumps({'id':meta['id'],'geometry':{'type':'Polygon','coordinates':[ring]}}))
`],{cwd:resolve('..'),env:{...process.env,GEOFATHOM_IMAGERY_DIR:resolve('..',process.env.GEOFATHOM_E2E_DATABASE_PATH||'data/e2e-geofathom.sqlite')+'.imagery'},encoding:'utf8'}));
 await page.route('**/tile.openstreetmap.org/**',r=>r.fulfill({contentType:'image/png',body:tile}));
 const project=await page.request.post(API+'/projects',{data:{name:'Terrain acceptance '+Date.now()}});
 expect(project.status(),await project.text()).toBe(201);const id=(await project.json()).id;
 const feature=await page.request.post(API+'/projects/'+id+'/features',{data:{name:'DEM study area',geometry:fixture.geometry,source:'Synthetic DEM'}});
 expect(feature.status(),await feature.text()).toBe(201);
 await page.goto('/');
 await page.getByLabel('Active project').selectOption(id);
 await page.getByRole('navigation',{name:'Workspace tools'}).getByRole('button',{name:'Terrain',exact:true}).click();
 await page.getByLabel('DEM elevation layer').selectOption(fixture.id);
 await page.getByLabel('Confirm DEM meter elevations').check();
 await page.getByRole('button',{name:/DEM study area/}).click();
 await expect(page.getByLabel('DEM fetch area')).toHaveValue('selection');
 await expect(page.getByLabel('DEM download target')).toContainText('Selected geometry');
 await expect(page.getByLabel('Interactive geospatial map')).toHaveAttribute('data-dem-target-visible','true');
 await page.getByLabel('DEM fetch area').selectOption('viewport');
 await expect(page.getByLabel('DEM download target')).toContainText('Current map');
 await page.getByRole('button',{name:'Use selected area',exact:true}).click();
 await expect(page.getByLabel('DEM fetch area')).toHaveValue('selection');
 await expect(page.getByLabel('DEM download target')).toContainText('Selected geometry');
 const terrainTab=page.getByRole('navigation',{name:'Workspace tools'}).getByRole('button',{name:'Terrain',exact:true});
 await expect(terrainTab).toHaveAttribute('aria-pressed','true');
 await terrainTab.click();
 await expect(terrainTab).toHaveAttribute('aria-pressed','false');
 await terrainTab.click();
 const tools=page.getByLabel('Terrain tools');
 await expect(tools.getByRole('button',{pressed:true})).toHaveCount(0);
 await expect(page.getByRole('button',{name:'Run terrain operation'})).toHaveCount(0);
 const map=page.getByLabel('Interactive geospatial map');
 await tools.getByRole('button',{name:'Slope / aspect',exact:true}).click();
 await page.getByRole('button',{name:'Run terrain operation'}).click();
 await expect(page.getByRole('img',{name:'Slope (degrees)'})).toBeVisible();
 await tools.getByRole('button',{name:'Elevation distribution',exact:true}).click();
 await page.getByRole('button',{name:'Run terrain operation'}).click();
 await expect(page.getByRole('img',{name:'Elevation distribution and cumulative area'})).toBeVisible();
 await expect(page.getByLabel('Elevation distribution bin')).toBeVisible();
 await page.getByRole('button',{name:'Expand',exact:true}).click();
 const dialogue=page.getByRole('dialog',{name:'Expanded terrain result'});
 await expect(dialogue).toBeVisible();
 const svgDownload=page.waitForEvent('download');await dialogue.getByRole('button',{name:'SVG',exact:true}).click();
 expect((await svgDownload).suggestedFilename()).toBe('terrain-chart.svg');
 for(const [format,header] of [['PNG','89504e470d0a1a0a'],['PDF','255044462d312e34']] as const){
   const event=page.waitForEvent('download');await dialogue.getByRole('button',{name:format,exact:true}).click();
   const file=await event;expect(file.suggestedFilename()).toBe('terrain-chart.'+format.toLowerCase());
   expect(readFileSync((await file.path())!).subarray(0,8).toString('hex')).toBe(header);
 }
 await dialogue.getByRole('button',{name:'Close expanded',exact:true}).click();
 await page.getByLabel('Terrain tool group').selectOption('Surface');
 await tools.getByRole('button',{name:'Slope map',exact:true}).click();
 await page.getByRole('button',{name:'Run terrain operation'}).click();
 await expect(page.getByAltText('Derived terrain raster')).toBeVisible();
 await expect(map).toHaveAttribute('data-terrain-raster-count','1');
 const countMetric=page.locator('.terrain-metrics > div').filter({hasText:'Calculated raster cells'}).first();
 await expect(countMetric.locator('strong')).not.toBeEmpty();
 await expect(countMetric.locator('strong')).not.toContainText('°');
 await expect(page.getByLabel('Slope edge cells explanation')).toContainText('boundary cells excluded');
 const opacity=page.getByLabel('Terrain raster opacity');
 await expect(opacity).toHaveValue('50');
 await expect(page.getByLabel('Terrain raster resampling')).toHaveValue('linear');
 await expect(map).toHaveAttribute('data-terrain-raster-resampling','linear');
 await page.getByLabel('Terrain raster resampling').selectOption('nearest');
 await expect(map).toHaveAttribute('data-terrain-raster-resampling','nearest');
 await opacity.fill('25');
 await expect(map).toHaveAttribute('data-terrain-raster-opacity','0.25');
 const download=page.waitForEvent('download');await page.getByRole('button',{name:'GeoTIFF',exact:true}).click();
 expect((await download).suggestedFilename()).toBe('slope_map.tif');
 // Two related raster analyses remain independently addressable.
 await tools.getByRole('button',{name:'Hillshade',exact:true}).click();
 await page.getByRole('button',{name:'Run terrain operation'}).click();
 await expect(map).toHaveAttribute('data-terrain-raster-count','1');
 await expect(page.getByLabel('Terrain raster resampling')).toHaveValue('linear');
 const previousSlope=page.getByRole('checkbox',{name:/Show Slope map /}).first();
 await previousSlope.check();
 await expect(map).toHaveAttribute('data-terrain-raster-count','2');
 await previousSlope.uncheck();
 await expect(map).toHaveAttribute('data-terrain-raster-count','1');
 await page.getByLabel('Terrain tool group').selectOption('Quick');
 await tools.getByRole('button',{name:'Contours',exact:true}).click();
 await page.getByLabel('Contour interval').fill('5');
 await page.getByRole('button',{name:'Run terrain operation'}).click();
 await expect(page.getByRole('button',{name:'Save terrain features'})).toBeEnabled();
 await expect.poll(async()=>Number(await map.getAttribute('data-terrain-feature-count'))).toBeGreaterThan(0);
 await page.getByRole('button',{name:'Save terrain features'}).click();
 await expect(page.getByText(/Saved .* terrain features/)).toBeVisible();
 await tools.getByRole('button',{name:'Cut / fill',exact:true}).click();
 await page.getByLabel('Reference elevation',{exact:true}).fill('110');
 await page.getByRole('button',{name:'Run terrain operation'}).click();
 await expect(page.getByLabel('Terrain results').getByText('Cut',{exact:true}).first()).toBeVisible();
 await expect(page.getByRole('img',{name:'Earthwork volume (m³)'})).toBeVisible();
 await tools.getByRole('button',{name:'3D terrain',exact:true}).click();
 await page.getByRole('button',{name:'Run terrain operation'}).click();
 const meshCanvas=page.getByLabel('Interactive 3D terrain preview');
 await expect(meshCanvas).toBeVisible();
 // Require the WebGL2 path under the CI SwiftShader renderer, not the CPU fallback.
 await expect(meshCanvas).toHaveAttribute('data-renderer','webgl2');
 await expect.poll(async()=>meshCanvas.evaluate(node=>{
   const canvas=node as HTMLCanvasElement,gl=canvas.getContext('webgl2');if(!gl)return false;
   const data=new Uint8Array(canvas.width*canvas.height*4);gl.readPixels(0,0,canvas.width,canvas.height,gl.RGBA,gl.UNSIGNED_BYTE,data);
   for(let i=0;i<data.length;i+=4)if(data[i+3]>0&&data[i+1]>data[i]+10&&data[i+1]>data[i+2]+10)return true;
   return false;
 })).toBe(true);
 const objEvent=page.waitForEvent('download');await page.getByRole('button',{name:'OBJ',exact:true}).click();
 const obj=await objEvent;expect(readFileSync((await obj.path())!,'utf8')).toMatch(/\nf \d+ \d+ \d+/);
 await tools.getByRole('button',{name:'Viewshed',exact:true}).click();
 await page.getByRole('button',{name:'Pick observer',exact:true}).click();
 const bounds=(await map.boundingBox())!;
 await page.mouse.click(bounds.x+bounds.width/2,bounds.y+bounds.height/2);
 await expect(page.getByLabel('Terrain sample location')).toHaveCount(1);
 await page.getByRole('button',{name:'Run terrain operation'}).click();
 await expect(page.getByRole('img',{name:'Visibility (cells)'})).toBeVisible();
 await tools.getByRole('button',{name:'Watershed (D8)',exact:true}).click();
 await page.getByRole('button',{name:'Area center',exact:true}).click();
 await page.getByRole('button',{name:'Run terrain operation'}).click();
 await expect(page.getByRole('img',{name:'Catchment (cells)'})).toBeVisible();
 const ring=fixture.geometry.coordinates[0];
 const path={type:'LineString',coordinates:[ring[0],ring[2]]};
 const line=await page.request.post(API+'/projects/'+id+'/features',{data:{name:'DEM profile line',geometry:path,source:'Synthetic DEM'}});
 expect(line.status(),await line.text()).toBe(201);
 // Reload the workspace instead of relying on a stale list from a different query.
 await page.reload();
 await page.getByRole('navigation',{name:'Workspace tools'}).getByRole('button',{name:'Terrain',exact:true}).click();
 await page.getByLabel('DEM elevation layer').selectOption(fixture.id);
 await page.getByLabel('Confirm DEM meter elevations').check();
 await page.getByRole('button',{name:/DEM profile line/}).click();
 await page.getByLabel('Terrain tools').getByRole('button',{name:'Elevation profile',exact:true}).click();
 await page.getByRole('button',{name:'Run terrain operation'}).click();
 const chart=page.getByRole('img',{name:'Interactive elevation profile'});
 await expect(chart).toBeVisible();await chart.hover();
 await expect(page.getByLabel('Terrain sample location')).toHaveCount(1);
 await expect(page.getByLabel('Terrain run provenance')).toBeVisible();
 // Reverse interaction: actual map-projected profile point → chart cursor.
 await chart.locator('..').hover({position:{x:1,y:1}});
 const pixels=JSON.parse((await map.getAttribute('data-profile-station-pixels'))||'[]') as number[][];
 expect(pixels.length).toBeGreaterThan(10);
 const mapBox=(await map.boundingBox())!;
 const candidate=pixels.find(p=>p[0]>20&&p[0]<mapBox.width-20&&p[1]>20&&p[1]<mapBox.height-20);
 expect(candidate).toBeTruthy();
 await page.mouse.move(mapBox.x+candidate![0],mapBox.y+candidate![1]);
 await expect.poll(async()=>{
   const idx=await page.locator('.terrain-profile-chart[data-profile-selected-index]').getAttribute('data-profile-selected-index');
   return idx!==null&&idx!=='none';
 },{timeout:15000}).toBe(true);
 await expect(page.getByLabel('Profile sample position')).toBeVisible();
 await page.getByLabel('Terrain tool group').selectOption('Engineering');
 await page.getByLabel('Terrain tools').getByRole('button',{name:'Cross sections',exact:true}).click();
 await page.getByRole('button',{name:'Run terrain operation'}).click();
 await expect(page.getByRole('button',{name:'All sections CSV'})).toBeVisible();
 await page.getByLabel('DEM elevation layer').selectOption('');
 await expect(page.getByLabel('DEM elevation layer')).toHaveValue('');
 await expect(page.getByRole('button',{name:'Run terrain operation'})).toBeDisabled();
 // Full scientific outputs, not only run receipts, survive a hard reload.
 // Restored layers are hidden until explicitly enabled on the map.
 await page.reload();
 await page.getByRole('navigation',{name:'Workspace tools'}).getByRole('button',{name:'Terrain',exact:true}).click();
 const restored=page.getByLabel('Analysis result layers');
 await expect(restored.getByRole('button',{name:/Cross sections ·/})).toBeVisible();
 await expect(restored.getByRole('button',{name:/Slope map ·/})).toBeVisible();
 await expect(map).toHaveAttribute('data-terrain-raster-count','0');
 await restored.getByRole('button',{name:/Cross sections ·/}).click();
 await expect(page.getByRole('button',{name:'All sections CSV'})).toBeVisible();
 await restored.getByRole('button',{name:/Slope map ·/}).click();
 await expect(page.getByAltText('Derived terrain raster')).toBeVisible();
 const cachedRaster=page.waitForEvent('download');
 await page.getByRole('button',{name:'GeoTIFF',exact:true}).click();
 expect((await cachedRaster).suggestedFilename()).toBe('slope_map.tif');
 // Removing a result removes it from IndexedDB as well as React memory.
 await restored.getByRole('button',{name:'Remove result Slope map'}).click();
 await expect(restored.getByRole('button',{name:/Slope map ·/})).toHaveCount(0);
 await page.reload();
 await page.getByRole('navigation',{name:'Workspace tools'}).getByRole('button',{name:'Terrain',exact:true}).click();
 await expect(page.getByLabel('Analysis result layers').getByRole('button',{name:/Slope map ·/})).toHaveCount(0);
 // Results from one project must never be visible in a different project.
 const another=await page.request.post(API+'/projects',{data:{name:'Independent terrain project '+Date.now()}});
 expect(another.status()).toBe(201);
 const anotherId=(await another.json()).id;
 // An external client created this project after initial startup. Focusing
 // the selector must discover it without reloading the current workspace.
 const selector=page.getByLabel('Active project');
 await selector.focus();
 await expect(selector.locator('option[value="'+anotherId+'"]')).toHaveCount(1);
 await selector.selectOption(anotherId);
 await expect(selector).toHaveValue(anotherId);
 await expect(page.getByLabel('Analysis result layers')).toHaveCount(0);
});
