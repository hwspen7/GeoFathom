/** Fail fast with actionable diagnostics when the browser cannot mount the GIS workspace. */
import {test,expect} from '@playwright/test';

test('GIS workspace boots, renders tools, and accepts module selection',async({page})=>{
 const pageErrors:string[]=[],consoleErrors:string[]=[],failedRequests:string[]=[];
 page.on('pageerror',error=>pageErrors.push(error.stack??error.message));
 page.on('console',message=>{if(message.type()==='error')consoleErrors.push(message.text());});
 page.on('requestfailed',request=>{
  if(request.url().startsWith('http://localhost:5173')||
     request.url().startsWith('http://127.0.0.1:8000'))
   failedRequests.push(request.method()+' '+request.url()+' '+request.failure()?.errorText);
 });
 const response=await page.goto('/',{waitUntil:'domcontentloaded',timeout:20000});
 try{
  expect(response?.status()).toBe(200);
  const navigation=page.getByRole('navigation',{name:'Workspace tools'});
  await expect(navigation).toBeVisible({timeout:15000});
  const compact=navigation.getByLabel('Workspace module',{exact:true});
  if(await compact.isVisible())await compact.selectOption({label:'GIS'});
  else await navigation.getByRole('button',{name:'GIS',exact:true}).click();
  await expect(page.locator('#tools-gis')).toBeVisible({timeout:8000});
  await expect(page.getByLabel('Interactive geospatial map')).toBeVisible({timeout:8000});
  expect(pageErrors).toEqual([]);
 }catch(error){
  const body=(await page.locator('body').innerText().catch(()=>'<body unavailable>')).slice(0,2500);
  throw new Error('GIS browser bootstrap failed. '+String(error)+
   '\nBody: '+body+
   '\nPage exceptions: '+JSON.stringify(pageErrors.slice(0,10))+
   '\nConsole errors: '+JSON.stringify(consoleErrors.slice(0,10))+
   '\nLocal request failures: '+JSON.stringify(failedRequests.slice(0,10)));
 }
});
