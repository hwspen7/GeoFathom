import {expect,test} from '@playwright/test';

const tile='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/ZecAAAAASUVORK5CYII=';
test.beforeEach(async({page})=>{
  await page.route('**/tile.openstreetmap.org/**',route=>
    route.fulfill({status:200,contentType:'image/png',body:Buffer.from(tile,'base64')}));
});

async function project(page:import('@playwright/test').Page,name:string) {
  // Each test retry must own a unique project. Shared CI backend data
  // persists across browser retries and otherwise creates ambiguous options.
  name=name+'-'+Date.now().toString(36)+'-'+Math.random().toString(36).slice(2,8);
  await page.goto('/');
  await page.getByLabel('New project name').fill(name);
  await page.getByRole('button',{name:'Create project'}).click();
  const selection=page.getByLabel('Active project');
  await expect(selection).toBeVisible();
  const option=selection.locator('option',{hasText:name});
  await expect(option).toHaveCount(1);
  const createdId=await option.getAttribute('value');
  expect(createdId).toBeTruthy();
  await expect(selection).toHaveValue(createdId!);
  return createdId!;
}
async function savedWorkspace(page:import('@playwright/test').Page,id:string) {
  const r=await page.request.get('http://127.0.0.1:8000/projects/'+id+'/workspace');
  expect(r.ok()).toBeTruthy();
  return await r.json() as {
    layers:Array<{id:string;name:string;visible:number;style_revision:number;
      style:{labels:{enabled:boolean;field:string;font_size:number};
             symbol:{fill_opacity:number}}}>;
    features:Array<{id:string;name:string;revision:number;properties:Record<string,unknown>;
                    geometry:GeoJSON.Geometry}>;
  };
}

test('style labels by field, persist symbol settings and reload the workspace',async({page})=>{
  const id=await project(page,'Labeling integration');
  const map=page.getByLabel('Interactive geospatial map');
  await expect(map).toHaveAttribute('data-label-layer-ready','true',{timeout:25000});
  await page.locator('.layer-cartography summary').click();
  const enabled=page.getByLabel('Enable layer labels');
  await expect(enabled).not.toBeChecked();
  await enabled.check();
  await expect.poll(async()=>{
    const w=await savedWorkspace(page,id);
    return w.layers[0].style.labels.enabled;
  }).toBe(true);
  const field=page.getByLabel('Label source field');
  await field.fill('category');
  await field.press('Tab');
  await expect.poll(async()=>{
    const w=await savedWorkspace(page,id);
    return w.layers[0].style.labels.field;
  }).toBe('category');
  await page.getByLabel('Label font size').selectOption('18');
  await expect.poll(async()=>{
    const w=await savedWorkspace(page,id);
    return w.layers[0].style.labels.font_size;
  }).toBe(18);
  await page.getByLabel('Polygon fill opacity').selectOption('0.6');
  await expect.poll(async()=>{
    const w=await savedWorkspace(page,id);
    return w.layers[0].style.symbol.fill_opacity;
  }).toBe(.6);
  // Another browser may create a newer project before this tab reloads.
  const other=await page.request.post('http://127.0.0.1:8000/projects',{
    data:{name:'Concurrent unrelated project '+id},
  });
  expect(other.status()).toBe(201);
  await page.reload();
  await expect(page.getByLabel('Active project')).toHaveValue(id);
  await page.locator('.layer-cartography summary').click();
  await expect(page.getByLabel('Enable layer labels')).toBeChecked();
  await expect(page.getByLabel('Label font size')).toHaveValue('18');
  await expect(page.getByLabel('Label source field')).toHaveValue('category');
  await expect(page.getByLabel('Polygon fill opacity')).toHaveValue('0.6');
  await expect(page.getByLabel('Map legend',{exact:true})).toContainText('Measurements');
  await page.getByLabel('Toggle map legend').click();
  await expect(page.getByLabel('Map legend',{exact:true})).not.toBeVisible();
});

test('click to create, rename, revise and delete a permanent map note',async({page})=>{
  const id=await project(page,'Annotation integration');
  const map=page.getByLabel('Interactive geospatial map');
  await expect(map).toHaveAttribute('data-label-layer-ready','true',{timeout:25000});
  await page.getByLabel('Map note text').fill('Observation point 设备 A');
  await page.getByLabel('Place map note').click();
  await expect(page.getByLabel('Cancel map note')).toBeVisible();
  const bbox=await map.boundingBox();
  expect(bbox).not.toBeNull();
  await page.mouse.click(bbox!.x+bbox!.width*.52,bbox!.y+bbox!.height*.52);
  await expect(page.getByText('Map annotation saved.')).toBeVisible();
  await expect.poll(async()=> (await savedWorkspace(page,id)).features.length).toBe(1);
  await expect.poll(async()=>Number(await map.getAttribute('data-label-feature-count')),
    {timeout:15000}).toBeGreaterThan(0);
  let w=await savedWorkspace(page,id);
  expect(w.features[0].properties.annotation).toBe(true);
  expect(w.features[0].properties.annotation_text).toBe('Observation point 设备 A');
  expect(w.features[0].geometry.type).toBe('Point');
  await page.getByLabel('Edit selected map note').fill('Updated observation point');
  await page.getByLabel('Save map note text').click();
  await expect(page.getByText('Annotation text saved as a new revision.')).toBeVisible();
  await expect.poll(async()=>{
    const out=await savedWorkspace(page,id);
    return out.features[0].properties.annotation_text;
  }).toBe('Updated observation point');
  w=await savedWorkspace(page,id);
  expect(w.features[0].revision).toBe(1);
  page.once('dialog',dialog=>void dialog.accept());
  await page.getByLabel('Delete selected map feature').click();
  await expect.poll(async()=> (await savedWorkspace(page,id)).features.length).toBe(0);
});

