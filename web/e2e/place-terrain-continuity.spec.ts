import {test,expect} from './coverage-fixture';

const tile=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/ZecAAAAASUVORK5CYII=','base64');
const cmh={id:'cmh-acceptance',name:'CMH Acceptance Airport',display_name:'John Glenn Columbus Airport, Ohio',
 longitude:-82.892,latitude:39.997,bbox:[-82.917,39.979,-82.866,40.015],
 geometry:{type:'Polygon',coordinates:[[
 [-82.915,39.985],[-82.87,39.985],[-82.87,40.008],[-82.915,40.008],[-82.915,39.985]
 ]]},boundary_status:'mapped',source:'Acceptance fixture',osm_type:'way',osm_id:12345};
async function search(page:import('@playwright/test').Page,place:typeof cmh){
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
 await page.getByRole('navigation',{name:'Workspace tools'}).getByRole('button',{name:'Terrain',exact:true}).click();
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
 await expect(page.getByLabel('Pinned places').getByRole('button',{name:'Select pinned CMH Acceptance Airport'})).toBeVisible();
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
 await page.getByRole('navigation',{name:'Workspace tools'}).getByRole('button',{name:'Terrain',exact:true}).click();
 await expect(page.getByLabel('DEM fetch area')).toHaveValue('viewport');
 await expect(page.getByLabel('DEM fetch area').locator('option[value="selection"]')).toBeDisabled();
});

test('Draw profile line keeps CMH selected before and after Finish, until explicit removal',async({page})=>{
 await page.goto('/');
 const map=page.getByLabel('Interactive geospatial map');
 await expect(map).toHaveAttribute('data-label-layer-ready','true',{timeout:25000});
 await search(page,cmh);
 const toolbar=page.getByLabel('Survey toolbar');
 await page.getByRole('navigation',{name:'Workspace tools'}).getByRole('button',{name:'Terrain',exact:true}).click();
 await page.getByLabel('Terrain tools').getByRole('button',{name:'Elevation profile',exact:true}).click();
 await page.getByRole('button',{name:'Draw profile line',exact:true}).click();
 await expect(page.locator('.results .result.active')).toHaveCount(1);
 await expect(page.getByLabel('Pinned places').getByRole('button',{name:'Select pinned CMH Acceptance Airport'})).toBeVisible();
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
 await expect(page.getByLabel('Pinned places').getByRole('button',{name:'Select pinned CMH Acceptance Airport'})).toBeVisible();
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
 await page.getByRole('navigation',{name:'Workspace tools'}).getByRole('button',{name:'Terrain',exact:true}).click();
 await page.getByLabel('Terrain tools').getByRole('button',{name:'Elevation profile',exact:true}).click();
 await page.getByRole('button',{name:'Draw profile line',exact:true}).click();
 await page.getByLabel('Survey toolbar').getByRole('button',{name:'Cancel drawing',exact:true}).click();
 await expect(page.getByText('Drawing cancelled. Retained locations are unchanged.')).toBeVisible();
 await expect(page.locator('.results .result.active')).toHaveCount(1);
 await expect(page.getByLabel('Pinned places').getByRole('button',{name:'Select pinned CMH Acceptance Airport'})).toBeVisible();
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
 await page.getByRole('navigation',{name:'Workspace tools'}).getByRole('button',{name:'Terrain',exact:true}).click();
 await expect(page.getByLabel('DEM fetch area')).toHaveValue('selection');
 await expect(page.getByLabel('DEM download target')).toContainText('W -82.91540°');
});
