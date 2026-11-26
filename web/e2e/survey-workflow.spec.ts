import {test,expect} from './coverage-fixture';
import type {Page} from '@playwright/test';
import {openFileMenu,activateWorkspaceModule} from './workspace-ui';

const API='http://127.0.0.1:8000';
const tile=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/ZecAAAAASUVORK5CYII=','base64');
const polygon={type:'Polygon',coordinates:[[[118.05,24.4],[118.15,24.4],[118.15,24.5],[118.05,24.5],[118.05,24.4]]]};
async function setup(page:Page){
 await page.route('**/tile.openstreetmap.org/**',r=>r.fulfill({contentType:'image/png',body:tile}));
 const created=await page.request.post(API+'/projects',{data:{name:'Survey usability '+Date.now()+' '+Math.random()}});
 expect(created.status()).toBe(201);
 const project=(await created.json()).id as string;
 const ids:string[]=[];
 for(const name of ['厦门岛','Polygon 1']){
  const response=await page.request.post(`${API}/projects/${project}/features`,{data:{name,geometry:polygon,source:'Usability fixture'}});
  expect(response.status()).toBe(201);ids.push((await response.json()).id);
 }
 await page.goto('/');
 await expect(page.getByLabel('Active project').locator(`option[value="${project}"]`)).toHaveCount(1);
 await page.getByLabel('Active project').selectOption(project);
 await page.getByRole('button',{name:'厦门岛',exact:true}).click();
 const map=page.getByLabel('Interactive geospatial map');
 await expect(map).toHaveAttribute('data-label-layer-ready','true',{timeout:25000});
 const toolbar=page.getByLabel('Survey toolbar');
 // Handle diagnostics certify the fitted camera only while vertex editing
 // is active. Follow that real UI transition instead of waiting in pan mode.
 await toolbar.getByRole('button',{name:'Vertices',exact:true}).click();
 await expect(map).toHaveAttribute('data-map-camera-stable','true');
 await page.keyboard.press('Enter');
 await expect(toolbar.getByRole('button',{name:'Vertices',exact:true})).not.toHaveClass(/active/);
 return {project,ids,map,toolbar};
}
async function points(page:Page){
 const bounds=(await page.getByLabel('Interactive geospatial map').boundingBox())!;
 const x=bounds.x+bounds.width/2,y=bounds.y+bounds.height/2;
 return [[x-28,y-28],[x+28,y-28],[x+28,y+28],[x-28,y+28]];
}
for(const width of [1100,1280,1600])test(`drawing exits and error recovery stay on screen at ${width}px`,async({page},testInfo)=>{
 await page.setViewportSize({width,height:760});
 const {toolbar,map}=await setup(page);
 await expect(page.getByLabel('Object count')).toBeVisible();
 const inspector=page.getByRole('region',{name:'Measurement results'});
 await expect(inspector).toBeVisible();
 await expect(inspector.locator('.measurement-object-name')).toHaveText('厦门岛');
 await expect(inspector.locator('.measurement-primary strong')).toBeVisible();
 await expect(inspector.locator('.measurement-perimeter strong')).toBeVisible();
 await expect(inspector.getByText('Method',{exact:true})).toHaveCount(0);
 await expect(inspector.getByText('Source',{exact:true})).toHaveCount(0);
 const styles=await inspector.locator('.measurement-metric-grid .metric').evaluateAll(nodes=>nodes.map(node=>{
   const card=getComputedStyle(node),value=getComputedStyle(node.querySelector('strong')!);
   return [card.flexDirection,card.alignItems,card.backgroundColor,card.padding,value.fontSize,value.fontWeight];
 }));
 expect(styles).toHaveLength(2);
 expect(styles[0]).toEqual(styles[1]);
 await expect(inspector.locator('.edge-measurements summary')).toContainText('segments');
 await inspector.locator('.edge-measurements summary').click();
 const edge=inspector.getByRole('button',{name:'Edge 1',exact:true});
 await edge.click();
 await expect(edge).toHaveAttribute('aria-pressed','true');
 await expect(map).toHaveAttribute('data-selected-measurement-edge','1');
 await expect(page.locator('.map-edge-selected')).toHaveCSS('background-color','rgba(0, 0, 0, 0)');
 // Clicking the map releases the measurement selection, not the study object.
 const edgeMapBox=(await map.boundingBox())!;
 await map.click({position:{x:12,y:Math.round(edgeMapBox.height/2)}});
 await expect(map).toHaveAttribute('data-selected-measurement-edge','');
 await expect(edge).toHaveAttribute('aria-pressed','false');
 await expect(inspector.locator('.measurement-primary strong')).toBeVisible();
 await expect(page.locator('.maplibregl-ctrl-group').first()).toHaveCSS('background-color','rgba(0, 0, 0, 0)');
 await inspector.locator('.edge-measurements summary').click();
 await page.screenshot({path:testInfo.outputPath('survey-objects-'+width+'.png')});
 // The map ends above the dedicated status row; dock footers do not overlap it.
 const chrome=await toolbar.boundingBox();
 const mapBox=await map.boundingBox();
 const statusBox=await page.locator('.gis-status').boundingBox();
 const bodyBox=await page.locator('.gis-body').boundingBox();
 expect(chrome).not.toBeNull();
 expect(mapBox).not.toBeNull();
 expect(statusBox).not.toBeNull();
 expect(bodyBox).not.toBeNull();
 expect(chrome!.height).toBeLessThanOrEqual(width<=1250?75:46);
 expect(chrome!.y+chrome!.height).toBeLessThanOrEqual(mapBox!.y+1);
 expect(bodyBox!.y+bodyBox!.height).toBeLessThanOrEqual(statusBox!.y+1);
 expect(statusBox!.y+statusBox!.height).toBeLessThanOrEqual(761);
 for(const footer of await page.locator('.gis-operations > .workspace-fixed-footer:not(:empty), .gis-results-monitor > .workspace-fixed-footer:not(:empty)').all()){
  if(!await footer.isVisible())continue;
  const bounds=(await footer.boundingBox())!;
  expect(bounds.y+bounds.height).toBeLessThanOrEqual(statusBox!.y+1);
 }

 // The compact toolbar must remain distinguishable even without captions.
 const split=toolbar.getByRole('button',{name:'Split line',exact:true});
 const trace=toolbar.getByRole('button',{name:'Trace network',exact:true});
 await expect(split.locator('svg.lucide-split')).toHaveCount(1);
 await expect(toolbar.getByRole('button',{name:'Cut edge',exact:true}).locator('svg.lucide-scissors')).toHaveCount(1);
 await expect(trace.locator('svg.lucide-route')).toHaveCount(1);
 await expect(split).toHaveAttribute('title','Split polygon by line');
 await expect(trace).toHaveAttribute('title','Save a vector line first');
 for(const name of ['Point','Polygon','Line','Rectangle','Circle','Cut hole','Split line']){
  const tool=toolbar.getByRole('button',{name,exact:true});
  await tool.click();
  await expect(tool).toHaveAttribute('aria-pressed','true');
  await expect(toolbar.getByRole('button',{name:'Cancel drawing'})).toBeInViewport();
  const top=(await toolbar.boundingBox())!,bottom=(await map.boundingBox())!;
  for(const button of await toolbar.getByRole('button').all())if(await button.isVisible()){
   const box=(await button.boundingBox())!;
   expect(box.y).toBeGreaterThanOrEqual(top.y);
   expect(box.y+box.height).toBeLessThanOrEqual(top.y+top.height+1);
   expect(box.x+box.width).toBeLessThanOrEqual(width);
  }
  expect(top.y+top.height).toBeLessThanOrEqual(bottom.y+1);
  await tool.click();
  await expect(tool).toHaveAttribute('aria-pressed','false');
 }
 await toolbar.getByRole('button',{name:'Cut hole',exact:true}).click();
 await page.keyboard.press('Enter');
 await expect(toolbar.getByRole('group',{name:'Active drawing'})).toHaveCount(0);
 await toolbar.getByRole('button',{name:'Cut hole',exact:true}).click();
 const [first]=await points(page);await page.mouse.click(first[0],first[1]);
 await page.keyboard.press('Enter');
 await expect(toolbar.getByRole('alert')).toContainText('more point');
 await expect(toolbar.getByRole('button',{name:'Cancel drawing'})).toBeInViewport();
 await toolbar.getByRole('button',{name:'Cancel drawing'}).click();
 await expect(toolbar.getByRole('alert')).toHaveCount(0);
 await expect(page.getByRole('button',{name:'厦门岛',exact:true})).toHaveAttribute('aria-pressed','true');
 const metric=page.locator('.results-summary .metric:not(.secondary) strong');
 const original=await metric.textContent();
 await toolbar.getByRole('button',{name:'Cut hole',exact:true}).click();
 // Use exact WGS84 vertices outside the selected Xiamen polygon rather
 // than pixels near the viewport edge: screen positions are not geography.
 // This validates the server's actual hole containment check at all widths.
 const numeric=page.locator('details.survey-options').filter({hasText:'Exact coordinates and construction'});
 if(!(await numeric.getAttribute('open')))await numeric.locator('summary').click();
 for(const [longitude,latitude] of [[120,25],[120.01,25],[120.01,25.01],[120,25.01]]){
  await numeric.getByLabel('Longitude',{exact:true}).fill(String(longitude));
  await numeric.getByLabel('Latitude',{exact:true}).fill(String(latitude));
  await numeric.getByRole('button',{name:'Add precise vertex'}).click();
 }
 await expect(toolbar.getByText('4 pts')).toBeVisible();
 await page.keyboard.press('Enter');
 await expect(toolbar.getByRole('alert')).toContainText('strictly inside');
 await expect(toolbar.getByRole('button',{name:'Cancel drawing'})).toBeInViewport();
 await page.screenshot({path:testInfo.outputPath('survey-recovery-'+width+'.png')});
 await toolbar.getByRole('button',{name:'Cancel drawing'}).click();
 await expect(metric).toHaveText(original!);
});