test('annotation respects locked layer and project boundaries',async({page})=>{
  const id=await project(page,'Annotation permissions');
  const w=await savedWorkspace(page,id);
  const lid=w.layers[0].id;
  const response=await page.request.patch(
    'http://127.0.0.1:8000/projects/'+id+'/layers/'+lid,
    {data:{locked:true}},
  );
  expect(response.ok()).toBeTruthy();
  const blocked=await page.request.post(
    'http://127.0.0.1:8000/projects/'+id+'/annotations',
    {data:{text:'Should not save',position:[0,22],layer_id:lid}},
  );
  expect(blocked.status()).toBe(409);
  const foreign=await page.request.post(
    'http://127.0.0.1:8000/projects/invalid-id/annotations',
    {data:{text:'Should not cross projects',position:[0,22],layer_id:lid}},
  );
  expect(foreign.status()).toBe(404);
  expect((await savedWorkspace(page,id)).features).toHaveLength(0);
});


test('categorized attribute colors produce visible legend classes and identify a feature',async({page})=>{
  const id=await project(page,'Categorized buildings');
  const point=(x:number,name:string,category:string)=>({
    name,source:'Surveyor',geometry:{type:'Point',coordinates:[x,22]},
    properties:{category,height:12},
  });
  for(const item of [point(0,'Facility A','hospital'),point(1,'Facility B','school')]){
    const response=await page.request.post(
      'http://127.0.0.1:8000/projects/'+id+'/features',{data:item},
    );
    expect(response.status()).toBe(201);
  }
  await page.reload();
  await page.locator('.layer-cartography summary').click();
  await page.getByLabel('Category color field').fill('category');
  await page.getByLabel('Category color field').press('Tab');
  await expect.poll(async()=>{
    const w=await savedWorkspace(page,id);
    return w.layers[0].style.symbol.category_field;
  }).toBe('category');
  await page.getByRole('button',{name:'Generate colors for attribute categories'}).click();
  await expect.poll(async()=>{
    const r=await page.request.get(
      'http://127.0.0.1:8000/projects/'+id+'/workspace');
    const w=await r.json();
    return Object.keys(w.layers[0].style.symbol.category_colors).length;
  }).toBe(2);
  const legend=page.getByLabel('Map legend',{exact:true});
  await expect(legend).toContainText('hospital');
  await expect(legend).toContainText('school');
  await page.locator('.project-features button').filter({hasText:'Facility A'}).click();
  await page.locator('.feature-inspector summary').click();
  await expect(page.locator('.feature-inspector-body')).toContainText('Surveyor');
  await expect(page.getByText(/height:/)).toBeVisible();
  const map=page.getByLabel('Interactive geospatial map');
  const bounds=await map.boundingBox();
  expect(bounds).not.toBeNull();
  await page.mouse.move(bounds!.x+bounds!.width*.5,bounds!.y+bounds!.height*.5);
  await expect(page.getByLabel('Cursor coordinates')).toContainText(/Lon .*Lat /);
});

test('map labels treat HTML-like annotation content as plain geographic data',async({page})=>{
  const id=await project(page,'Safe map labels');
  const malicious='<img src=x onerror=alert(1)>';
  const map=page.getByLabel('Interactive geospatial map');
  // The asynchronous MapLibre source must be ready before accepting
  // geographic clicks; the map canvas existing in the DOM is insufficient.
  await expect(map).toHaveAttribute('data-label-layer-ready','true',{timeout:25000});
  await page.getByLabel('Map note text').fill(malicious);
  await page.getByLabel('Place map note').click();
  await expect(page.getByLabel('Cancel map note')).toBeVisible();
  const bounds=await map.boundingBox();
  expect(bounds).not.toBeNull();
  await page.mouse.click(bounds!.x+bounds!.width*.52,bounds!.y+bounds!.height*.52);
  await expect.poll(async()=> (await savedWorkspace(page,id)).features.length,
    {timeout:15000}).toBe(1);
  const w=await savedWorkspace(page,id);
  expect(w.features[0].properties.annotation_text).toBe(malicious);
  expect(await page.evaluate(()=>document.querySelectorAll('img[onerror]').length)).toBe(0);
});
