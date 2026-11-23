import {test,expect} from './coverage-fixture';
import type {Page} from '@playwright/test';
import {openFileMenu} from './workspace-ui';

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
 await page.screenshot({path:testInfo.outputPath('survey-objects-'+width+'.png')});
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
 const bounds=(await map.boundingBox())!,y=bounds.y+bounds.height/2;
 // Deliberately cut outside the fitted source polygon, as in the reported
 // workflow. A server rejection must remain readable and cancellable.
 for(const [x,dy] of [[12,-20],[32,-20],[32,20],[12,20]])
  await page.mouse.click(bounds.x+x,y+dy);
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
