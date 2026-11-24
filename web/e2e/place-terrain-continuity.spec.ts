import {test,expect} from './coverage-fixture';
import {openProjectDrawer,closeProjectDrawer,activateWorkspaceModule} from './workspace-ui';

const tile=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/ZecAAAAASUVORK5CYII=','base64');
const cmh={id:'cmh-acceptance',name:'CMH Acceptance Airport',display_name:'John Glenn Columbus Airport, Ohio',
 longitude:-82.892,latitude:39.997,bbox:[-82.917,39.979,-82.866,40.015],
 geometry:{type:'Polygon',coordinates:[[
 [-82.915,39.985],[-82.87,39.985],[-82.87,40.008],[-82.915,40.008],[-82.915,39.985]
 ]]},boundary_status:'mapped',source:'Acceptance fixture',osm_type:'way',osm_id:12345};
async function search(page:import('@playwright/test').Page,place:typeof cmh){
 await openProjectDrawer(page,'search');
 await page.route('**/search?q=*',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({results:[place]})}));
 await page.getByLabel('Search for a place').fill('John Glenn Columbus Airport');
 await page.getByRole('button',{name:'Search',exact:true}).click();
 await expect(page.locator('.results .result.active')).toHaveCount(1);
}

test.beforeEach(async({page})=>{
 await page.route('**/tile.openstreetmap.org/**',route=>route.fulfill({contentType:'image/png',body:tile}));
});

test('CMH Find a place remains selected across map clicks and Terrain activation',async({page})=>{
 await page.goto('/');
 const map=page.getByLabel('Interactive geospatial map');
 await expect(map).toHaveAttribute('data-label-layer-ready','true',{timeout:25000});
 await search(page,cmh);
 await expect(page.getByText('Mapped boundary loaded. Check that it represents your intended area.')).toBeVisible();
 // An ordinary click outside the shape must not cancel the location selection.
 const bounds=(await map.boundingBox())!;
 await page.mouse.click(bounds.x+bounds.width*.08,bounds.y+bounds.height*.12);
 await expect(page.locator('.results .result.active')).toHaveCount(1);
 await activateWorkspaceModule(page,'Terrain');
 await expect(page.getByLabel('DEM fetch area')).toHaveValue('selection');
 await expect(page.getByLabel('DEM download target')).toContainText('Selected geometry');
 await page.getByLabel('DEM fetch area').selectOption('viewport');
 await expect(page.getByLabel('DEM download target')).toContainText('Current map');
 await page.getByRole('button',{name:'Use selected area'}).click();
 await expect(page.getByLabel('DEM fetch area')).toHaveValue('selection');
 await page.mouse.click(bounds.x+bounds.width*.90,bounds.y+bounds.height*.85);
 await expect(page.locator('.results .result.active')).toHaveCount(1);
 await expect(page.getByLabel('DEM fetch area')).toHaveValue('selection');
 await page.getByRole('button',{name:'Deselect',exact:true}).click();
 await expect(page.locator('.results .result.active')).toHaveCount(0);
 await openProjectDrawer(page,'search');
 await expect(page.getByLabel('Pinned places').getByRole('button',{name:'Select pinned CMH Acceptance Airport'})).toBeVisible();
 await closeProjectDrawer(page);
});

test('point-only airport search result stays selected and cannot masquerade as area',async({page})=>{
 await page.goto('/');
 const map=page.getByLabel('Interactive geospatial map');
 await expect(map).toHaveAttribute('data-label-layer-ready','true',{timeout:25000});
 await search(page,{...cmh,geometry:{type:'Point',coordinates:[-82.892,39.997]} as unknown as typeof cmh.geometry,boundary_status:'location_only'});
 await expect(page.getByText(/Location selected \(point only\)/)).toBeVisible();
 const bounds=(await map.boundingBox())!;
 await page.mouse.click(bounds.x+bounds.width*.15,bounds.y+bounds.height*.15);
 await expect(page.locator('.results .result.active')).toHaveCount(1);
 await activateWorkspaceModule(page,'Terrain');
 await expect(page.getByLabel('DEM fetch area')).toHaveValue('viewport');
 await expect(page.getByLabel('DEM fetch area').locator('option[value="selection"]')).toBeDisabled();
});