test('splitting a polygon produces independent selectable objects and exits the tool',async({page})=>{
 const {toolbar,map}=await setup(page);
 await toolbar.getByRole('button',{name:'Split line',exact:true}).click();
 const bounds=(await map.boundingBox())!;
 await page.mouse.click(bounds.x+30,bounds.y+bounds.height/2);
 await page.mouse.click(bounds.x+bounds.width-30,bounds.y+bounds.height/2);
 await page.keyboard.press('Enter');
 await expect(toolbar.getByRole('button',{name:'Split line',exact:true})).toHaveAttribute('aria-pressed','false');
 await expect(page.getByRole('button',{name:'Split part 1',exact:true})).toBeVisible();
 await expect(page.getByRole('button',{name:'Split part 2',exact:true})).toBeVisible();
 await page.getByRole('button',{name:'Split part 2',exact:true}).click();
 await expect(page.getByRole('button',{name:'Split part 2',exact:true})).toHaveAttribute('aria-pressed','true');
});

test('Enter commits a real hole and editing can return to pan with Enter',async({page})=>{
 const {project,ids,toolbar}=await setup(page);
 const before=await (await page.request.get(`${API}/projects/${project}/workspace`)).json();
 await toolbar.getByRole('button',{name:'Cut hole',exact:true}).click();
 for(const [x,y] of await points(page))await page.mouse.click(x,y);
 await expect(toolbar.getByText('4 pts')).toBeVisible();
 await page.keyboard.press('Enter');
 await expect(toolbar.getByRole('button',{name:'Cut hole',exact:true})).toHaveAttribute('aria-pressed','false');
 await expect(toolbar.getByRole('group',{name:'Active drawing'})).toHaveCount(0);
 await openFileMenu(page);
 await page.getByRole('button',{name:'Update feature',exact:true}).click();
 await expect.poll(async()=>{
  const body=await (await page.request.get(`${API}/projects/${project}/workspace`)).json();
  return body.features.find((f:{id:string})=>f.id===ids[0]).geometry.coordinates.length;
 }).toBe(2);
 const after=await (await page.request.get(`${API}/projects/${project}/workspace`)).json();
 expect(after.features.find((f:{id:string})=>f.id===ids[0]).measurement.area_m2)
  .toBeLessThan(before.features.find((f:{id:string})=>f.id===ids[0]).measurement.area_m2);
 await page.locator('.gis-file-menu > summary').click();
 await toolbar.getByRole('button',{name:'Vertices',exact:true}).click();
 await page.keyboard.press('Enter');
 await expect(toolbar.getByRole('button',{name:'Vertices',exact:true})).not.toHaveClass(/active/);
});

