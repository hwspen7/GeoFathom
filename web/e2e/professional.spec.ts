import {expect,test,type Page} from '@playwright/test';

const tile='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/ZecAAAAASUVORK5CYII=';
test.beforeEach(async({page})=>{
  await page.route('**/tile.openstreetmap.org/**',route=>
    route.fulfill({status:200,contentType:'image/png',body:Buffer.from(tile,'base64')}));
});
const API='http://127.0.0.1:8000';

async function create(page:Page,name:string){
  await page.goto('/');
  await page.getByLabel('New project name').fill(name);
  await page.getByRole('button',{name:'Create project'}).click();
  const select=page.getByLabel('Active project');
  const option=select.locator('option',{hasText:name});
  await expect(option).toHaveCount(1);
  const id=await option.getAttribute('value');
  expect(id).toBeTruthy();
  await expect(select).toHaveValue(id!);
  return id!;
}
async function add(page:Page,id:string,name:string,geometry:GeoJSON.Geometry,
                   properties:Record<string,unknown>={}){
  const r=await page.request.post(API+'/projects/'+id+'/features',{data:{
    name,geometry,properties,source:'E2E acceptance',
  }});
  expect(r.status()).toBe(201);
  return await r.json();
}
function rectangle(x:number,y:number,w=.02,h=.02):GeoJSON.Polygon{
  return {type:'Polygon',coordinates:[[
    [x,y],[x+w,y],[x+w,y+h],[x,y+h],[x,y],
  ]]};
}

test('professional spatial QA detects overlap and prints a valid real PDF',async({page})=>{
  const id=await create(page,'P0 quality and PDF');
  await add(page,id,'Parcel A',rectangle(0,22));
  await add(page,id,'Parcel B',rectangle(.015,22));
  await page.reload();
  await page.locator('details').filter({hasText:'Topology quality inspection'})
    .locator('summary').click();
  await page.getByLabel('Run topology QA').click();
  await expect(page.getByLabel('Topology QA results')).toContainText('overlap');
  const api=await page.request.post(API+'/projects/'+id+'/quality/topology',{data:{
    study_area:rectangle(0,22,.04,.04),minimum_area_m2:1,
  }});
  expect(api.status()).toBe(200);
  expect((await api.json()).counts.overlap).toBeGreaterThan(0);
  await page.locator('details').filter({hasText:'PDF print layout'})
    .locator('summary').click();
  await page.getByLabel('PDF map title').fill('Engineering Parcel Map');
  await page.getByLabel('PDF paper').selectOption('a3');
  const downloaded=page.waitForEvent('download');
  await page.getByLabel('Export vector PDF').click();
  const file=await downloaded;
  expect(file.suggestedFilename()).toBe('geofathom-map.pdf');
  const response=await page.request.post(API+'/projects/'+id+'/print/pdf',{data:{
    title:'Engineering Parcel Map',paper:'a3',orientation:'landscape',
    extent:null,show_grid:true,show_legend:true,layer_ids:null,
  }});
  expect(response.status()).toBe(200);
  const bytes=await response.body();
  expect(bytes.subarray(0,4).toString()).toBe('%PDF');
});

test('graduated choropleth writes real breaks; CRS grid converts and persists',async({page})=>{
  const id=await create(page,'P1 map styling');
  for(const [i,height] of [12,24,38,80,190].entries())
    await add(page,id,'Asset '+i,{type:'Point',coordinates:[i*.002,22]},
      {height});
  await page.reload();
  await page.locator('details').filter({hasText:'Graduated numeric choropleth'})
    .locator('summary').click();
  await page.getByLabel('Graduated numeric field').fill('height');
  await page.getByLabel('Graduated class count').selectOption('4');
  await page.getByLabel('Graduated method').selectOption('jenks');
  await page.getByRole('button',{name:'Calculate & save color classes'}).click();
  await expect(page.getByText('Layer graduated colors updated.')).toBeVisible();
  const w=await page.request.get(API+'/projects/'+id+'/workspace');
  const workspace=await w.json();
  expect(workspace.layers[0].style.symbol.graduated_field).toBe('height');
  expect(workspace.layers[0].style.symbol.graduated_colors.length)
    .toBeGreaterThan(1);
  await page.locator('details').filter({hasText:'Project EPSG coordinates & grid'})
    .locator('summary').click();
  await page.getByLabel('Project EPSG code').fill('EPSG:32631');
  await page.getByRole('button',{name:'Save project CRS'}).click();
  await expect(page.getByText('Project EPSG and coordinate grid settings saved.')).toBeVisible();
  const crs=await page.request.get(API+'/projects/'+id+'/crs');
  expect((await crs.json()).epsg).toBe('EPSG:32631');
  const transform=await page.request.post(API+'/projects/'+id+'/crs/transform',{
    data:{points:[[0,22]],target:'EPSG:32631'},
  });
  expect(transform.status()).toBe(200);
  expect((await transform.json()).coordinates[0][0]).toBeGreaterThan(100000);
});

