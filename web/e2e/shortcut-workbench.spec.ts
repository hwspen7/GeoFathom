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
   await expect(panel.locator(':scope > .sidebar-scroll')).toBeAttached();
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
 const map=page.getByLabel('Interactive geospatial map');
 await expect(map).toHaveAttribute('data-label-layer-ready','true',{timeout:25000});
 const box=(await map.boundingBox())!;
 await page.getByLabel('Survey toolbar').getByRole('button',{name:'Polygon',exact:true}).click();
 for(const [x,y] of [[.35,.35],[.45,.35],[.45,.45],[.35,.45]])await page.mouse.click(box.x+x*box.width,box.y+y*box.height);
 await page.keyboard.press('Enter');
 await expect(tools.getByLabel('Boundary longitude')).toBeVisible();
 await expect(tools.locator('.compact-object-row')).toHaveCount(1);
 const legend=page.getByLabel('Map legend',{exact:true});
 await expect(legend).toContainText('Polygon 1');
 await expect(legend).not.toContainText('Local drawings ·');
 const object=tools.getByRole('group',{name:'Object Polygon 1'});
 const rowBefore=(await object.boundingBox())!;
 await object.getByRole('button',{name:'Rename object'}).click();
 await expect(object.getByRole('button',{name:'Cancel rename'})).toBeVisible();
 const rowDuring=(await object.boundingBox())!;
 expect(rowDuring.height).toBeLessThanOrEqual(rowBefore.height+2);
 await object.getByLabel('Object name').fill('Area 1');
 await object.getByRole('button',{name:'Save name'}).click();
 await expect(legend).toContainText('Area 1');
 await expect(legend).not.toContainText('Polygon 1');
 // Every object appears only once, and navigation uses the same compact list.
 for(const module of ['Survey','Analysis','Spatial','Network','Temporal','LiDAR','Sensing','Raster','Mapping','Assistant']){
  await nav.getByRole('button',{name:module,exact:true}).click();
  await expect(tools.locator('.compact-object-row').filter({hasText:'Area 1'})).toBeVisible();
 }
 await nav.getByRole('button',{name:'GIS',exact:true}).click();
 for(const [width,height] of [[1680,900],[1280,720]]){
  await page.setViewportSize({width,height});
  await expect(tools.getByRole('button',{name:/Analyze selected/})).toBeInViewport({ratio:1});
  await expect(tools.getByLabel('GIS export format')).toBeInViewport({ratio:1});
  await expect(tools.getByLabel('Boundary longitude')).toBeInViewport({ratio:1});
  const region=tools.locator('.workspace-module-content');
  await expect.poll(()=>region.evaluate(e=>e.scrollHeight-e.clientHeight)).toBeLessThanOrEqual(1);
 }
});

test('empty results dock releases map width and returns only when results exist',async({page})=>{
 await page.setViewportSize({width:1680,height:900});
 await page.route('**/tile.openstreetmap.org/**',r=>r.fulfill({contentType:'image/png',body:tile}));
 await page.goto('/');
 const nav=page.getByRole('navigation',{name:'Workspace tools'});
 const monitor=page.getByLabel('Results monitor',{exact:true});
 const map=page.getByLabel('Interactive geospatial map');
 await nav.getByRole('button',{name:'LiDAR',exact:true}).click();
 await expect(monitor).toBeHidden();
 const wide=(await map.boundingBox())!.width;
 await nav.getByRole('button',{name:'Survey',exact:true}).click();
 await expect(monitor).toBeHidden();
 await expect(map).toHaveAttribute('data-label-layer-ready','true',{timeout:25000});
 const box=(await map.boundingBox())!;
 await page.getByLabel('Survey toolbar').getByRole('button',{name:'Polygon',exact:true}).click();
 for(const [x,y] of [[.25,.35],[.35,.35],[.35,.45],[.25,.45]])await page.mouse.click(box.x+x*box.width,box.y+y*box.height);
 await page.keyboard.press('Enter');
 await expect(monitor).toBeVisible();
 await expect.poll(async()=>Math.round((await map.boundingBox())!.width)).toBeLessThan(Math.round(wide)-200);
 await nav.getByRole('button',{name:'LiDAR',exact:true}).click();
 await expect(monitor).toBeHidden();
 await expect.poll(async()=>Math.round((await map.boundingBox())!.width)).toBe(Math.round(wide));
 await nav.getByRole('button',{name:'Survey',exact:true}).click();
 await expect(monitor).toBeVisible();
 await page.getByLabel('Survey toolbar').getByRole('button',{name:'Deselect',exact:true}).click();
 await expect(monitor).toBeHidden();
});

