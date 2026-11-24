import {expect,test} from './coverage-fixture';
import {activateWorkspaceModule} from './workspace-ui';
import {readFile} from 'node:fs/promises';

const points=(count:number)=>({type:'FeatureCollection',features:Array.from({length:count},(_,i)=>({
 type:'Feature',geometry:{type:'Point',coordinates:[-83+i*.00001,40]},
 properties:{name:'设施 '+i,category:'station',height:12.5,active:true,nullable:null,nested:{value:[i,false]}},
}))});
async function downloaded(download:import('@playwright/test').Download){
 const path=await download.path();expect(path).toBeTruthy();return readFile(path!);
}

test('batch imports 620 rows and exports full CSV and GDAL datasets beyond the UI page',async({page,request})=>{
 test.setTimeout(90000);
 const created=await request.post('/api/projects',{data:{name:'Exchange '+Date.now()}});expect(created.ok()).toBeTruthy();
 const project=await created.json();
 await page.goto('/');await page.getByLabel('Active project',{exact:true}).selectOption(project.id);
 await activateWorkspaceModule(page,'Data',true);
 await page.getByRole('button',{name:'Import',exact:true}).click();
 await page.getByRole('button',{name:'Advanced import',exact:true}).click();
 await page.getByLabel('Batch dataset files').setInputFiles({name:'stations.geojson',mimeType:'application/geo+json',buffer:Buffer.from(JSON.stringify(points(620)))});
 await expect(page.getByLabel('Source layers')).toContainText('620 features');
 await page.getByRole('button',{name:'Import batch',exact:true}).click();
 await expect(page.getByText(/Imported 620 features · 0 rejected/)).toBeVisible({timeout:30000});
 const reportEvent=page.waitForEvent('download');await page.getByRole('button',{name:'Download import report'}).click();
 const report=JSON.parse((await downloaded(await reportEvent)).toString());expect(report.created).toBe(620);
 const workspace=await (await request.get('/api/projects/'+project.id+'/workspace')).json();
 expect(workspace.total).toBe(620);expect(workspace.features).toHaveLength(200);
 await activateWorkspaceModule(page,'Export');
 await page.getByLabel('Export scope',{exact:true}).selectOption('project');
 await page.getByLabel('Export format',{exact:true}).selectOption('csv');
 await page.getByRole('button',{name:'Inspect export',exact:true}).click();
 await expect(page.getByText(/620 features · Point/)).toBeVisible();
 const csvEvent=page.waitForEvent('download');await page.getByRole('button',{name:'Export CSV',exact:true}).click();
 const csv=(await downloaded(await csvEvent)).toString();
 expect(csv.split('\n').filter(line=>line.trim())).toHaveLength(621);
 expect(csv).toContain('设施 619');expect(csv).toContain('category');expect(csv).toContain('geometry_wkt');
 await page.getByLabel('Export format',{exact:true}).selectOption('gpkg');
 await page.getByLabel('Export target EPSG').fill('EPSG:3857');
 await page.getByLabel('Export setup').selectOption('delivery');
 await page.getByLabel('Background dataset export').check();
 await page.getByRole('button',{name:'Export GPKG',exact:true}).click();
 // The queued artifact retains its original project scope while the user
 // edits inputs for a subsequent export. Progress must keep updating.
 await page.getByLabel('Export scope',{exact:true}).selectOption('local');
 await expect(page.getByRole('button',{name:'Download dataset',exact:true})).toBeVisible({timeout:30000});
 const gpkgEvent=page.waitForEvent('download');await page.getByRole('button',{name:'Download dataset',exact:true}).click();
 const binary=await downloaded(await gpkgEvent);expect(binary.subarray(0,15).toString()).toBe('SQLite format 3');
 const other=await (await request.post('/api/projects',{data:{name:'Roundtrip '+Date.now()}})).json();
 const imported=await request.post('/api/projects/'+other.id+'/vector/import',{multipart:{file:{name:'stations.gpkg',mimeType:'application/octet-stream',buffer:binary}}});
 expect(imported.status(),await imported.text()).toBe(201);expect((await imported.json()).created).toBe(620);
 const result=await (await request.get('/api/projects/'+other.id+'/vector/export/geojson')).json();
 expect(result.features).toHaveLength(620);
 expect(result.features.find((f:GeoJSON.Feature)=>f.properties?.name==='设施 619').properties).toMatchObject({height:12.5,active:true,nullable:null,nested:{value:[619,false]}});
});

