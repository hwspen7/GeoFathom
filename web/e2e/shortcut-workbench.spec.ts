import {test,expect} from './coverage-fixture';
import {openProjectDrawer} from './workspace-ui';
const tile=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/ZecAAAAASUVORK5CYII=','base64');
test('keyboard drawing, right-click completion, selection context and cancel',async({page})=>{
 await page.route('**/tile.openstreetmap.org/**',r=>r.fulfill({contentType:'image/png',body:tile}));
 await page.goto('/');
 const map=page.getByLabel('Interactive geospatial map');
 await expect(map).toHaveAttribute('data-label-layer-ready','true',{timeout:25000});
 const toolbar=page.getByLabel('Survey toolbar');
 const bounds=(await map.boundingBox())!;
 const x=bounds.x+bounds.width*.35,y=bounds.y+bounds.height*.4,d=Math.min(60,bounds.width*.15);
 await page.keyboard.press('g');
 await expect(toolbar.getByRole('button',{name:'Polygon',exact:true})).toHaveAttribute('aria-pressed','true');
 for(const [a,b] of [[x,y],[x+d,y],[x+d,y+d],[x,y+d]])await page.mouse.click(a,b);
 await page.mouse.click(x+5,y+5,{button:'right'});
 await expect(toolbar.getByRole('button',{name:'Finish',exact:true})).toHaveCount(0);
 await openProjectDrawer(page,'layers');
 await expect(page.getByLabel('Local drawings').getByRole('button',{name:'Polygon 1',exact:true})).toBeVisible();
 await page.mouse.click(x+d/2,y+d/2,{button:'right'});
 const menu=page.getByRole('menu',{name:'Map commands'});
 await expect(menu).toBeVisible();
 await menu.getByRole('menuitem',{name:/Move feature/}).click();
 await expect(toolbar.getByRole('button',{name:'Move',exact:true})).toHaveClass(/active/);
 await page.keyboard.press('Escape');
 await expect(toolbar.getByRole('button',{name:'Move',exact:true})).not.toHaveClass(/active/);
 await page.keyboard.press('t');
 await expect(page.getByLabel('Project and layers',{exact:true})).toBeHidden();
 await page.getByRole('button',{name:'Browse terrain tools',exact:true}).click();
 await expect(page.getByLabel('Terrain tools',{exact:true})).toBeVisible();
 await page.locator('.gis-workspace-menu > summary').click();
 await page.getByRole('button',{name:'Shortcuts',exact:true}).click();
 await expect(page.getByRole('dialog',{name:'Keyboard shortcuts'})).toBeVisible();
 await page.keyboard.press('Escape');
 await expect(page.getByRole('dialog',{name:'Keyboard shortcuts'})).toHaveCount(0);
});

// Module navigation must not detach or duplicate the global drawing controls.
test('global survey toolbar persists across all research modules',async({page})=>{
 await page.setViewportSize({width:1680,height:900});
 await page.route('**/tile.openstreetmap.org/**',r=>r.fulfill({contentType:'image/png',body:tile}));
 await page.goto('/');
 const toolbar=page.getByLabel('Survey toolbar');
 const navigation=page.getByRole('navigation',{name:'Workspace tools'});
 const names=['Point','Polygon','Line','Rectangle','Circle','Cut hole','Split line','Trace network','Vertices','Move','Edge','Snap ON','Undo','Redo','Copy'];
 await expect(toolbar.getByRole('button',{name:'Polygon',exact:true})).toBeVisible();
 const initial=await toolbar.boundingBox();
 expect(initial).not.toBeNull();
 for(const module of ['GIS','Analysis','Terrain','Spatial','Network','Temporal','LiDAR','Sensing','Raster','Mapping','Data','Export','Assistant','Survey']){
  await navigation.getByRole('button',{name:module,exact:true}).click();
  await expect(navigation.getByRole('button',{name:module,exact:true})).toHaveAttribute('aria-pressed','true');
  // Fixed side panels start directly with their content, without title bars.
  for(const panel of [page.getByLabel('Operations',{exact:true}),page.getByLabel('Results monitor',{exact:true})]){
   await expect(panel.locator(':scope > .workspace-dock-heading')).toHaveCount(0);
   await expect(panel.locator(':scope > .sidebar-scroll')).toBeVisible();
   const top=await panel.evaluate(el=>el.firstElementChild===el.querySelector(':scope > .sidebar-scroll'));
   expect(top).toBe(true);
  }
  for(const name of names){
   const tool=toolbar.getByRole('button',{name,exact:true});
   await expect(tool).toHaveCount(1);
   await expect(tool).toBeVisible();
  }
  await expect(toolbar.getByLabel('Map type')).toBeVisible();
  const bounds=await toolbar.boundingBox();
  expect(bounds).not.toBeNull();
  expect(bounds!.y).toBe(initial!.y);
  expect(bounds!.height).toBe(initial!.height);
 }
 await navigation.getByRole('button',{name:'Raster',exact:true}).click();
 await toolbar.getByRole('button',{name:'Polygon',exact:true}).click();
 await expect(toolbar.getByRole('button',{name:'Polygon',exact:true})).toHaveAttribute('aria-pressed','true');
 await expect(toolbar.getByRole('button',{name:'Cancel drawing'})).toBeVisible();
 await toolbar.getByRole('button',{name:'Cancel drawing'}).click();
 await expect(navigation.getByRole('button',{name:'Raster',exact:true})).toHaveAttribute('aria-pressed','true');
 await expect(toolbar.getByRole('button',{name:'Polygon',exact:true})).toHaveAttribute('aria-pressed','false');
});

test('GIS tools and object browser stay open without collapsible sections',async({page})=>{
 await page.setViewportSize({width:1680,height:900});
 await page.route('**/tile.openstreetmap.org/**',r=>r.fulfill({contentType:'image/png',body:tile}));
 await page.goto('/');
 const nav=page.getByRole('navigation',{name:'Workspace tools'});
 await nav.getByRole('button',{name:'GIS',exact:true}).click();
 const tools=page.getByRole('complementary',{name:'Operations'});
 await expect(tools.getByRole('heading',{name:'Objects',exact:true})).toBeVisible();
 await expect(tools.getByRole('heading',{name:/Attribute table/})).toBeVisible();
 await expect(tools.getByLabel('Attribute search field')).toBeVisible();
 await expect(tools.getByLabel('Import GIS vector file')).toBeAttached();
 await expect(tools.getByLabel('GIS export format')).toBeVisible();
 await expect(tools.getByRole('button',{name:/Analyze selected/})).toBeVisible();
 await expect(tools.locator('#tools-gis details, details.workspace-objects')).toHaveCount(0);
 await nav.getByRole('button',{name:'Survey',exact:true}).click();
 await nav.getByRole('button',{name:'GIS',exact:true}).click();
 await expect(tools.getByLabel('Attribute search field')).toBeVisible();
 await expect(tools.getByLabel('Filter project features')).toBeVisible();
});
