import {expect,test} from './coverage-fixture';

const tile=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/ZecAAAAASUVORK5CYII=','base64');
test.beforeEach(async({page})=>{
  await page.route('**/tile.openstreetmap.org/**',route=>
    route.fulfill({status:200,contentType:'image/png',body:tile}));
  await page.goto('/');
  await expect(page.getByLabel('Interactive geospatial map'))
    .toHaveAttribute('data-label-layer-ready','true',{timeout:25000});
});

async function positions(page:import('@playwright/test').Page){
  const rect=(await page.getByLabel('Interactive geospatial map').boundingBox())!;
  const unit=Math.min(85,rect.width*.13,rect.height*.16);
  return {a:[rect.x+rect.width*.38,rect.y+rect.height*.38] as const,
    b:[rect.x+rect.width*.38+unit,rect.y+rect.height*.38] as const,
    c:[rect.x+rect.width*.38+unit,rect.y+rect.height*.38+unit] as const,
    d:[rect.x+rect.width*.38,rect.y+rect.height*.38+unit] as const,
    unit};
}

test('polygon closes by snapping to first node without a duplicate open segment',async({page})=>{
  const toolbar=page.getByLabel('Survey toolbar');
  await toolbar.getByRole('button',{name:'Polygon',exact:true}).click();
  const p=await positions(page);
  for(const [x,y] of [p.a,p.b,p.c,p.d])await page.mouse.click(x,y);
  await expect(toolbar.getByText('4 pts')).toBeVisible();
  // Clicking within the first handle's 14px tolerance completes the ring.
  await page.mouse.click(p.a[0]+5,p.a[1]-3);
  await expect(page.getByText(/Drawing completed and measured/)).toBeVisible();
  await expect(toolbar.getByRole('button',{name:'Finish',exact:true})).toHaveCount(0);
  await expect(toolbar.getByRole('button',{name:'Polygon',exact:true})).toHaveAttribute('aria-pressed','false');
  await expect(page.getByLabel('Live map dimensions').locator('.map-dimension-total')).not.toContainText('~ ');
});

test('Enter, Backspace, Ctrl+Z, Ctrl+Y and Finish use sketch-only vertex history',async({page})=>{
  const toolbar=page.getByLabel('Survey toolbar');
  await toolbar.getByRole('button',{name:'Polygon',exact:true}).click();
  const p=await positions(page);
  for(const [x,y] of [p.a,p.b,p.c])await page.mouse.click(x,y);
  await expect(toolbar.getByText('3 pts')).toBeVisible();
  await page.keyboard.press('Backspace');
  await expect(toolbar.getByText('2 pts')).toBeVisible();
  await expect(toolbar.getByRole('button',{name:'Finish',exact:true})).toBeDisabled();
  await page.keyboard.press('Control+y');
  await expect(toolbar.getByText('3 pts')).toBeVisible();
  await page.keyboard.press('Control+z');
  await expect(toolbar.getByText('2 pts')).toBeVisible();
  await page.keyboard.press('Control+Shift+z');
  await expect(toolbar.getByText('3 pts')).toBeVisible();
  await page.keyboard.press('Enter');
  await expect(page.getByText(/Drawing completed and measured/)).toBeVisible();
  await toolbar.getByRole('button',{name:'Polygon',exact:true}).click();
  for(const [x,y] of [p.a,p.b,p.c])await page.mouse.click(x,y);
  await toolbar.getByRole('button',{name:'Finish',exact:true}).click();
  await expect(page.getByText(/Drawing completed and measured/)).toBeVisible();
});

test('invalid new polygon edge is rejected before Finish, and Escape exits without losing selection',async({page})=>{
  const toolbar=page.getByLabel('Survey toolbar');
  await toolbar.getByRole('button',{name:'Polygon',exact:true}).click();
  const p=await positions(page);
  // A, C, D are a valid triangle. New D->B would cross A->C.
  for(const [x,y] of [p.a,p.c,p.d,p.b])await page.mouse.click(x,y);
  await expect(toolbar.getByText('3 pts')).toBeVisible();
  await expect(page.getByRole('alert').filter({hasText:/crosses or touches an existing polygon edge/})).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(toolbar.getByRole('button',{name:'Finish',exact:true})).toHaveCount(0);
  await expect(toolbar.getByRole('button',{name:'Polygon',exact:true})).toHaveAttribute('aria-pressed','false');
});

test('double-click finishes lines without appending a duplicate last vertex',async({page})=>{
  const toolbar=page.getByLabel('Survey toolbar');
  await toolbar.getByRole('button',{name:'Line',exact:true}).click();
  const p=await positions(page);
  await page.mouse.click(...p.a);
  await page.mouse.dblclick(...p.c,{delay:120});
  await expect(page.getByText(/Drawing completed and measured/)).toBeVisible();
  await expect(toolbar.getByRole('button',{name:'Finish',exact:true})).toHaveCount(0);
});