test('CSV configuration maps coordinates and types and reports an invalid row',async({page,request})=>{
 const project=await (await request.post('/api/projects',{data:{name:'CSV '+Date.now()}})).json();
 await page.goto('/');await page.getByLabel('Active project',{exact:true}).selectOption(project.id);
 await activateWorkspaceModule(page,'Data',true);await page.getByRole('button',{name:'Import',exact:true}).click();
 await page.getByRole('button',{name:'Advanced import',exact:true}).click();
 await page.getByLabel('Batch dataset files').setInputFiles({name:'sites.csv',mimeType:'text/csv',buffer:Buffer.from('x,y,name,count\n-83,40,Valid,12\nbad,40,Invalid,4\n')});
 await expect(page.getByLabel('Source layers')).toContainText('2 features');
 await page.getByLabel('Import error policy').selectOption('skip');
 await page.getByLabel('Import configuration').selectOption('coordinates');
 await page.getByLabel('CSV longitude field').fill('x');await page.getByLabel('CSV latitude field').fill('y');
 await page.getByLabel('Import configuration').selectOption('fields');
 await page.getByLabel('Import source field').selectOption('count');
 await page.getByLabel('Import field name').fill('population');
 await page.getByLabel('Import field type').selectOption('integer');
 await page.getByRole('button',{name:'Import batch',exact:true}).click();
 await expect(page.getByText(/Imported 1 features · 1 rejected/)).toBeVisible({timeout:30000});
 const data=await (await request.get('/api/projects/'+project.id+'/vector/export/geojson')).json();
 expect(data.features[0].properties.population).toBe(12);expect(data.features[0].properties.count).toBeUndefined();
 const event=page.waitForEvent('download');await page.getByRole('button',{name:'Download import report'}).click();
 expect(JSON.parse((await downloaded(await event)).toString()).files[0].errors[0].row).toBe(2);
});

test('portable project ZIP is restored through Data into an empty project',async({page,request})=>{
 const project=await (await request.post('/api/projects',{data:{name:'Package '+Date.now()}})).json();
 const source=points(3);
 const imported=await request.post('/api/projects/'+project.id+'/vector/import',{multipart:{file:{name:'sites.geojson',mimeType:'application/geo+json',buffer:Buffer.from(JSON.stringify(source))}}});
 expect(imported.status()).toBe(201);
 const empty=await (await request.post('/api/projects',{data:{name:'Restore '+Date.now()}})).json();
 await page.goto('/');await page.getByLabel('Active project',{exact:true}).selectOption(project.id);
 await activateWorkspaceModule(page,'Export',true);await page.getByLabel('Export format',{exact:true}).selectOption('package');
 const event=page.waitForEvent('download');await page.getByRole('button',{name:'Export PACKAGE',exact:true}).click();
 const pkg=await downloaded(await event);expect(pkg.subarray(0,2).toString()).toBe('PK');
 await page.getByLabel('Active project',{exact:true}).selectOption(empty.id);
 await activateWorkspaceModule(page,'Data');await page.getByRole('button',{name:'Import',exact:true}).click();
 await page.getByRole('button',{name:'Advanced import',exact:true}).click();await page.getByRole('button',{name:'Restore project',exact:true}).click();
 await page.getByLabel('Restore project package').setInputFiles({name:'project.zip',mimeType:'application/zip',buffer:pkg});
 await expect(page.getByText(/Restored 3 features/)).toBeVisible({timeout:30000});
 const restored=await (await request.get('/api/projects/'+empty.id+'/vector/export/geojson')).json();
 expect(restored.features).toHaveLength(3);expect(restored.features[2].properties.nested).toBeTruthy();
});
