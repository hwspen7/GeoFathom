import {activateWorkspaceModule,expectWorkspaceModule} from './workspace-ui';
import {test,expect} from './coverage-fixture';
import type {Locator,Page} from '@playwright/test';
import {execFileSync} from 'node:child_process';
import {resolve} from 'node:path';
import {readFileSync} from 'node:fs';
const API='http://127.0.0.1:8000';
const tile=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/ZecAAAAASUVORK5CYII=','base64');

// Navigate actual fixed form pages rather than forcing off-screen controls.
async function revealTerrainControl(page:Page,control:Locator){
 const panel=page.locator('#tools-terrain .terrain-control-page:not([hidden])');
 const previous=panel.getByRole('button',{name:'Previous terrain page'});
 const next=panel.getByRole('button',{name:'Next terrain page'});
 if(await control.isVisible())return;
 while(await previous.isVisible()&&await previous.isEnabled())await previous.click();
 for(let i=0;i<30;i++){
  if(await control.isVisible())return;
  if(!await next.isVisible()||!await next.isEnabled())break;
  await next.click();
 }
 await expect(control).toBeVisible();
}

test('real DEM is imported, analyzed, visualized and saved through workbench',async({page})=>{
 // This scenario exercises many real API operations and software-rendered WebGL.
 test.setTimeout(process.env.CI ? 240000 : 120000);
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
 await activateWorkspaceModule(page,'Terrain');
 await page.getByRole('button',{name:'Get DEM',exact:true}).click();
 await page.getByLabel('DEM elevation layer').selectOption(fixture.id);
 await revealTerrainControl(page,page.getByLabel('Confirm DEM meter elevations'));
 await page.getByLabel('Confirm DEM meter elevations').check();
 await page.getByRole('button',{name:/DEM study area/}).click();
 await expect(page.getByLabel('DEM fetch area')).toHaveValue('selection');
 await expect(page.getByLabel('DEM download target')).toContainText('Selected geometry');
 await expect(page.getByLabel('Interactive geospatial map')).toHaveAttribute('data-dem-target-visible','true');
 await revealTerrainControl(page,page.getByLabel('DEM fetch area'));
 await page.getByLabel('DEM fetch area').selectOption('viewport');
 await expect(page.getByLabel('DEM download target')).toContainText('Current map');
 await revealTerrainControl(page,page.getByRole('button',{name:'Use selected area',exact:true}));
 await page.getByRole('button',{name:'Use selected area',exact:true}).click();
 await expect(page.getByLabel('DEM fetch area')).toHaveValue('selection');
 await expect(page.getByLabel('DEM download target')).toContainText('Selected geometry');
 await expectWorkspaceModule(page,'Terrain');
 await expect(page.getByRole('complementary',{name:'Operations'})).toBeVisible();
 await expect(page.getByLabel('Results monitor')).toBeHidden();
 await expect(page.getByLabel('Project and layers',{exact:true})).toBeHidden();
 // Before the first result, the map uses the entire remaining workspace.
 const left=await page.getByRole('complementary',{name:'Operations'}).boundingBox();
 const center=await page.getByLabel('Interactive geospatial map').boundingBox();
 expect(left&&center).toBeTruthy();
 expect(left!.x+left!.width).toBeLessThan(center!.x+10);
 expect(center!.height).toBeGreaterThan(400);
 expect(Math.round(left!.width)).toBe(318);
 await expect(page.getByLabel('Terrain analysis inputs')).toBeVisible();
 await expect(page.getByRole('button',{name:'Get DEM',exact:true})).toHaveAttribute('aria-pressed','true');
 await expect(page.getByLabel('Terrain analysis inputs')).not.toContainText('01');
 await expect(page.getByLabel('Terrain analysis inputs')).not.toContainText('02');
 const scrollModes=await page.locator('.gis-operations>.sidebar-scroll,.gis-results-monitor>.sidebar-scroll')
   .evaluateAll(elements=>elements.map(element=>getComputedStyle(element).overflowY));
 expect(scrollModes[0]).toBe('clip');
 expect(['hidden','clip']).toContain(scrollModes[1]);
 await expect(page.getByRole('button',{name:/full operations view/})).toHaveCount(0);
 await expect(page.getByRole('button',{name:/full results view/})).toHaveCount(0);
 await expect(page.getByRole('separator',{name:/Resize (operations|results)/})).toHaveCount(0);
 const visual=async()=>{
  // New records intentionally select Overview after the cache commit. Wait
  // for calculation completion before choosing a figure on that record.
  await expect(page.getByRole('button',{name:'Calculating…',exact:true})).toHaveCount(0);
  await page.getByRole('tab',{name:'Figures',exact:true}).click();
 };
 const outputs=()=>page.getByRole('tab',{name:'Data',exact:true}).click();
 const details=()=>page.getByRole('tab',{name:'Data',exact:true}).click();
 // The global drawing toolbar persists when Terrain is active.
 await expect(page.getByLabel('Survey toolbar').getByRole('button',{name:'Polygon',exact:true})).toBeVisible();
 // Repeated module activation must preserve the fixed Tools panel and active analysis.
 await activateWorkspaceModule(page,'Terrain');
 await expect(page.getByRole('complementary',{name:'Operations'})).toBeVisible();
 await page.getByRole('button',{name:'Browse terrain tools',exact:true}).click();
 const tools=page.getByLabel('Terrain tools',{exact:true});
 await expect(tools.getByRole('button',{pressed:true})).toHaveCount(0);
 await expect(page.getByRole('button',{name:'Run terrain operation'})).toHaveCount(0);
 const map=page.getByLabel('Interactive geospatial map');
 await page.getByRole('button',{name:'Browse terrain tools',exact:true}).click();
 await revealTerrainControl(page,tools.getByRole('button',{name:'Slope / aspect',exact:true}));
 await tools.getByRole('button',{name:'Slope / aspect',exact:true}).click();
 await page.getByRole('button',{name:'Run terrain operation'}).click();
 await expect(page.getByRole('tablist',{name:'Terrain result views'}).getByRole('tab')).toHaveCount(3);
 await expect(page.getByRole('tab',{name:'Overview',exact:true})).toHaveAttribute('aria-selected','true');
 await page.getByRole('tab',{name:'Overview',exact:true}).focus();
 await page.keyboard.press('ArrowRight');
 await expect(page.getByRole('tab',{name:'Figures',exact:true})).toHaveAttribute('aria-selected','true');
 await expect(page.getByRole('tab',{name:'Figures',exact:true})).toBeFocused();
 await visual();
 await expect(page.getByRole('img',{name:'Slope (degrees)'})).toBeVisible();
 await expect(page.getByLabel('Results monitor').getByLabel('Terrain results')).toBeVisible();
 const right=await page.getByLabel('Results monitor').boundingBox();
 const resultMap=await map.boundingBox();
 expect(Math.round(right!.width)).toBe(364);
 expect(resultMap!.x+resultMap!.width).toBeLessThan(right!.x+10);
 expect(resultMap!.width).toBeLessThan(center!.width);
 await page.getByRole('button',{name:'Browse terrain tools',exact:true}).click();
 await revealTerrainControl(page,tools.getByRole('button',{name:'Elevation distribution',exact:true}));
 await tools.getByRole('button',{name:'Elevation distribution',exact:true}).click();
 await page.getByRole('button',{name:'Run terrain operation'}).click();
 await visual();
 await expect(page.getByRole('img',{name:'Elevation distribution and cumulative area'})).toBeVisible();
 await expect(page.getByLabel('Elevation distribution bin')).toBeVisible();
 await page.getByRole('button',{name:'Hypsometry',exact:true}).click();
 await expect(page.getByRole('img',{name:'Hypsometric curve'})).toBeVisible();
 await page.getByRole('button',{name:'Analysis',exact:true}).click();
 await page.getByRole('button',{name:'Review',exact:true}).click();
 const dialogue=page.getByRole('dialog',{name:'Terrain result review'});
 await expect(dialogue).toBeVisible();
 await dialogue.getByRole('navigation',{name:'Terrain review views'}).getByRole('button',{name:'Overview',exact:true}).click();
 await expect(dialogue.getByRole('button',{name:'Overview',exact:true})).toHaveAttribute('aria-pressed','true');
 await dialogue.getByRole('navigation',{name:'Terrain review views'}).getByRole('button',{name:'Figures',exact:true}).click();
 const svgDownload=page.waitForEvent('download');await dialogue.getByRole('button',{name:'SVG',exact:true}).click();
 expect((await svgDownload).suggestedFilename()).toBe('terrain-chart.svg');
 for(const [format,header] of [['PNG','89504e470d0a1a0a'],['PDF','255044462d312e34']] as const){
   const event=page.waitForEvent('download');await dialogue.getByRole('button',{name:format,exact:true}).click();
   const file=await event;expect(file.suggestedFilename()).toBe('terrain-chart.'+format.toLowerCase());
   expect(readFileSync((await file.path())!).subarray(0,8).toString('hex')).toBe(header);
 }
 await dialogue.getByRole('button',{name:'Close review',exact:true}).click();
 await page.getByRole('button',{name:'Browse terrain tools',exact:true}).click();
 await page.getByLabel('Terrain tool group').selectOption('Surface');
 await page.getByRole('button',{name:'Browse terrain tools',exact:true}).click();
 await revealTerrainControl(page,tools.getByRole('button',{name:'Slope map',exact:true}));
 await tools.getByRole('button',{name:'Slope map',exact:true}).click();
 // Both choices must be real server inputs and survive in the analysis receipt.
 await revealTerrainControl(page,page.getByLabel('Terrain gradient algorithm'));
 await page.getByLabel('Terrain gradient algorithm').selectOption('zevenbergen_thorne');
 await revealTerrainControl(page,page.getByLabel('Slope classification preset'));
 await page.getByLabel('Slope classification preset').selectOption('detailed');
 await page.getByRole('button',{name:'Run terrain operation'}).click();
 await visual();
 await expect(page.getByAltText('Derived terrain raster')).toBeVisible();
 await page.getByLabel('Terrain chart measure').selectOption('percent');
 await expect(page.getByRole('img',{name:'Terrain class distribution (valid %)'})).toBeVisible();
 await page.getByLabel('Terrain chart measure').selectOption('area');
 await expect(page.getByRole('img',{name:'Terrain class distribution (projected km²)'})).toBeVisible();
 await page.getByLabel('Terrain chart measure').selectOption('cells');
 await page.getByRole('button',{name:'Composition',exact:true}).click();
 await expect(page.getByRole('img',{name:'Terrain class composition'})).toBeVisible();
 await page.getByRole('button',{name:'Cumulative',exact:true}).click();
 await expect(page.getByRole('img',{name:'Class share and cumulative area'})).toBeVisible();
 await page.getByRole('button',{name:'Analysis',exact:true}).click();
 await expect(map).toHaveAttribute('data-terrain-raster-count','1');
 await details();
 await page.getByLabel('Additional terrain metrics').locator('summary').click();
 const countMetric=page.locator('.terrain-metrics > div').filter({hasText:'Calculated raster cells'}).first();
 await expect(countMetric.locator('strong')).not.toBeEmpty();
 await expect(countMetric.locator('strong')).not.toContainText('°');
 await expect(page.getByLabel('Slope edge cells explanation')).toContainText('boundary cells excluded');
 await page.getByLabel('Terrain class statistics').locator('summary').click();
 await expect(page.getByRole('table',{name:'Terrain class area statistics'}).locator('tbody tr')).toHaveCount(8);
 await expect(page.getByLabel('Terrain algorithm parameters')).toContainText('gradient method');
 await expect(page.getByLabel('Terrain algorithm parameters')).toContainText('zevenbergen_thorne');
 await expect(page.getByLabel('Terrain algorithm parameters')).toContainText('detailed');
 await visual();
 const opacity=page.getByLabel('Terrain raster opacity');
 await expect(opacity).toHaveValue('50');
 await expect(page.getByLabel('Terrain raster resampling')).toHaveValue('linear');
 await expect(map).toHaveAttribute('data-terrain-raster-resampling','linear');
 await page.getByLabel('Terrain raster resampling').selectOption('nearest');
 await expect(map).toHaveAttribute('data-terrain-raster-resampling','nearest');
 await opacity.fill('25');
 await expect(map).toHaveAttribute('data-terrain-raster-opacity','0.25');
 await outputs();
 const download=page.waitForEvent('download');await page.getByRole('button',{name:'GeoTIFF',exact:true}).click();
 expect((await download).suggestedFilename()).toBe('slope_map.tif');
 const csvFile=page.waitForEvent('download');
 await page.getByRole('button',{name:'Export terrain class CSV'}).click();
 const exported=await csvFile;
 expect(exported.suggestedFilename()).toBe('slope_map-classes.csv');
 const csv=readFileSync((await exported.path())!,'utf8');
 expect(csv).toContain('class,cells,percent_valid,area_m2,cumulative_percent');
 expect(csv.split('\n').length).toBeGreaterThan(8);
 // Two related raster analyses remain independently addressable.
 await page.getByRole('button',{name:'Browse terrain tools',exact:true}).click();
 await revealTerrainControl(page,tools.getByRole('button',{name:'Hillshade',exact:true}));
 await tools.getByRole('button',{name:'Hillshade',exact:true}).click();
 await page.getByRole('button',{name:'Run terrain operation'}).click();
 await expect(map).toHaveAttribute('data-terrain-raster-count','1');
 await visual();
 await expect(page.getByLabel('Terrain raster resampling')).toHaveValue('linear');
 await outputs();
 await page.getByLabel('Terrain output layers').locator('summary').click();
 const previousSlope=page.getByRole('checkbox',{name:/Show Slope map /}).first();
 await previousSlope.check();
 await expect(map).toHaveAttribute('data-terrain-raster-count','2');
 await previousSlope.uncheck();
 await expect(map).toHaveAttribute('data-terrain-raster-count','1');
 // Hiding a map layer does not remove the native product from other workbenches.
 await activateWorkspaceModule(page,'Temporal');
 await page.getByRole('button',{name:'Open Spatiotemporal Analysis'}).click();
 const temporal=page.getByRole('dialog',{name:'Spatiotemporal science workbench'});
 await expect(temporal.getByLabel('Current scientific raster').locator('option').filter({hasText:'Slope map'})).toHaveCount(1);
 await temporal.getByRole('button',{name:'Close',exact:true}).click();
 await activateWorkspaceModule(page,'Terrain');
 await expect(map).toHaveAttribute('data-terrain-raster-count','1');
 await page.getByRole('button',{name:'Browse terrain tools',exact:true}).click();
 await page.getByLabel('Terrain tool group').selectOption('Quick');
 await page.getByRole('button',{name:'Browse terrain tools',exact:true}).click();
 await revealTerrainControl(page,tools.getByRole('button',{name:'Contours',exact:true}));
 await tools.getByRole('button',{name:'Contours',exact:true}).click();
 await revealTerrainControl(page,page.getByLabel('Contour interval'));
 await page.getByLabel('Contour interval').fill('5');
 await page.getByRole('button',{name:'Run terrain operation'}).click();
 await expect(page.getByRole('button',{name:'Save terrain features'})).toBeEnabled();
 await expect.poll(async()=>Number(await map.getAttribute('data-terrain-feature-count'))).toBeGreaterThan(0);
 await page.getByRole('button',{name:'Save terrain features'}).click();
 await expect(page.getByText(/Saved .* terrain features/)).toBeVisible();
 // Saved contours are still useful after the browser-local analysis cache is
 // gone; their project features retain source identity and run settings.
 const stored=await page.request.get(API+'/projects/'+id+'/workspace');
 expect(stored.status()).toBe(200);
 const persisted=(await stored.json()).features as Array<{
   properties:Record<string,unknown>
 }>;
 const contour=persisted.find(f=>f.properties.operation==='contours');
 expect(contour).toBeTruthy();
 expect(contour!.properties.terrain_run_id).toMatch(/^[a-f0-9-]{20,}$/);
 expect(contour!.properties.source_sha256).toMatch(/^[a-f0-9]{64}$/);
 expect(contour!.properties.research_parameters).toMatchObject({
   contour_interval_m:5
 });
 await page.getByRole('button',{name:'Browse terrain tools',exact:true}).click();
 await revealTerrainControl(page,tools.getByRole('button',{name:'Cut / fill',exact:true}));
 await tools.getByRole('button',{name:'Cut / fill',exact:true}).click();
 await revealTerrainControl(page,page.getByLabel('Reference elevation',{exact:true}));
 await page.getByLabel('Reference elevation',{exact:true}).fill('110');
 await page.getByRole('button',{name:'Run terrain operation'}).click();
 await expect(page.getByLabel('Terrain results').getByText('Cut',{exact:true}).first()).toBeVisible();
 await visual();
 await expect(page.getByRole('img',{name:'Earthwork volume (m³)'})).toBeVisible();
 await page.getByRole('button',{name:'Browse terrain tools',exact:true}).click();
 await revealTerrainControl(page,tools.getByRole('button',{name:'3D terrain',exact:true}));
 await tools.getByRole('button',{name:'3D terrain',exact:true}).click();
 await revealTerrainControl(page,page.getByLabel('3D mesh sampling budget'));
 await page.getByLabel('3D mesh sampling budget').selectOption('128');
 await page.getByRole('button',{name:'Run terrain operation'}).click();
 await visual();
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
 const objEvent=page.waitForEvent('download');await page.getByRole('button',{name:'OBJ (preview)',exact:true}).click();
 const obj=await objEvent;expect(readFileSync((await obj.path())!,'utf8')).toMatch(/\nf \d+ \d+ \d+/);
 await page.getByRole('button',{name:'Browse terrain tools',exact:true}).click();
 await revealTerrainControl(page,tools.getByRole('button',{name:'Viewshed',exact:true}));
 await tools.getByRole('button',{name:'Viewshed',exact:true}).click();
 await page.getByText('Viewing sector and range').click();
 await revealTerrainControl(page,page.getByLabel('Viewshed maximum distance'));
 await page.getByLabel('Viewshed maximum distance').fill('2000');
 await revealTerrainControl(page,page.getByLabel('Viewshed facing azimuth'));
 await page.getByLabel('Viewshed facing azimuth').fill('45');
 await revealTerrainControl(page,page.getByLabel('Viewshed horizontal field of view'));
 await page.getByLabel('Viewshed horizontal field of view').fill('180');
 await revealTerrainControl(page,page.getByRole('button',{name:'Pick observer',exact:true}));
 await page.getByRole('button',{name:'Pick observer',exact:true}).click();
 const bounds=(await map.boundingBox())!;
 await page.mouse.click(bounds.x+bounds.width/2,bounds.y+bounds.height/2);
 await expect(page.getByLabel('Terrain sample location')).toHaveCount(1);
 await page.getByRole('button',{name:'Run terrain operation'}).click();
 await visual();
 await expect(page.getByRole('img',{name:'Visibility (cells)'})).toBeVisible();
 await details();
 await expect(page.getByLabel('Scientific validation status')).toContainText('not performed');
 await visual();
 await page.getByRole('button',{name:'Browse terrain tools',exact:true}).click();
 await revealTerrainControl(page,tools.getByRole('button',{name:'Watershed (D8)',exact:true}));
 await tools.getByRole('button',{name:'Watershed (D8)',exact:true}).click();
 await page.getByRole('button',{name:'Area center',exact:true}).click();
 await page.getByRole('button',{name:'Run terrain operation'}).click();
 await visual();
 await expect(page.getByRole('img',{name:'Catchment (cells)'})).toBeVisible();
 const ring=fixture.geometry.coordinates[0];
 const path={type:'LineString',coordinates:[ring[0],ring[2]]};
 const line=await page.request.post(API+'/projects/'+id+'/features',{data:{name:'DEM profile line',geometry:path,source:'Synthetic DEM'}});
 expect(line.status(),await line.text()).toBe(201);
 // Reload the workspace instead of relying on a stale list from a different query.
 await page.reload();
 await activateWorkspaceModule(page,'Terrain');
 await page.getByRole('button',{name:'Get DEM',exact:true}).click();
 await page.getByLabel('DEM elevation layer').selectOption(fixture.id);
 await revealTerrainControl(page,page.getByLabel('Confirm DEM meter elevations'));
 await page.getByLabel('Confirm DEM meter elevations').check();
 await page.getByLabel('Filter project features').fill('DEM profile line');
 await page.getByRole('button',{name:/DEM profile line/}).click();
 await page.getByRole('button',{name:'Browse terrain tools',exact:true}).click();
 await page.getByLabel('Terrain tools',{exact:true}).getByRole('button',{name:'Elevation profile',exact:true}).click();
 await page.getByRole('button',{name:'Run terrain operation'}).click();
 await visual();
 const chart=page.getByRole('img',{name:'Interactive elevation profile'});
 await expect(chart).toBeVisible();await chart.hover();
 await expect(page.getByLabel('Terrain sample location',{exact:true})).toHaveCount(1);
 await page.getByRole('button',{name:'Gradient',exact:true}).click();
 await expect(page.getByRole('img',{name:'Longitudinal profile grade'})).toBeVisible();
 await page.getByRole('button',{name:'Analysis',exact:true}).click();
 // Switching figures leaves the SVG and clears its transient hover marker.
 // Re-enter the restored profile to exercise chart-to-map linking again.
 await expect(chart).toBeVisible();
 await chart.hover();
 await expect(page.getByLabel('Terrain sample location')).toHaveCount(1);
 await details();
 await expect(page.getByLabel('Terrain run provenance')).toBeVisible();
 await visual();
 // Reverse interaction: actual map-projected profile point → chart cursor.
 await chart.locator('..').hover({position:{x:1,y:1}});
 // Return from the inspector to the map before using absolute mouse
 // coordinates. Playwright can scroll an ancestor while hovering charts.
 await map.scrollIntoViewIfNeeded();
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
 await page.getByRole('button',{name:'Browse terrain tools',exact:true}).click();
 await page.getByLabel('Terrain tool group').selectOption('Engineering');
 await page.getByRole('button',{name:'Browse terrain tools',exact:true}).click();
 await page.getByLabel('Terrain tools',{exact:true}).getByRole('button',{name:'Cross sections',exact:true}).click();
 await page.getByRole('button',{name:'Run terrain operation'}).click();
 await expect(page.getByLabel('Choose terrain result').locator('option:checked')).toContainText('Cross sections');
 await visual();
 await expect(page.getByRole('button',{name:'All sections CSV'})).toBeVisible();
 await page.getByRole('button',{name:'Get DEM',exact:true}).click();
 await page.getByLabel('DEM elevation layer').selectOption('');
 await expect(page.getByLabel('DEM elevation layer')).toHaveValue('');
 await expect(page.getByRole('button',{name:'Run terrain operation'})).toBeDisabled();
 // Full scientific outputs, not only run receipts, survive a hard reload.
 // Restored layers are hidden until explicitly enabled on the map.
 await page.reload();
 await activateWorkspaceModule(page,'Terrain');
 const resultSelect=page.getByLabel('Choose terrain result');
 await expect(resultSelect.locator('option').filter({hasText:'Cross sections'})).toHaveCount(1);
 await expect(resultSelect.locator('option').filter({hasText:'Slope map'})).toHaveCount(1);
 await expect(map).toHaveAttribute('data-terrain-raster-count','0');
 const crossId=await resultSelect.locator('option').filter({hasText:'Cross sections'}).getAttribute('value');
 await resultSelect.selectOption(crossId!);
 await visual();
 await expect(page.getByRole('button',{name:'All sections CSV'})).toBeVisible();
 const slopeId=await resultSelect.locator('option').filter({hasText:'Slope map'}).getAttribute('value');
 await resultSelect.selectOption(slopeId!);
 await visual();
 await expect(page.getByAltText('Derived terrain raster')).toBeVisible();
 await outputs();
 const cachedRaster=page.waitForEvent('download');
 await page.getByRole('button',{name:'GeoTIFF',exact:true}).click();
 expect((await cachedRaster).suggestedFilename()).toBe('slope_map.tif');
 const layerManager=page.getByLabel('Terrain output layers',{exact:true}).locator('.terrain-layer-manager');
 if(await layerManager.getAttribute('open')===null)await layerManager.locator('summary').click();
 const removeSlope=layerManager.getByRole('button',{name:'Remove result Slope map',exact:true});
 // Restored outputs are paged. Reach the actual row through the visible
 // page controls before removing it; never treat the selector as the layer list.
 const pages=layerManager.getByLabel('Terrain layer pages',{exact:true});
 while(await removeSlope.count()===0&&await pages.getByRole('button',{name:'Next',exact:true}).isEnabled())
  await pages.getByRole('button',{name:'Next',exact:true}).click();
 // Removing a result removes it from IndexedDB as well as React memory.
 await removeSlope.click();
 await expect(resultSelect.locator('option').filter({hasText:'Slope map'})).toHaveCount(0);
 await page.reload();
 await activateWorkspaceModule(page,'Terrain');
 await outputs();
 await expect(page.getByLabel('Choose terrain result').locator('option').filter({hasText:'Slope map'})).toHaveCount(0);
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

test('Terrain shares fixed Objects and exposes scientific tools through non-scrolling pages',async({page})=>{
 await page.setViewportSize({width:1280,height:720});
 await page.route('**/tile.openstreetmap.org/**',r=>r.fulfill({contentType:'image/png',body:tile}));
 await page.goto('/');
 await activateWorkspaceModule(page,'Survey');
 const objects=page.locator('.workspace-objects');
 const before=await objects.boundingBox();
 await activateWorkspaceModule(page,'Terrain');
 const after=await objects.boundingBox();
 expect(after!.y).toBe(before!.y);
 const panel=page.locator('#tools-terrain');
 await expect(panel.getByLabel('DEM elevation layer')).toBeVisible();
 await expect(panel.getByLabel('Choose terrain analysis')).toBeVisible();
 await expect(panel.locator('details,summary')).toHaveCount(0);
 await panel.getByLabel('Choose terrain analysis').selectOption('viewshed_multi');
 await expect(panel.getByRole('heading',{name:'Multi-observer viewshed'})).toBeVisible();
 const form=panel.getByLabel('Terrain parameter pages');
 const next=form.getByRole('button',{name:'Next terrain page'});
 await expect(next).toBeVisible();
 const collected=new Set<string>();
 for(let i=0;i<20;i++){
  const labels=await form.locator('.terrain-page-row[aria-hidden="false"] [aria-label]').evaluateAll(els=>els.map(el=>el.getAttribute('aria-label')!));
  labels.forEach(label=>collected.add(label));
  const visible=await form.locator('.terrain-page-row[aria-hidden="false"]').evaluateAll(els=>els.every(el=>el.getBoundingClientRect().bottom<=el.parentElement!.getBoundingClientRect().bottom+1));
  expect(visible).toBe(true);
  if(await next.isDisabled())break;
  await next.click();
 }
 expect(collected.has('Observer 1 longitude')).toBe(true);
 expect(collected.has('Viewshed maximum distance')).toBe(true);
 await expect(page.getByRole('button',{name:'Run terrain operation'})).toBeInViewport({ratio:1});
 const content=page.locator('.gis-operations .workspace-module-content');
 expect(await content.evaluate(e=>getComputedStyle(e).overflowY)).toBe('clip');
 await content.hover();
 await page.mouse.wheel(0,600);
 expect(await content.evaluate(e=>e.scrollTop)).toBe(0);
});
