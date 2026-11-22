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
 await expect(page.getByLabel('DEM fetch area')).toHaveValue('viewport');
 await page.getByLabel('DEM fetch area').selectOption('selection');
 await expect(page.getByLabel('DEM download target')).toContainText('Selected geometry');
 await page.mouse.click(bounds.x+bounds.width*.90,bounds.y+bounds.height*.85);
 await expect(page.locator('.results .result.active')).toHaveCount(1);
 await expect(page.getByLabel('DEM fetch area')).toHaveValue('selection');
 await page.getByRole('button',{name:'Deselect',exact:true}).click();
 await expect(page.locator('.results .result.active')).toHaveCount(0);
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