test('Survey uses flat compact sections and keeps every construction control accessible',async({page})=>{
 await page.setViewportSize({width:1280,height:720});
 await page.route('**/tile.openstreetmap.org/**',r=>r.fulfill({contentType:'image/png',body:tile}));
 await page.goto('/');
 await page.getByRole('navigation',{name:'Workspace tools'}).getByRole('button',{name:'Survey',exact:true}).click();
 const survey=page.locator('#tools-survey');
 await expect(survey.locator('details,summary')).toHaveCount(0);
 await expect(survey.locator('.survey-workflow-hint,.survey-vertex-help,.survey-main-heading')).toHaveCount(0);
 await expect(survey.getByRole('heading',{name:'Vertices',exact:true})).toBeVisible();
 await expect(survey.getByRole('heading',{name:'Construction',exact:true})).toBeVisible();
 const controlHeight=await survey.getByLabel('Numeric construction mode').evaluate(el=>el.getBoundingClientRect().height);
 expect(controlHeight).toBeGreaterThanOrEqual(26);
 expect(controlHeight).toBeLessThanOrEqual(32);
 await expect(survey.getByRole('checkbox')).toBeVisible();
 await expect(survey.getByLabel('Numeric construction mode')).toBeVisible();
 await expect(survey.getByRole('button',{name:'Apply exact geometry'})).toBeInViewport({ratio:1});
 await expect(survey.getByRole('button',{name:'Intersect'})).toBeInViewport({ratio:1});
 for(const mode of ['rectangle','circle','bearing','point']){
  await survey.getByLabel('Numeric construction mode').selectOption(mode);
  if(mode==='rectangle')await expect(survey.getByLabel('Opposite longitude')).toBeVisible();
  if(mode==='circle'||mode==='bearing')await expect(survey.getByLabel('Radius or length in meters')).toBeVisible();
  if(mode==='bearing')await expect(survey.getByLabel('Bearing in degrees')).toBeVisible();
  await expect(survey.getByRole('button',{name:'Intersect'})).toBeInViewport({ratio:1});
 }
 await expect(survey.getByRole('button',{name:'Union'})).toBeDisabled();
});

test('Analysis has flat sections and the same persistent Objects host',async({page})=>{
 await page.setViewportSize({width:1680,height:900});
 await page.route('**/tile.openstreetmap.org/**',r=>r.fulfill({contentType:'image/png',body:tile}));
 await page.goto('/');
 const nav=page.getByRole('navigation',{name:'Workspace tools'});
 const objects=page.locator('.workspace-objects');
 const filter=objects.getByLabel('Filter project features');
 await filter.fill('persistent search');
 const before=await objects.boundingBox();
 await filter.evaluate(el=>el.setAttribute('data-test-persistent-host','true'));
 for(const name of ['GIS','Analysis','Terrain','Spatial','Network','Temporal','LiDAR','Sensing','Raster','Mapping','Assistant','Survey']){
  await nav.getByRole('button',{name,exact:true}).click();
  await expect(filter).toHaveValue('persistent search');
  await expect(filter).toHaveAttribute('data-test-persistent-host','true');
  const current=(await objects.boundingBox())!;
  expect(Math.abs(current.y-before!.y)).toBeLessThanOrEqual(1);
  expect(Math.abs(current.x-before!.x)).toBeLessThanOrEqual(1);
  expect(Math.abs(current.height-before!.height)).toBeLessThanOrEqual(1);
 }
 await filter.fill('');
 await nav.getByRole('button',{name:'Analysis',exact:true}).click();
 const analysis=page.locator('#tools-spatial');
 await expect(analysis.locator('details,summary')).toHaveCount(0);
 for(const label of ['Buffer distance','Selection area mode','Topology threshold','PDF map title','PDF paper','PDF orientation','PDF extent'])
  await expect(analysis.getByLabel(label,{exact:true})).toBeVisible();
 await expect(analysis.getByRole('button',{name:'Export vector PDF'})).toBeInViewport({ratio:1});
});

test('Survey GIS and Analysis use icons and fixed non-scrolling tools',async({page})=>{
 await page.setViewportSize({width:1680,height:900});
 await page.route('**/tile.openstreetmap.org/**',r=>r.fulfill({contentType:'image/png',body:tile}));
 await page.goto('/');
 const nav=page.getByRole('navigation',{name:'Workspace tools'});
 const tools=page.getByRole('complementary',{name:'Operations'});
 const map=page.getByLabel('Interactive geospatial map');
 await expect(map).toHaveAttribute('data-label-layer-ready','true',{timeout:25000});
 const box=(await map.boundingBox())!;
 await page.getByLabel('Survey toolbar').getByRole('button',{name:'Polygon',exact:true}).click();
 for(const [x,y] of [[.35,.35],[.45,.35],[.45,.45],[.35,.45]])await page.mouse.click(box.x+x*box.width,box.y+y*box.height);
 await page.keyboard.press('Enter');
 for(const [width,height] of [[1680,900],[1280,720]]){
  await page.setViewportSize({width,height});
  for(const [name,id,action] of [['Survey','tools-survey','Intersect'],['GIS','tools-gis','Analyze selected terrain area'],['Analysis','tools-spatial','Export vector PDF']]){
   await nav.getByRole('button',{name,exact:true}).click();
   const panel=tools.locator('#'+id);
   await expect(panel).toBeVisible();
   const headings=tools.locator('.gis-static-heading,.compact-boundary-heading,#'+id+' h3');
   expect(await headings.evaluateAll(els=>els.every(el=>!!el.querySelector('svg')))).toBe(true);
   await expect(panel.getByRole('button',{name:action,exact:true})).toBeInViewport({ratio:1});
   const content=tools.locator('.workspace-module-content');
   await expect.poll(()=>content.evaluate(el=>el.scrollHeight-el.clientHeight)).toBeLessThanOrEqual(1);
   const before=await panel.boundingBox();
   await content.hover();
   await page.mouse.wheel(0,650);
   await expect.poll(()=>content.evaluate(el=>el.scrollTop)).toBe(0);
   expect((await panel.boundingBox())!.y).toBe(before!.y);
  }
 }
});
