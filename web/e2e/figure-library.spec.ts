import {activateWorkspaceModule} from './workspace-ui';
import {test,expect} from './coverage-fixture';
import {execFileSync} from 'node:child_process';
import {resolve} from 'node:path';
import {readFileSync} from 'node:fs';
const API='http://127.0.0.1:8000';
const tile=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/ZecAAAAASUVORK5CYII=','base64');

test('a real slope result opens the scientific figure library and exports numerical data and publication figures',async({page},testInfo)=>{
 test.setTimeout(240000);
 const fixture=JSON.parse(execFileSync('python',['-c',`
import json,tempfile
from pathlib import Path
import numpy as np,rasterio
from rasterio.transform import from_origin
from rasterio.warp import transform_geom
from shapely.geometry import box,mapping
from imagery.store import store_upload
with tempfile.TemporaryDirectory() as directory:
 p=Path(directory)/'figure-dem.tif'
 yy,xx=np.indices((32,32))
 z=100+xx*.5+np.sin(yy/5)*3+np.cos(xx/4)*2
 with rasterio.open(p,'w',driver='GTiff',width=32,height=32,count=1,dtype='float32',
   crs='EPSG:32617',transform=from_origin(500000,4500000,10,10),nodata=-9999) as ds:
  ds.write(z.astype('float32'),1)
 meta=store_upload(p,'Figure library DEM.tif')
 geometry=transform_geom('EPSG:32617','EPSG:4326',mapping(box(500020,4499700,500300,4499980)))
 print(json.dumps({'id':meta['id'],'geometry':geometry}))
`],{cwd:resolve('..'),env:{...process.env,GEOFATHOM_IMAGERY_DIR:resolve('..',process.env.GEOFATHOM_E2E_DATABASE_PATH||'data/e2e-geofathom.sqlite')+'.imagery'},encoding:'utf8'}));
 const project=await page.request.post(API+'/projects',{data:{name:'Figure library '+Date.now()}});
 expect(project.status()).toBe(201);const projectId=(await project.json()).id;
 expect((await page.request.post(API+'/projects/'+projectId+'/features',{data:{name:'Figure study area',source:'Numerical fixture',geometry:fixture.geometry}})).status()).toBe(201);
 await page.route('**/tile.openstreetmap.org/**',r=>r.fulfill({contentType:'image/png',body:tile}));
 await page.goto('/');await page.getByLabel('Active project').selectOption(projectId);await activateWorkspaceModule(page,'Terrain');
 await page.getByLabel('DEM elevation layer').selectOption(fixture.id);await page.getByLabel('Confirm DEM meter elevations').check();
 await page.locator('.workspace-objects > summary').click();await page.getByRole('button',{name:/Figure study area/}).click();
 await page.getByLabel('Choose terrain analysis').selectOption('slope_map');
 const analysisResponse=page.waitForResponse(r=>r.url().endsWith('/terrain/advanced')&&r.request().method()==='POST');
 await page.getByRole('button',{name:'Run terrain operation'}).click();
 const response=await analysisResponse;expect(response.status()).toBe(200);const result=await response.json();
 await expect(page.getByLabel('Choose terrain result')).not.toHaveValue('');
 await page.getByRole('tab',{name:'Figures',exact:true}).click();
 await page.getByRole('button',{name:'Expand',exact:true}).click();
 const expanded=page.getByRole('dialog',{name:'Expanded terrain result'});
 await expect(expanded).toBeVisible();
 await expanded.getByRole('button',{name:'Figure library',exact:true}).click();
 await expect(expanded).toBeHidden();
 const dialog=page.getByRole('dialog',{name:'Scientific figure library'});await expect(dialog).toBeVisible();
 for(const [value,name] of [['histogram','Histogram'],['cdf','Cumulative distribution'],['box','Box and whisker'],['qq','Normal Q–Q'],['scatter','Elevation–result scatter'],['joint_density','Elevation–result density']] as const){
  await dialog.getByLabel('Chart type').selectOption(value);await expect(dialog.getByRole('img',{name:'Scientific figure: '+name})).toBeVisible();
 }
 await dialog.getByLabel('Chart type').selectOption('histogram');
 await dialog.getByLabel('Numerical bins').selectOption('80');
 await dialog.getByRole('button',{name:'Style',exact:true}).click();
 await dialog.getByLabel('Figure title').fill('Slope distribution in the study area');
 await dialog.getByLabel('Font',{exact:true}).selectOption('serif');
 await dialog.getByRole('button',{name:'Axes',exact:true}).click();
 await dialog.getByLabel('X axis label').fill('Slope angle (degrees)');
 await dialog.getByLabel('Y axis label').fill('Area share (%)');
 await dialog.getByRole('button',{name:'Style',exact:true}).click();
 await dialog.getByLabel('Style name').fill('Publication monochrome');await dialog.getByRole('button',{name:'Save style',exact:true}).click();
 await dialog.getByRole('button',{name:'Charts',exact:true}).click();
 await page.screenshot({path:testInfo.outputPath('survey-figure-library.png')});
 const getFile=async(name:string)=>{const event=page.waitForEvent('download');await dialog.getByRole('button',{name,exact:true}).click();const file=await event;const path=await file.path();expect(path).toBeTruthy();return {data:readFileSync(path!),path:path!,name:file.suggestedFilename()};};
 const csv=await getFile('CSV');expect(csv.name).toBe('terrain-slope_map-histogram.csv');
 const lines=csv.data.toString('utf8').trim().split(/\r?\n/);expect(lines.length).toBe(81);
 const cellCounts=lines.slice(1).reduce((sum,row)=>sum+Number(row.split(',')[3]),0);expect(cellCounts).toBe(result.raster.valid_cells);
 const svg=await getFile('SVG');expect(svg.data.toString('utf8')).toContain('Slope distribution in the study area');expect(svg.data.toString('utf8')).toContain('geofathom-figure-1');
 const pdf=await getFile('PDF');expect(pdf.data.subarray(0,5).toString()).toBe('%PDF-');
 execFileSync('python',['-c',`from pypdf import PdfReader;import sys;r=PdfReader(sys.argv[1]);assert 'Slope distribution' in r.pages[0].extract_text();assert '/XObject' not in r.pages[0]['/Resources']`,pdf.path]);
 const png=await getFile('PNG');expect(png.data.subarray(0,8).toString('hex')).toBe('89504e470d0a1a0a');
 expect(png.data.indexOf(Buffer.from('pHYs'))).toBeGreaterThan(0);
 const json=await getFile('JSON');const payload=JSON.parse(json.data.toString('utf8'));expect(payload.data.valid_cells).toBe(result.raster.valid_cells);expect(payload.metadata.source.sha256).toHaveLength(64);
 const python=await getFile('Python script');expect(python.data.toString('utf8')).toContain('base64.b64decode');
 await dialog.getByRole('button',{name:'Extended figure studio'}).click();
 const studio=page.getByRole('dialog',{name:'Scientific figure studio'});
 await expect(studio).toBeVisible();
 await studio.getByRole('button',{name:/Continuous georeferenced map/}).click();
 await studio.getByRole('button',{name:'Render figure'}).click();
 await expect(studio.getByAltText('Continuous georeferenced map preview')).toBeVisible({timeout:30000});
 await expect(studio.getByRole('button',{name:'Figure composer (1)'})).toBeVisible();
 await studio.getByRole('button',{name:'Add to composition (1/6)',exact:true}).click();
 await studio.getByLabel('Figure category').selectOption('Scenarios');
 await studio.getByRole('button',{name:/Pareto dominance and trade-offs/}).click();
 await studio.getByLabel('Figure CSV data').fill('cost,benefit\n1,1\n2,3\n3,2\n4,5');
 await studio.getByLabel('Figure field x').selectOption('cost');
 await studio.getByLabel('Figure field y').selectOption('benefit');
 await studio.getByText('Maximize Y objective',{exact:true}).click();
 await studio.getByRole('button',{name:'Render figure'}).click();
 await expect(studio.getByAltText('Pareto dominance and trade-offs preview')).toBeVisible({timeout:30000});
 const studioDownload=page.waitForEvent('download');
 await studio.getByRole('button',{name:'PDF',exact:true}).click();
 expect((await studioDownload).suggestedFilename()).toBe('geofathom-pareto.pdf');
 await page.screenshot({path:testInfo.outputPath('extended-scientific-figure.png')});
 await studio.getByRole('button',{name:'Add to composition (2/6)',exact:true}).click();
 await studio.getByRole('button',{name:'Figure composer (3)'}).click();
 await studio.getByLabel('Composition title').fill('Terrain and tradeoff study');
 await studio.getByRole('button',{name:'Render composition'}).click();
 await expect(studio.getByAltText('Publication composition preview')).toBeVisible({timeout:30000});
 await page.screenshot({path:testInfo.outputPath('publication-composition.png')});
 await studio.getByRole('button',{name:'Close studio'}).click();
 await dialog.getByRole('button',{name:'Close figure library'}).click();
});
