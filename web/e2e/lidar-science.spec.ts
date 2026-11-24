import {expect,test} from './coverage-fixture';
import {activateWorkspaceModule} from './workspace-ui';

test('LiDAR workbench imports real XYZ bytes, measures voxel counts and exports results',async({page})=>{
 await page.route('**/tile.openstreetmap.org/**',route=>route.fulfill({status:200,contentType:'image/png',body:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/ZecAAAAASUVORK5CYII=','base64')}));
 await page.goto('/');
 await activateWorkspaceModule(page,'3D & LiDAR');
 const panel=page.locator('#tools-lidar');
 await panel.getByLabel('Analysis method').selectOption('voxel');
 await panel.getByLabel('Point cloud (LAS or XYZ CSV)').setInputFiles({name:'cloud.csv',mimeType:'text/csv',buffer:Buffer.from('x,y,z\n0.1,0.1,0.1\n0.3,0.3,0.3\n1.2,0.1,0.1\n')});
 await panel.getByLabel('Projected EPSG (metres)').fill('32617');
 await panel.getByLabel('Vertical datum / height reference').fill('local');
 await panel.getByRole('checkbox').check();
 const pending=page.waitForResponse(r=>r.url().includes('/analysis/lidar/run?')&&r.request().method()==='POST');
 await panel.getByRole('button',{name:'Run 3D analysis'}).click();
 const res=await pending;expect(res.ok()).toBeTruthy();
 const body=await res.json();expect(body.metrics.output_points).toBe(2);
 const results=page.getByRole('region',{name:'3D and LiDAR results'});
 await expect(results.getByRole('img',{name:'Equal-scale orthographic point cloud'})).toBeVisible();
 const download=page.waitForEvent('download');await results.getByRole('button',{name:'Export full CSV'}).click();
 expect((await download).suggestedFilename()).toBe('lidar-voxel.csv');
});
