import {expect,test} from './coverage-fixture';
import {openProjectDrawer} from './workspace-ui';
const API='http://127.0.0.1:8000';
const tile='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/ZecAAAAASUVORK5CYII=';

test('project switch clears selected saved geometry and cannot undo into another project',async({page})=>{
  await page.route('**/tile.openstreetmap.org/**',route=>route.fulfill({
    status:200,contentType:'image/png',body:Buffer.from(tile,'base64')}));
  const suffix=Date.now().toString(36)+'-'+Math.random().toString(36).slice(2);
  async function create(name:string){
    const response=await page.request.post(API+'/projects',{data:{name:name+' '+suffix}});
    expect(response.status(),await response.text()).toBe(201);
    return (await response.json()).id as string;
  }
  const first=await create('Source project');
  const second=await create('Destination project');
  const original=await page.request.post(API+'/projects/'+first+'/features',{data:{
    name:'Isolated parcel '+suffix,geometry:{type:'Polygon',coordinates:[[[10,20],[10.01,20],[10.01,20.01],[10,20]]]},
    source:'Test',
  }});
  expect(original.status(),await original.text()).toBe(201);
  await page.goto('/');
  const select=page.getByLabel('Active project');
  await expect(select.locator('option[value="'+first+'"]')).toHaveCount(1);
  await select.selectOption(first);
  await page.getByRole('button',{name:new RegExp('Isolated parcel '+suffix)}).click();
  await expect(page.getByRole('button',{name:'Update feature'})).toBeEnabled();
  await openProjectDrawer(page);
  await page.getByLabel('Map note text').fill('Do not put this in another project');
  await page.getByLabel('Place map note').click();
  await select.selectOption(second);
  await expect(page.getByText('No saved features yet.')).toBeVisible();
  await expect(page.getByRole('button',{name:'Save selected'})).toBeDisabled();
  await expect(page.getByRole('button',{name:'Undo',exact:true})).toBeDisabled();
  await expect(page.getByRole('button',{name:'Redo',exact:true})).toBeDisabled();
  await expect(page.getByRole('button',{name:'Update feature'})).toHaveCount(0);
  const workspace=await page.request.get(API+'/projects/'+second+'/workspace');
  expect((await workspace.json()).total).toBe(0);
  await select.selectOption(first);
  await expect(page.getByRole('button',{name:new RegExp('Isolated parcel '+suffix)})).toBeVisible();
});


test('delayed authoritative geometry validation cannot publish after project switch',async({page})=>{
  await page.route('**/tile.openstreetmap.org/**',route=>route.fulfill({
    status:200,contentType:'image/png',body:Buffer.from(tile,'base64')}));
  const suffix=Date.now().toString(36)+'-'+Math.random().toString(36).slice(2);
  async function create(name:string){
    const response=await page.request.post(API+'/projects',{data:{name:name+' '+suffix}});
    expect(response.status(),await response.text()).toBe(201);
    return (await response.json()).id as string;
  }
  const first=await create('Pending geometry');
  const second=await create('New geometry workspace');
  await page.goto('/');
  const select=page.getByLabel('Active project');
  await expect(select.locator('option[value="'+first+'"]')).toHaveCount(1);
  await select.selectOption(first);
  await expect(page.getByRole('button',{name:'Measurements',exact:true})).toBeVisible();
  let release!:()=>void;
  const gate=new Promise<void>(resolve=>{release=resolve;});
  let requested!:()=>void;
  const received=new Promise<void>(resolve=>{requested=resolve;});
  await page.route('**/measure',async route=>{
    const response=await route.fetch();
    requested();
    await gate;
    await route.fulfill({response});
  });
  try{
    await page.getByLabel('Numeric construction mode').selectOption('rectangle');
    await page.getByLabel('Longitude',{exact:true}).fill('10');
    await page.getByLabel('Latitude',{exact:true}).fill('20');
    await page.getByLabel('Opposite longitude').fill('10.01');
    await page.getByLabel('Opposite latitude').fill('20.01');
    await page.getByRole('button',{name:'Apply exact geometry'}).click();
    await received;
    await select.selectOption(second);
    await expect(select).toHaveValue(second);
    await expect(page.getByRole('button',{name:'Save selected'})).toBeDisabled();
    const response=page.waitForResponse(r=>r.url().endsWith('/measure')&&r.request().method()==='POST');
    release();await response;
    await page.evaluate(()=>new Promise<void>(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve()))));
    await expect(page.getByRole('button',{name:'Save selected'})).toBeDisabled();
    await expect(page.getByText('Precise construction created with PyProj.')).toHaveCount(0);
  }finally{release();}
});
