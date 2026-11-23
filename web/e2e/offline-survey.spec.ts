import {test,expect} from './coverage-fixture';
import {openProjectDrawer} from './workspace-ui';
const tile=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/ZecAAAAASUVORK5CYII=','base64');
test('offline drawing finishes, multiple local features remain selectable and reload',async({page})=>{
 await page.route('**/api/**',r=>r.fulfill({status:503,contentType:'application/json',body:'{"detail":"Backend offline"}'}));
 await page.route('**/tile.openstreetmap.org/**',r=>r.fulfill({contentType:'image/png',body:tile}));
 await page.goto('/');
 const map=page.getByLabel('Interactive geospatial map');
 await expect(map).toHaveAttribute('data-label-layer-ready','true',{timeout:25000});
 const box=(await map.boundingBox())!;
 const x=box.x+box.width*.28,y=box.y+box.height*.35,d=Math.min(60,box.width*.13);
 const toolbar=page.getByLabel('Survey toolbar');
 await toolbar.getByRole('button',{name:'Polygon',exact:true}).click();
 for(const [a,b] of [[x,y],[x+d,y],[x+d,y+d],[x,y+d]])await page.mouse.click(a,b);
 await toolbar.getByRole('button',{name:'Finish',exact:true}).click();
 await expect(page.getByText(/Drawing completed locally/)).toBeVisible();
 await expect(page.getByLabel('Live map dimensions')).toContainText('~ ');
 await expect(toolbar.getByRole('button',{name:'Finish',exact:true})).toHaveCount(0);
 await toolbar.getByRole('button',{name:'Rectangle',exact:true}).click();
 await page.mouse.click(x+2*d,y);await page.mouse.click(x+3*d,y+d);
 // The layer list and map legend both display the count; assert the legend explicitly.
 await expect(page.getByLabel('Map legend',{exact:true}).getByText('Local drawings · 2',{exact:true})).toBeVisible();
 await page.reload();
 await openProjectDrawer(page,'layers');
 await expect(page.getByLabel('Local drawings').getByRole('button',{name:'Polygon 1',exact:true})).toBeVisible();
 await page.getByLabel('Local drawings').getByRole('button',{name:'Polygon 1',exact:true}).click();
 await expect(page.getByText('Selected Polygon 1',{exact:true})).toBeVisible();
});