test('Object row actions address the neighbour, persist names and respect locked layers',async({page})=>{
 const {project,ids}=await setup(page);
 const row=page.getByRole('group',{name:'Object Polygon 1',exact:true});
 await row.getByRole('button',{name:'Rename object'}).click();
 await row.getByRole('textbox',{name:'Object name'}).fill('厦门岛缓冲区');
 await row.getByRole('textbox',{name:'Object name'}).press('Enter');
 const renamed=page.getByRole('group',{name:'Object 厦门岛缓冲区',exact:true});
 await expect(renamed.getByRole('button',{name:'Rename object'})).toBeVisible();
 await expect(page.getByRole('button',{name:'厦门岛',exact:true})).toHaveAttribute('aria-pressed','true');
 await page.reload();await expect(renamed).toBeVisible();
 await page.getByRole('button',{name:'厦门岛',exact:true}).click();
 await renamed.getByRole('button',{name:'Delete object'}).click();
 await expect(renamed).toHaveCount(0);
 await expect(page.getByRole('button',{name:'厦门岛',exact:true})).toHaveAttribute('aria-pressed','true');
 const body=await (await page.request.get(`${API}/projects/${project}/workspace`)).json();
 expect(body.features.map((f:{id:string})=>f.id)).toEqual([ids[0]]);
 const trash=await (await page.request.get(`${API}/projects/${project}/trash`)).json();
 expect(trash.items.some((f:{feature_id:string})=>f.feature_id===ids[1])).toBe(true);
 await page.getByRole('button',{name:'Undo delete',exact:true}).click();
 await expect(renamed).toBeVisible();
 await expect(page.getByRole('button',{name:'厦门岛',exact:true})).toHaveAttribute('aria-pressed','true');
 await renamed.getByRole('button',{name:'Delete object'}).click();
 await expect(renamed).toHaveCount(0);
 const lock=await page.request.patch(`${API}/projects/${project}/layers/${body.features[0].layer_id}`,{data:{locked:true}});
 expect(lock.ok()).toBe(true);
 await page.reload();
 const locked=page.getByRole('group',{name:'Object 厦门岛',exact:true});
 await expect(locked.getByRole('button',{name:'Rename object'})).toBeDisabled();
 await expect(locked.getByRole('button',{name:'Delete object'})).toBeDisabled();
});