test('Draw profile line keeps CMH selected before and after Finish, until explicit removal',async({page})=>{
 await page.goto('/');
 const map=page.getByLabel('Interactive geospatial map');
 await expect(map).toHaveAttribute('data-label-layer-ready','true',{timeout:25000});
 await search(page,cmh);
 const toolbar=page.getByLabel('Survey toolbar');
 await activateWorkspaceModule(page,'Terrain');
 await page.getByRole('button',{name:'Browse terrain tools',exact:true}).click();
 await page.getByLabel('Terrain tools',{exact:true}).getByRole('button',{name:'Elevation profile',exact:true}).click();
 await page.getByRole('button',{name:'Draw profile line',exact:true}).click();
 await expect(page.locator('.results .result.active')).toHaveCount(1);
 await openProjectDrawer(page,'search');
 await expect(page.getByLabel('Pinned places').getByRole('button',{name:'Select pinned CMH Acceptance Airport'})).toBeVisible();
 await closeProjectDrawer(page);
 const rect=(await map.boundingBox())!;
 const x=rect.x+rect.width*.43,y=rect.y+rect.height*.52;
 await page.mouse.click(x,y);
 await page.mouse.click(x+Math.min(100,rect.width*.12),y);
 await toolbar.getByRole('button',{name:'Finish',exact:true}).click();
 await expect(page.getByText('Profile line ready. Your selected study area remains unchanged.')).toBeVisible();
 await expect(page.getByText('✓ Independent profile line')).toBeVisible();
 await expect(page.locator('.results .result.active')).toHaveCount(1);
 await expect(page.getByRole('button',{name:'Remove profile line'})).toBeVisible();
 await page.reload();
 await openProjectDrawer(page,'search');
 await expect(page.getByLabel('Pinned places').getByRole('button',{name:'Select pinned CMH Acceptance Airport'})).toBeVisible();
 await closeProjectDrawer(page);
 await openProjectDrawer(page,'search');
  await page.getByLabel('Pinned places').getByRole('button',{name:'Remove pinned CMH Acceptance Airport'}).click();
 await expect(page.getByLabel('Pinned places')).toHaveCount(0);
});

test('general survey drawing does not delete the selected airport region',async({page})=>{
 await page.goto('/');
 const map=page.getByLabel('Interactive geospatial map');
 await expect(map).toHaveAttribute('data-label-layer-ready','true',{timeout:25000});
 await search(page,cmh);
 const retained=page.getByLabel('Pinned places').getByRole('button',{name:'Select pinned CMH Acceptance Airport'});
 await expect(retained).toBeVisible();
 const toolbar=page.getByLabel('Survey toolbar');
 await toolbar.getByRole('button',{name:'Polygon',exact:true}).click();
 await expect(page.locator('.results .result.active')).toHaveCount(1);
 await expect(retained).toBeVisible();
 const box=(await map.boundingBox())!;
 const x=box.x+box.width*.43,y=box.y+box.height*.47,d=Math.min(45,box.width*.08,box.height*.08);
 for(const [px,py] of [[x,y],[x+d,y],[x+d,y+d],[x,y+d]])await page.mouse.click(px,py);
 await toolbar.getByRole('button',{name:'Finish',exact:true}).click();
 await expect(page.getByText(/Drawing completed and measured/)).toBeVisible();
 await expect(retained).toBeVisible();
 await retained.click();
 await expect(page.locator('.results .result.active')).toHaveCount(1);
 await page.getByRole('button',{name:'Deselect',exact:true}).click();
 await expect(retained).toBeVisible();
});