test('P2 jobs and optional backend status work without configuring cloud services',async({page})=>{
  const id=await create(page,'P2 background workflows');
  await add(page,id,'Field A',rectangle(0,22));
  await page.reload();
  await page.locator('details').filter({hasText:'Persistent background GIS jobs'})
    .locator('summary').click();
  await page.getByLabel('Background GIS job type').selectOption('export_geojson');
  await page.getByRole('button',{name:'Queue background operation'}).click();
  await expect(page.getByLabel('GIS background tasks')).toContainText('completed',
    {timeout:16000});
  const jobs=await page.request.get(API+'/projects/'+id+'/jobs');
  const list=await jobs.json();
  expect(list.jobs[0].status).toBe('completed');
  expect(list.jobs[0].result.type).toBe('FeatureCollection');
  await page.locator('details').filter({hasText:'Spatial database & indexed viewport'})
    .locator('summary').click();
  await expect(page.getByLabel('PostGIS status')).toContainText(/Not configured|Configured, offline|Connected/);
  await page.locator('details').filter({hasText:'OGC map & feature services'})
    .locator('summary').click();
  await expect(page.getByLabel('New OGC service type')).toHaveValue('wms');
});

test('drawing selection rectangle selects actual saved map features',async({page})=>{
  const id=await create(page,'P0 rectangle select');
  await add(page,id,'Map center',{type:'Point',coordinates:[0,22]});
  await page.reload();
  const map=page.getByLabel('Interactive geospatial map');
  await expect(map).toHaveAttribute('data-label-layer-ready','true',{timeout:25000});
  await page.locator('details').filter({hasText:'Select by location'})
    .locator('summary').click();
  await page.getByLabel('Draw selection rectangle').click();
  const rect=await map.boundingBox();
  expect(rect).not.toBeNull();
  const cx=rect!.x+rect!.width/2,cy=rect!.y+rect!.height/2;
  await page.mouse.move(cx-50,cy-55);
  await page.mouse.down();
  await page.mouse.move(cx+50,cy+55,{steps:12});
  await page.mouse.up();
  await expect(page.getByLabel('Select spatial matches')).toBeEnabled();
  await page.getByLabel('Select spatial matches').click();
  await expect(page.getByLabel('Spatial selection results')).toContainText('Map center');
});


test('P1 drag a saved point label and commit revisioned offset fields',async({page})=>{
  const id=await create(page,'P1 freehand label placement');
  await add(page,id,'Important POI',{type:'Point',coordinates:[0,22]},
    {category:'field station'});
  await page.reload();
  const map=page.getByLabel('Interactive geospatial map');
  await expect(map).toHaveAttribute('data-label-layer-ready','true',{timeout:25000});
  await page.locator('.layer-cartography summary').click();
  await page.getByLabel('Enable layer labels').check();
  await expect.poll(async()=>{
    const r=await page.request.get(API+'/projects/'+id+'/workspace');
    return (await r.json()).layers[0].style.labels.enabled;
  }).toBe(true);
  await page.locator('details').filter({hasText:'Advanced label placement & callouts'})
    .locator('summary').click();
  await page.getByLabel('Label rule field').fill('category');
  await page.getByLabel('Label rule field').press('Tab');
  await expect.poll(async()=>{
    const r=await page.request.get(API+'/projects/'+id+'/workspace');
    return (await r.json()).layers[0].style.labels.rule_field;
  }).toBe('category');
  await page.getByLabel('Label rule operator').selectOption('contains');
  await page.getByLabel('Label rule value').fill('field');
  await page.getByLabel('Label rule value').press('Tab');
  await expect.poll(async()=>{
    const r=await page.request.get(API+'/projects/'+id+'/workspace');
    return (await r.json()).layers[0].style.labels.rule_value;
  }).toBe('field');
  await page.getByLabel('Move map labels').click();
  await expect(page.getByRole('button',{name:'Stop moving labels'})).toBeVisible();
  const bbox=await map.boundingBox();
  expect(bbox).not.toBeNull();
  const x=bbox!.x+bbox!.width/2,y=bbox!.y+bbox!.height/2;
  await page.mouse.move(x,y);
  await page.mouse.down();
  await page.mouse.move(x+55,y+20,{steps:10});
  await page.mouse.up();
  await expect.poll(async()=>{
    const r=await page.request.get(API+'/projects/'+id+'/workspace');
    const w=await r.json();
    return w.features[0].revision;
  },{timeout:13000}).toBeGreaterThan(0);
  const response=await page.request.get(API+'/projects/'+id+'/workspace');
  const w=await response.json();
  expect(w.features[0].properties.label_offset_x).toBeGreaterThan(0);
  expect(w.features[0].properties.label_offset_y).toBeGreaterThan(0);
});
