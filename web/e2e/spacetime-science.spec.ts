import {expect,test} from './coverage-fixture';
import {activateWorkspaceModule} from './workspace-ui';
// Actual six-band 3x3 float32 georeferenced TIFF; each band is 3+2*t.
const cube='SUkqAMIBAAARAAABAwABAAAAAwAAAAEBAwABAAAAAwAAAAIBAwAGAAAA2gAAAAMBAwABAAAACAAAAAYBAwABAAAAAQAAABEBBAABAAAAAAAAABUBAwABAAAABgAAABYBAwABAAAAAwAAABcBBAABAAAAAAAAABwBAwABAAAAAQAAAD0BAwABAAAAAQAAAFIBAwAFAAAA5gAAAFMBAwAGAAAA8AAAAA6DDAADAAAA/AAAAIKEDAAGAAAAFAEAAK+HAwAgAAAARAEAALGHAgAeAAAAhAEAAAAAAAAgACAAIAAgACAAIAAAAAAAAAAAAAAAAwADAAMAAwADAAMAAAAAAAAAJEAAAAAAAAAkQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAICEHkEAAAAAiCpRQQAAAAAAAAAAAQABAAAABwAABAAAAQABAAEEAAABAAEAAgSxhxYAAAABCLGHBwAWAAYIAAABAI4jAAwAAAEAaX8EDAAAAQApI1dHUyA4NCAvIFVUTSB6b25lIDE3TnxXR1MgODR8AHicY2BwcGBgWADED4BYwJGBwQCIA4B4aIsDAJkxImwAEgAAAQMAAQAAAAMAAAABAQMAAQAAAAMAAAACAQMABgAAAKACAAADAQMAAQAAAAgAAAAGAQMAAQAAAAEAAAARAQQAAQAAAKIBAAAVAQMAAQAAAAYAAAAWAQMAAQAAAAMAAAAXAQQAAQAAAB8AAAAcAQMAAQAAAAEAAAA9AQMAAQAAAAEAAABSAQMABQAAAKwCAABTAQMABgAAALYCAAAOgwwAAwAAAMICAACChAwABgAAANoCAACvhwMAIAAAAAoDAACxhwIAHgAAAEoDAACApAIASQAAAGgDAAAAAAAAIAAgACAAIAAgACAAAAAAAAAAAAAAAAMAAwADAAMAAwADAAAAAAAAACRAAAAAAAAAJEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACAhB5BAAAAAIgqUUEAAAAAAAAAAAEAAQAAAAcAAAQAAAEAAQABBAAAAQABAAIEsYcWAAAAAQixhwcAFgAGCAAAAQCOIwAMAAABAGl/BAwAAAEAKSNXR1MgODQgLyBVVE0gem9uZSAxN058V0dTIDg0fAA8R0RBTE1ldGFkYXRhPgogIDxJdGVtIG5hbWU9IlRFUlJBSU5fVU5JVCI+aW5kZXg8L0l0ZW0+CjwvR0RBTE1ldGFkYXRhPgoA';
test('dated multiband cube produces real trend raster and export',async({page})=>{
 await page.goto('/');await activateWorkspaceModule(page,'Spatiotemporal Analysis');
 await page.getByRole('button',{name:'Open Spatiotemporal Analysis'}).click();
 const d=page.getByRole('dialog',{name:'Spatiotemporal science workbench'});
 await expect(d).toContainText('84 scientific methods');
 await d.getByLabel('Additional cube or QA sources').setInputFiles({name:'cube.tif',mimeType:'image/tiff',buffer:Buffer.from(cube,'base64')});
 await d.getByText('Multiband cube binding',{exact:true}).click();
 await expect(d.getByRole('button',{name:'Bind bands as dated observations'})).toBeEnabled();
 await d.getByRole('button',{name:'Bind bands as dated observations'}).click();
 for(let i=1;i<=6;i++)await d.getByLabel('Acquisition time '+i,{exact:true}).fill(String(i-1));
 await d.getByLabel('Space-time algorithm').selectOption('series_slope');
 const response=page.waitForResponse(r=>r.url().endsWith('/analysis/spatiotemporal/run')&&r.request().method()==='POST');
 await d.getByRole('button',{name:'Run spatiotemporal analysis'}).click();
 const res=await response;expect(res.ok()).toBeTruthy();const data=await res.json();expect(data.raster.summary.minimum).toBeCloseTo(2);expect(data.raster.summary.maximum).toBeCloseTo(2);
 await expect(d.getByAltText('Computed spatiotemporal raster')).toBeVisible();
 const download=page.waitForEvent('download');await d.getByRole('button',{name:'GeoTIFF',exact:true}).click();expect((await download).suggestedFilename()).toBe('series_slope.tif');
 await d.getByRole('button',{name:'Show space-time raster on map'}).click();await expect(d).not.toBeVisible();
 await expect(page.getByLabel('Spatiotemporal result layer')).toBeVisible();
});