test('Cancel stops an independent profile drawing without discarding CMH',async({page})=>{
 await page.goto('/');
 const map=page.getByLabel('Interactive geospatial map');
 await expect(map).toHaveAttribute('data-label-layer-ready','true',{timeout:25000});
 await search(page,cmh);
 await activateWorkspaceModule(page,'Terrain');
 await page.getByRole('button',{name:'Browse terrain tools',exact:true}).click();
 await page.getByLabel('Terrain tools',{exact:true}).getByRole('button',{name:'Elevation profile',exact:true}).click();
 await page.getByRole('button',{name:'Draw profile line',exact:true}).click();
 await page.getByLabel('Survey toolbar').getByRole('button',{name:'Cancel drawing',exact:true}).click();
 await expect(page.getByText('Drawing cancelled. Retained locations are unchanged.')).toBeVisible();
 await expect(page.locator('.results .result.active')).toHaveCount(1);
 await openProjectDrawer(page,'search');
 await expect(page.getByLabel('Pinned places').getByRole('button',{name:'Select pinned CMH Acceptance Airport'})).toBeVisible();
 await closeProjectDrawer(page);
});

test('search centers on true selected campus outline, not unrelated broad search bbox',async({page})=>{
 await page.goto('/');
 const map=page.getByLabel('Interactive geospatial map');
 await expect(map).toHaveAttribute('data-label-layer-ready','true',{timeout:25000});
 await search(page,{...cmh,bbox:[-84,41,-83,42]});
 await expect.poll(async()=>{
   const raw=await map.getAttribute('data-map-center');
   const center=raw?JSON.parse(raw) as number[]:[];
   return center.length===2&&Math.abs(center[0]+82.8925)<.02&&Math.abs(center[1]-39.9965)<.02;
 },{timeout:20000}).toBe(true);
 await activateWorkspaceModule(page,'Terrain');
 await expect(page.getByLabel('DEM fetch area')).toHaveValue('selection');
 await expect(page.getByLabel('DEM download target')).toContainText('W -82.91540°');
});

test('frontend exposes actual build revision in Settings for stale-process diagnosis',async({page})=>{
 await page.goto('/');
 await page.locator('.gis-settings > summary').click();
 await expect(page.getByLabel('Build revision')).toContainText(/Frontend revision [0-9a-f]{7,}/);
});

