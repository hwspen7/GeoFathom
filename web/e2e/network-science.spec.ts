import {expect,test} from './coverage-fixture';
import {activateWorkspaceModule} from './workspace-ui';

test('network workbench computes a directed route, exports and previews it',async({page})=>{
 await page.route('**/tile.openstreetmap.org/**',route=>route.fulfill({status:200,contentType:'image/png',body:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/ZecAAAAASUVORK5CYII=','base64')}));
 await page.goto('/');await activateWorkspaceModule(page,'Network Analysis');
 await page.getByRole('button',{name:'Open Network Analysis'}).click();
 const d=page.getByRole('dialog',{name:'Network science workbench'});
 await expect(d).toContainText('24 scientific methods');
 const edge=(id:string,source:string,target:string,a:number,b:number,minutes:number)=>({type:'Feature',geometry:{type:'LineString',coordinates:[[a,0],[b,0]]},properties:{edge_id:id,source,target,direction:'forward',minutes}});
 const graph={type:'FeatureCollection',features:[edge('ab','A','B',0,.001,2),edge('bc','B','C',.001,.002,3)]};
 await d.getByLabel('Network GeoJSON').setInputFiles({name:'network.geojson',mimeType:'application/geo+json',buffer:Buffer.from(JSON.stringify(graph))});
 await d.getByLabel('Cost property').fill('minutes');
 await d.getByLabel('Network algorithm').selectOption('shortest_path');
 await d.getByLabel('Origin node IDs (one per line)').fill('A');
 await d.getByLabel('Destination node IDs (one per line)').fill('C');
 const response=page.waitForResponse(r=>r.url().endsWith('/analysis/network-science/run')&&r.request().method()==='POST');
 await d.getByRole('button',{name:'Run network analysis'}).click();
 const r=await response;expect(r.ok()).toBeTruthy();expect((await r.json()).receipt.metrics.total_cost).toBe(5);
 await expect(d.getByRole('button',{name:'Cumulative route impedance'})).toBeVisible();
 const download=page.waitForEvent('download');await d.getByRole('button',{name:'GeoJSON',exact:true}).click();
 expect((await download).suggestedFilename()).toBe('network-result.geojson');
 await d.getByRole('button',{name:'Show network results on map'}).click();await expect(d).not.toBeVisible();
 await expect(page.locator('[data-network-science-feature-count="2"]')).toBeVisible();
});
