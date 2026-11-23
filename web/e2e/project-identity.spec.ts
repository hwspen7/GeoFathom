import {openProjectDrawer} from './workspace-ui';
import {expect,test} from './coverage-fixture';

const API='http://127.0.0.1:8000';
const tile='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/ZecAAAAASUVORK5CYII=';
test.beforeEach(async({page})=>{
  await page.route('**/tile.openstreetmap.org/**',route=>
    route.fulfill({status:200,contentType:'image/png',body:Buffer.from(tile,'base64')}));
});

test('a late workspace response cannot replace the selected project or its layers',async({page})=>{
  const suffix=Date.now().toString(36)+'-'+Math.random().toString(36).slice(2);
  async function create(name:string){
    const response=await page.request.post(API+'/projects',{data:{name:name+' '+suffix}});
    expect(response.status()).toBe(201);
    const project=await response.json();
    const layer=await page.request.post(API+'/projects/'+project.id+'/layers',{
      data:{name,color:'#2563eb'},
    });
    expect(layer.ok()).toBeTruthy();
    return project.id as string;
  }
  const first=await create('Delayed project layer');
  const second=await create('Current project layer');

  // Hold one real workspace response while a newer selection is loaded.
  let release!:()=>void;
  const pending=new Promise<void>(resolve=>{release=resolve;});
  let received!:()=>void;
  const requested=new Promise<void>(resolve=>{received=resolve;});
  await page.route('**/projects/'+first+'/workspace',async route=>{
    const result=await route.fetch();
    received();
    await pending;
    await route.fulfill({response:result});
  });
  try{
    await page.goto('/');
    const selection=page.getByLabel('Active project');
    // Both fixtures are present before we switch between them.
    await expect(selection.locator('option[value="'+first+'"]')).toHaveCount(1);
    await selection.selectOption(first);
    await requested;
    await selection.selectOption(second);
    await openProjectDrawer(page);
    await expect(page.getByRole('button',{name:'Current project layer',exact:true})).toBeVisible();
    const oldResponse=page.waitForResponse(response=>response.url().endsWith('/projects/'+first+'/workspace'));
    release();
    await oldResponse;
    // A browser task turn lets the old fetch continuation attempt publication.
    await page.evaluate(()=>new Promise<void>(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve()))));
    await expect(selection).toHaveValue(second);
    await expect(page.getByRole('button',{name:'Current project layer',exact:true})).toBeVisible();
    await expect(page.getByRole('button',{name:'Delayed project layer',exact:true})).toHaveCount(0);
    await page.reload();
    await openProjectDrawer(page);
    await expect(page.getByLabel('Active project')).toHaveValue(second);
    await expect(page.getByRole('button',{name:'Current project layer',exact:true})).toBeVisible();
  }finally{release();}
});