test('local row actions undo correctly and cancelling a sketch retains the selected draft',async({page})=>{
 const {toolbar}=await setup(page);
 await toolbar.getByRole('button',{name:'Rectangle',exact:true}).click();
 const p=await points(page);
 await page.mouse.click(p[0][0],p[0][1]);await page.mouse.click(p[2][0],p[2][1]);
 const local=page.locator('.workspace-feature-group').filter({has:page.locator('summary').filter({hasText:'Local drawings'})});
 await expect(local.getByRole('button',{name:'Polygon 1',exact:true})).toHaveAttribute('aria-pressed','true');
 await local.getByRole('button',{name:'Rename object'}).click();
 await local.getByRole('textbox',{name:'Object name'}).fill('Local study parcel');
 await local.getByRole('button',{name:'Save name'}).click();
 await toolbar.getByRole('button',{name:'Polygon',exact:true}).click();
 const [first]=await points(page);await page.mouse.click(first[0],first[1]);
 await toolbar.getByRole('button',{name:'Cancel drawing'}).click();
 await expect(local.getByRole('button',{name:'Local study parcel',exact:true})).toHaveAttribute('aria-pressed','true');
 await local.getByRole('button',{name:'Delete object'}).click();
 await expect(local).toHaveCount(0);
 await page.keyboard.press('Control+z');
 await expect(local.getByRole('button',{name:'Local study parcel',exact:true})).toHaveAttribute('aria-pressed','true');
 await page.reload();
 await expect(local.getByRole('button',{name:'Local study parcel',exact:true})).toBeVisible();
});


test('boundary coordinates stay expanded when switching scientific workspaces',async({page})=>{
 await page.setViewportSize({width:1600,height:900});
 await setup(page);
 for(const module of ['Survey','GIS','Analysis','Spatial','Network','Temporal','LiDAR','Sensing']){
   await activateWorkspaceModule(page,module);
   const boundary=page.getByRole('region',{name:'Boundary vertices'});
   await expect(boundary).toBeVisible();
   await expect(boundary.getByLabel('Boundary node',{exact:true})).toBeVisible();
   await expect(boundary.getByLabel('Boundary longitude',{exact:true})).toBeVisible();
   await expect(boundary.getByLabel('Boundary latitude',{exact:true})).toBeVisible();
   await expect(boundary.getByRole('button',{name:'Apply coordinates'})).toBeVisible();
   await expect(page.locator('details.geometry-edit-controls')).toHaveCount(0);
   await expect(boundary.locator('details.boundary-node-detail')).toHaveCount(0);
 }
});
