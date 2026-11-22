import {test,expect} from './coverage-fixture';
import {execFileSync} from 'node:child_process';
import {resolve} from 'node:path';
const API='http://127.0.0.1:8000';
const tile=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/ZecAAAAASUVORK5CYII=','base64');

test('real DEM is imported, analyzed, visualized and saved through workbench',async({page})=>{
 test.setTimeout(90000);
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
 await page.getByRole('navigation',{name:'Workspace tools'}).getByRole('button',{name:'Terrain',exact:true}).click();
 const tools=page.getByLabel('Terrain tools');
 const map=page.getByLabel('Interactive geospatial map');
 await tools.getByRole('button',{name:'Slope / aspect',exact:true}).click();
 await page.getByRole('button',{name:'Run terrain operation'}).click();
 await expect(page.getByRole('img',{name:'Slope (degrees)'})).toBeVisible();
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
 await expect(page.getByLabel('Interactive 3D terrain preview')).toBeVisible();
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
 await expect(page.getByLabel('Profile sample position')).toBeVisible();
});