test('survey buttons bind to operations and required geometry prerequisites',async({page})=>{
  const toolbar=page.getByLabel('Survey toolbar');
  for(const name of ['Point','Polygon','Line','Rectangle','Circle']){
    const button=toolbar.getByRole('button',{name,exact:true});
    await expect(button).toBeEnabled();
    await button.click();
    await expect(button).toHaveAttribute('aria-pressed','true');
    await toolbar.getByRole('button',{name:'Cancel drawing'}).click();
    await expect(button).toHaveAttribute('aria-pressed','false');
  }
  for(const name of ['Cut hole','Split line','Trace network'])
    await expect(toolbar.getByRole('button',{name,exact:true})).toBeDisabled();
  const p=await positions(page);
  await toolbar.getByRole('button',{name:'Rectangle',exact:true}).click();
  await page.mouse.click(...p.a);
  await page.mouse.click(...p.c);
  await expect(page.getByText(/Drawing completed and measured/)).toBeVisible();
  await expect(toolbar.getByRole('button',{name:'Cut hole',exact:true})).toBeEnabled();
  await expect(toolbar.getByRole('button',{name:'Split line',exact:true})).toBeEnabled();
  await toolbar.getByRole('button',{name:'Cut hole',exact:true}).click();
  await expect(toolbar.getByRole('button',{name:'Cut hole',exact:true})).toHaveAttribute('aria-pressed','true');
  await toolbar.getByRole('button',{name:'Cancel drawing'}).click();
});

test('Line drawing closed at its starting node produces an area with exact measurement',async({page})=>{
 const toolbar=page.getByLabel('Survey toolbar');
 await toolbar.getByRole('button',{name:'Line',exact:true}).click();
 const p=await positions(page);
 for(const [x,y] of [p.a,p.b,p.c,p.d])await page.mouse.click(x,y);
 await expect(toolbar.getByText('4 pts')).toBeVisible();
 await page.mouse.click(p.a[0]+4,p.a[1]+2);
 await expect(page.getByText(/Closed line converted to a measured region/)).toBeVisible();
 await expect(toolbar.getByRole('button',{name:'Line',exact:true})).toHaveAttribute('aria-pressed','false');
 const dimensions=page.getByLabel('Live map dimensions');
 await expect(dimensions.locator('.map-dimension-total')).toContainText(/km²|m²|ha/);
 await expect(dimensions.locator('.map-dimension-total')).not.toContainText('~ ');
});

test('four separate connected lines create a selectable independently measured area',async({page})=>{
 const toolbar=page.getByLabel('Survey toolbar');
 // Zoom to a local geography so the GEOS metric polygonizer receives a
 // realistic small-area network, independent of map tile availability.
 const map=page.getByLabel('Interactive geospatial map');
 const box=(await map.boundingBox())!;
 await page.mouse.move(box.x+box.width/2,box.y+box.height/2);
 await page.mouse.wheel(0,-1600);
 await page.waitForTimeout(900);
 const p=await positions(page);
 for(const [from,to] of [[p.a,p.b],[p.b,p.c],[p.c,p.d],[p.d,p.a]] as const){
   await toolbar.getByRole('button',{name:'Line',exact:true}).click();
   await page.mouse.click(...from);
   await page.mouse.click(...to);
   await page.keyboard.press('Enter');
   await expect(toolbar.getByRole('button',{name:'Line',exact:true})).toHaveAttribute('aria-pressed','false');
 }
 const labels=page.getByLabel('Live map dimensions').locator('.map-face-dimension');
 await expect(labels.first()).toBeVisible({timeout:25000});
 await expect(labels.first()).toContainText(/km²|m²|ha/);
 const midpoint:[number,number]=[(p.a[0]+p.c[0])/2,(p.a[1]+p.c[1])/2];
 await page.mouse.click(...midpoint);
 await expect(page.getByText(/closed polygon selected with area and perimeter/)).toBeVisible({timeout:10000});
 // Derived polygons are saved as independent local objects, not discarded
 // with their source line segments.
 await expect(page.getByLabel('Live map dimensions').locator('.map-face-dimension')).toHaveCount(0);
 await expect(page.getByLabel('Live map dimensions').locator('.map-dimension-total')).toContainText('perimeter');
 await expect(page.getByLabel('Map legend',{exact:true}).getByText('Area 1',{exact:true})).toHaveCount(1);
});

test('existing drawn polygons are not duplicated by automatic polygonization',async({page})=>{
 const toolbar=page.getByLabel('Survey toolbar');
 const map=page.getByLabel('Interactive geospatial map');
 const box=(await map.boundingBox())!;
 await page.mouse.move(box.x+box.width/2,box.y+box.height/2);
 await page.mouse.wheel(0,-1600);
 await page.waitForTimeout(900);
 const response=page.waitForResponse(r=>r.url().includes('/edit/polygonize')&&r.request().method()==='POST'&&r.ok());
 const p=await positions(page);
 await toolbar.getByRole('button',{name:'Polygon',exact:true}).click();
 for(const [x,y] of [p.a,p.b,p.c,p.d])await page.mouse.click(x,y);
 await page.keyboard.press('Enter');
 const output=await (await response).json();
 expect(output.count).toBe(0);
 const legend=page.getByLabel('Map legend',{exact:true});
 await expect(legend.getByText('Polygon 1',{exact:true})).toHaveCount(1);
 await expect(legend.getByText('Area 1',{exact:true})).toHaveCount(0);
});
