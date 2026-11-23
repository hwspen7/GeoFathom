import {expect,test} from './coverage-fixture';
import {activateWorkspaceModule,expectWorkspaceModule} from './workspace-ui';

const edge=(a:[number,number],b:[number,number])=>({
 type:'LineString',coordinates:[a,b],
});
for(const width of [1280,1600])test('Data and Export are independent fixed top modules with real GIS operations at '+width+'px',async({page})=>{
 await page.setViewportSize({width,height:900});
 await page.goto('/');
 await page.getByLabel('Active project').selectOption('');
 const modules=page.getByRole('navigation',{name:'Workspace tools'});
 if(width===1600){
  await expect(modules.getByRole('button',{name:'Data',exact:true})).toBeVisible();
  await expect(modules.getByRole('button',{name:'Export',exact:true})).toBeVisible();
 }else await expect(modules.getByLabel('Workspace module')).toBeVisible();
 await activateWorkspaceModule(page,'Data');
 await expect(page.getByLabel('Data operations')).toBeVisible();
 await expect(page.getByRole('button',{name:'Detect enclosed areas'})).toBeVisible();
 await expect(page.getByRole('button',{name:'Detect enclosed areas'})).toBeDisabled();
 await page.getByRole('button',{name:'Import',exact:true}).click();
 await expect(page.getByLabel('Import dataset file')).toBeVisible();
 await page.getByRole('button',{name:'Sources',exact:true}).click();
 await page.getByRole('button',{name:'Add source'}).click();
 await expect(page.getByLabel('New OGC service type')).toBeVisible();
 await activateWorkspaceModule(page,'Export');
 await expect(page.getByLabel('Export scope')).toBeVisible();
 await expect(page.getByLabel('Export format')).toBeVisible();
 await expect(page.getByRole('button',{name:'Export GEOJSON'})).toBeDisabled();
 await expectWorkspaceModule(page,'Export');
});

test('noded network derives three independently measurable areas through the live API',async({request})=>{
 const d=.01;
 const network=[
  edge([0,0],[3*d,0]),edge([3*d,0],[3*d,d]),
  edge([3*d,d],[0,d]),edge([0,d],[0,0]),
  edge([d,0],[d,d]),edge([2*d,0],[2*d,d]),
 ];
 const response=await request.post('/api/edit/polygonize',{data:{
  geometries:network,tolerance_m:1,minimum_area_m2:1,max_faces:300,
 }});
 expect(response.status()).toBe(200);
 const result=await response.json() as {count:number;faces:Array<{
  geometry:GeoJSON.Geometry;label_anchor:number[];
  measurement:{area_m2:number;perimeter_m:number};
 }>;dangles:number;cuts:number};
 expect(result.count).toBe(3);
 expect(result.dangles).toBe(0);
 expect(result.cuts).toBe(0);
 for(const face of result.faces){
  expect(face.geometry.type).toBe('Polygon');
  expect(face.label_anchor).toHaveLength(2);
  expect(face.measurement.area_m2).toBeGreaterThan(1000);
  expect(face.measurement.perimeter_m).toBeGreaterThan(100);
 }
});
