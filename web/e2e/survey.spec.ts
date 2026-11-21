import {expect,test} from '@playwright/test';

const tile='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/ZecAAAAASUVORK5CYII=';

test.beforeEach(async({page})=>{
  // Deterministic cartography; CI needs no public tile server credentials.
  await page.route('**/tile.openstreetmap.org/**',route=>
    route.fulfill({status:200,contentType:'image/png',body:Buffer.from(tile,'base64')}));
});

test('survey editor draws, repositions vertices, supports undo and saves project',async({page})=>{
  await page.goto('/');
  const map=page.getByLabel('Interactive geospatial map');
  await expect(map).toBeVisible();
  await expect(map).toHaveAttribute('data-label-layer-ready','true',{timeout:25000});
  await expect(page.getByRole('button',{name:'Polygon',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Polygon',exact:true}).click();
  const box=await map.boundingBox();
  expect(box).not.toBeNull();
  const left=box!.x+box!.width*.40,top=box!.y+box!.height*.40;
  const unit=Math.min(90,box!.width*.12,box!.height*.12);
  const points=[
    [left,top],[left+unit,top],[left+unit,top+unit],[left,top+unit],
  ];
  for(const [x,y] of points)await page.mouse.click(x,y);
  await page.getByRole('button',{name:'Finish',exact:true}).click();
  await expect(page.getByText(/Drawing completed and measured/)).toBeVisible();
  await page.getByRole('button',{name:'Vertices',exact:true}).click();
  const changes:GeoJSON.Geometry[]=[];
  page.on('request',request=>{
    if(request.url().endsWith('/measure')&&request.method()==='POST'){
      const payload=request.postDataJSON() as {geometry:GeoJSON.Geometry};
      changes.push(payload.geometry);
    }
  });
  await expect.poll(async()=>{
    const raw=await map.getAttribute('data-rendered-handle-pixels');
    const positions=raw?JSON.parse(raw) as number[][]:[];
    return positions.length;
  },{timeout:20000}).toBeGreaterThan(0);
  // Query the actual rendered edit handle reported after MapLibre's
  // asynchronous GeoJSON source worker reaches the idle state.
  const screen=JSON.parse((await map.getAttribute('data-rendered-handle-pixels'))||'[]') as number[][];
  expect(screen.length).toBeGreaterThan(0);
  const current=await map.boundingBox();
  expect(current).not.toBeNull();
  const x=current!.x+screen[0][0],y=current!.y+screen[0][1];
  await page.mouse.move(x,y);
  await page.mouse.down();
  await page.mouse.move(x+20,y-20,{steps:12});
  await page.mouse.up();
  try{
    await expect.poll(()=>changes.length,{timeout:10000}).toBeGreaterThan(0);
  }catch(failure){
    const debug=await map.evaluate(element=>Object.fromEntries(
      [...element.attributes].filter(item=>item.name.startsWith('data-dev-')||
        item.name.startsWith('data-rendered')) .map(item=>[item.name,item.value])));
    throw new Error('MapLibre drag acceptance diagnostics: '+
      JSON.stringify(debug)+'; '+String(failure));
  }
  expect(changes[0].type).toBe('Polygon');
  await expect(page.getByRole('button',{name:'Undo',exact:true})).toBeEnabled();
  await page.getByRole('button',{name:'Undo',exact:true}).click();
  await page.getByRole('button',{name:'Redo',exact:true}).click();
  await page.getByLabel('New project name').fill('Playwright Survey');
  await page.getByRole('button',{name:'Create project'}).click();
  await expect(page.getByRole('button',{name:'Save selected'})).toBeEnabled();
  await page.getByRole('button',{name:'Save selected'}).click();
  await expect(page.getByText('New geometry saved to the chosen layer.')).toBeVisible();
});

test('professional GIS panel exposes attributes, vector formats and DEM analysis',async({page})=>{
  await page.goto('/');
  await expect(page.getByText('Professional GIS tools')).toBeVisible();
  await page.getByText(/Attribute table/).click();
  await expect(page.getByLabel('Attribute search field')).toBeVisible();
  await page.getByText('GIS file import / export').click();
  await expect(page.getByLabel('GIS export format')).toBeVisible();
  await page.getByText('Terrain slope & elevation profile').click();
  await expect(page.getByRole('button',{name:/Analyze selected/})).toBeDisabled();
});


test('import KML, query the attribute table and persist a bulk property update',async({page})=>{
  await page.goto('/');
  await page.getByLabel('New project name').fill('Vector browser test');
  await page.getByRole('button',{name:'Create project'}).click();
  await page.getByText('GIS file import / export').click();
  const xml='<?xml version="1.0" encoding="UTF-8"?>'+
    '<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark>'+
    '<name>Facility A</name><Point><coordinates>0,22</coordinates></Point>'+
    '</Placemark></Document></kml>';
  await page.getByLabel('Import GIS vector file').setInputFiles({
    name:'facility.kml',mimeType:'application/vnd.google-earth.kml+xml',
    buffer:Buffer.from(xml),
  });
  await expect(page.getByText(/Imported 1 georeferenced GIS features/)).toBeVisible();
  await page.getByText(/Attribute table/).click();
  await page.getByLabel('Attribute search field').selectOption('name');
  await page.getByLabel('Attribute search value').fill('Facility');
  await page.getByRole('button',{name:'Filter rows'}).click();
  await expect(page.getByRole('button',{name:'Facility A',exact:true})).toBeVisible();
  await page.getByLabel('Select Facility A').check();
  await page.getByLabel('Attribute property name').fill('category');
  await page.getByLabel('New attribute value').fill('warehouse');
  await page.getByRole('button',{name:'Save properties & revisions'}).click();
  await expect(page.getByText(/Updated 1 feature attributes atomically/)).toBeVisible();
});