test('OSU disconnected mapped properties default to campus, with inspectable editable nodes',async({page})=>{
 await page.goto('/');
 const map=page.getByLabel('Interactive geospatial map');
 await expect(map).toHaveAttribute('data-label-layer-ready','true',{timeout:25000});
 const osu={...cmh,id:'osu-campus-test',name:'The Ohio State University',
  longitude:-83.023,latitude:40.001,bbox:[-83.09,39.985,-83.002,40.078],
  geometry:{type:'MultiPolygon',coordinates:[
    [[[-83.045,39.990],[-83.010,39.990],[-83.010,40.012],[-83.045,40.012],[-83.045,39.990]]],
    [[[-83.080,40.070],[-83.060,40.070],[-83.060,40.076],[-83.080,40.076],[-83.080,40.070]]],
  ]}} as unknown as typeof cmh;
 await search(page,osu);
 await expect(page.getByLabel('Study area parcel')).toHaveValue('0');
 await openProjectDrawer(page,'search');
 await expect(page.getByLabel('Pinned places').getByRole('button',{name:'Select pinned The Ohio State University'})).toBeVisible();
 await closeProjectDrawer(page);
 await activateWorkspaceModule(page,'Terrain');
 await expect(page.getByLabel('DEM fetch area')).toHaveValue('selection');
 await expect(page.getByLabel('DEM download target')).toContainText('N 40.01240°');
 await page.locator('.workspace-objects > summary').click();
 await page.getByText('Geometry / vertices',{exact:true}).click();
 await page.getByLabel('Study area parcel').selectOption('all');
 await expect(page.getByLabel('DEM download target')).toContainText('N 40.07640°');
 await page.getByLabel('Study area parcel').selectOption('0');
 await expect(page.getByLabel('DEM download target')).toContainText('N 40.01240°');
 // Reproduce an ordinary user workflow with the floating legend open.
 // Entering edit mode must make every actual geometry handle clickable.
 // The normal map, survey and cartography workflows keep the legend visible.
 await expect(page.locator('.map-legend-items')).toBeVisible();
 await page.getByRole('button',{name:'Edit boundary nodes'}).click();
 await expect(page.locator('.map-legend-items')).toHaveCount(0);
 await expect.poll(async()=>{
  const raw=await map.getAttribute('data-edit-handle-pixels');
  return raw?JSON.parse(raw).length:0;
 },{timeout:18000}).toBeGreaterThan(3);
 await expect(page.getByLabel('Boundary longitude')).toHaveValue('-83.0450000');
 // Wait for MapLibre's worker and the animated camera to settle before
 // reading a projected handle position. Cached geometry alone can be stale.
 await expect.poll(async()=>{
  const raw=await map.getAttribute('data-rendered-handle-pixels');
  return raw?JSON.parse(raw).length:0;
 },{timeout:18000}).toBeGreaterThan(3);
 // Projected handle locations become actionable only when fitBounds has
 // fully stopped and the latest workspace GeoJSON frame has rendered.
 await expect(map).toHaveAttribute('data-map-camera-stable','true',{timeout:18000});
 const pixels=JSON.parse((await map.getAttribute('data-edit-handle-pixels'))||'[]') as number[][];
 expect(pixels.length).toBeGreaterThan(3);
 const rect=(await map.boundingBox())!;
 // All geometry edit handles must remain directly accessible. A floating
 // map overlay must not intercept pointer events intended for a vertex.
 await expect(page.getByRole('button',{name:'Toggle map legend'})).toBeDisabled();
 const x=rect.x+pixels[2][0],y=rect.y+pixels[2][1];
 const pointerTarget=await page.evaluate(({x,y})=>{
   const element=document.elementFromPoint(x,y);
   return {inMap:Boolean(element?.closest('.map-canvas')),
     tag:element?.tagName??'none',classes:element?.className?.toString()??'none'};
 },{x,y});
 expect(pointerTarget.inMap,JSON.stringify({x,y,pointerTarget})).toBe(true);
 await page.mouse.click(x,y);
 // The geometry inspector must receive the *real* native pointer event.
 // This distinguishes a covered node from React selection propagation.
 await expect(map).toHaveAttribute('data-edit-native-hit',JSON.stringify({polygon:0,ring:0,vertex:2}));
 await expect(page.getByLabel('Boundary node',{exact:true})).toHaveValue('2');
 // Selecting (without dragging) must not silently create an edited local copy
 // or discard the original geocoded campus parcel.
 await expect(page.getByLabel('Study area parcel')).toHaveValue('0');
 await openProjectDrawer(page,'search');
 await expect(page.getByLabel('Pinned places').getByRole('button',{name:'Select pinned The Ohio State University'})).toBeVisible();
 await closeProjectDrawer(page);
 await page.getByLabel('Boundary node',{exact:true}).selectOption('1');
 await expect(page.getByLabel('Boundary longitude')).toHaveValue('-83.0100000');
 await page.getByLabel('Boundary longitude').fill('-83.0105');
 await page.getByRole('button',{name:'Apply coordinates'}).click();
 await expect.poll(async()=>await page.getByLabel('Boundary longitude').inputValue(),
  {timeout:18000}).toBe('-83.0105000');
 await openProjectDrawer(page,'search');
 await expect(page.getByLabel('Pinned places').getByRole('button',{name:'Select pinned The Ohio State University'})).toBeVisible();
 await closeProjectDrawer(page);
 await expect(page.getByLabel('DEM download target')).toContainText('N 40.01240°');
 // Editing temporarily hides the legend but must retain the user's
 // expanded/collapsed preference when editing ends.
 await page.getByRole('button',{name:'Edit boundary nodes'}).click();
 await expect(page.getByRole('button',{name:'Toggle map legend'})).toBeEnabled();
 await expect(page.locator('.map-legend-items')).toBeVisible();
 await page.getByRole('button',{name:'Back to terrain tools',exact:true}).click();
 await expect(page.getByLabel('DEM download target')).toBeVisible();
});

