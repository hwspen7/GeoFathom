import {test,expect} from './coverage-fixture';
import {execFileSync} from 'node:child_process';
import {resolve} from 'node:path';
const API='http://127.0.0.1:8000';
const tile=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/ZecAAAAASUVORK5CYII=','base64');

test('real DEM is imported, analyzed, visualized and saved through workbench',async({page})=>{
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
 await page.getByRole('navigation',{name:'Workspace tools'}).getByRole('button',{name:'Raster / AI',exact:true}).click();
 await page.getByLabel('Select georeferenced imagery').selectOption(fixture.id);
 await page.getByRole('button',{name:'DEM study area',exact:true}).click();
 await page.getByRole('navigation',{name:'Workspace tools'}).getByRole('button',{name:'GIS',exact:true}).click();
 await page.getByText('Advanced DEM tools',{exact:true}).click();
 const mode=page.getByLabel('Advanced terrain operation');
 await mode.selectOption('contours');
 await page.getByLabel('Contour interval').fill('5');
 await page.getByRole('button',{name:'Run terrain operation'}).click();
 await expect(page.getByRole('button',{name:'Save terrain features'})).toBeEnabled();
 await page.getByRole('button',{name:'Save terrain features'}).click();
 await expect(page.getByText(/Saved .* terrain features/)).toBeVisible();
 await mode.selectOption('volume');
 await page.getByLabel('Reference elevation').fill('110');
 await page.getByRole('button',{name:'Run terrain operation'}).click();
 await expect(page.getByText('cut m3',{exact:true})).toBeVisible();
 await mode.selectOption('mesh');
 await page.getByRole('button',{name:'Run terrain operation'}).click();
 await expect(page.getByLabel('Interactive 3D terrain preview')).toBeVisible();
});