test('Hong Kong airport area uses global DEM provider and stays within enlarged budget',async({page})=>{
 await page.goto('/');
 const map=page.getByLabel('Interactive geospatial map');
 await expect(map).toHaveAttribute('data-label-layer-ready','true',{timeout:25000});
 const hkg={...cmh,id:'hkg-acceptance',name:'Hong Kong airport study area',
   longitude:113.92,latitude:22.31,bbox:[113.87,22.27,113.99,22.36],
   geometry:{type:'Polygon',coordinates:[[
     [113.885,22.275],[113.965,22.275],[113.965,22.345],
     [113.885,22.345],[113.885,22.275],
   ]]}};
 await search(page,hkg);
 await activateWorkspaceModule(page,'Terrain');
 await expect(page.getByLabel('DEM fetch area')).toHaveValue('selection');
 await expect(page.getByLabel('Public DEM resolution')).toHaveValue('30');
 await expect(page.getByLabel('Public DEM resolution').locator('option[value="1"]')).toBeDisabled();
 await expect(page.getByLabel('Public DEM resolution').locator('option[value="3"]')).toBeDisabled();
 await expect(page.getByLabel('Public DEM resolution').locator('option[value="10"]')).toBeDisabled();
 await expect(page.getByLabel('DEM download target')).toContainText('Selected geometry');
 await expect(page.getByRole('button',{name:'Auto-fit DEM resolution'})).toContainText('30 m');
 await expect(page.getByLabel('DEM source coverage',{exact:true})).toContainText('Copernicus global');
 await expect(page.getByText(/8-million-cell.*budget/)).toHaveCount(0);
 await openProjectDrawer(page,'search');
 await expect(page.getByLabel('Pinned places').getByRole('button',{name:'Select pinned Hong Kong airport study area'})).toBeVisible();
 await closeProjectDrawer(page);
});

test('large US university footprint automatically finds usable 3 m grid without deleting boundaries',async({page})=>{
 await page.goto('/');
 const map=page.getByLabel('Interactive geospatial map');
 await expect(map).toHaveAttribute('data-label-layer-ready','true',{timeout:25000});
 const large={...cmh,id:'large-campus-acceptance',name:'Large Campus Acceptance',
   longitude:-83.018,latitude:40.01,bbox:[-83.05,39.98,-82.984,40.036],
   geometry:{type:'Polygon',coordinates:[[
     [-83.05,39.98],[-82.984,39.98],[-82.984,40.036],
     [-83.05,40.036],[-83.05,39.98],
   ]]}};
 await search(page,large);
 await activateWorkspaceModule(page,'Terrain');
 await page.getByLabel('Public DEM resolution').selectOption('1');
 await expect(page.getByRole('alert')).toContainText('8-million-cell');
 await expect(page.getByRole('button',{name:'Fetch DEM'})).toBeDisabled();
 await page.getByRole('button',{name:'Auto-fit DEM resolution'}).click();
 await expect(page.getByLabel('Public DEM resolution')).toHaveValue('3');
 await expect(page.getByRole('button',{name:'Fetch DEM'})).toBeEnabled();
 await expect(page.getByLabel('DEM download target')).toContainText('Selected geometry');
 await openProjectDrawer(page,'search');
 await expect(page.getByLabel('Pinned places').getByRole('button',{name:'Select pinned Large Campus Acceptance'})).toBeVisible();
 await closeProjectDrawer(page);
});
