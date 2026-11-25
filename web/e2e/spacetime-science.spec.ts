import {expect,test} from './coverage-fixture';
import {activateWorkspaceModule,openProjectDrawer} from './workspace-ui';
// Actual six-band 3x3 uint8 georeferenced TIFF; each band is 3+2*t.
const cube='SUkqAMwBAAAQAAABAwABAAAAAwAAAAEBAwABAAAAAwAAAAIBAwAGAAAAzgAAAAMBAwABAAAAAQAAAAYBAwABAAAAAQAAABEBBAABAAAAAAAAABUBAwABAAAABgAAABYBAwABAAAAAwAAABcBBAABAAAAAAAAABwBAwABAAAAAQAAAFIBAwAFAAAA2gAAAFMBAwAGAAAA5AAAAA6DDAADAAAA8AAAAIKEDAAGAAAACAEAAK+HAwAgAAAAOAEAALGHAgAeAAAAeAEAAAAAAAAIAAgACAAIAAgACAAAAAAAAAAAAAAAAQABAAEAAQABAAEAAAAAAAAAJEAAAAAAAAAkQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAICEHkEAAAAAiCpRQQAAAAAAAAAAAQABAAAABwAABAAAAQABAAEEAAABAAEAAgSxhxYAAAABCLGHBwAWAAYIAAABAI4jAAwAAAEAaX8EDAAAAQApI1dHUyA4NCAvIFVUTSB6b25lIDE3TnxXR1MgODR8AAMFBwkLDQMFBwkLDQMFBwkLDQMFBwkLDQMFBwkLDQMFBwkLDQMFBwkLDQMFBwkLDQMFBwkLDREAAAEDAAEAAAADAAAAAQEDAAEAAAADAAAAAgEDAAYAAACeAgAAAwEDAAEAAAABAAAABgEDAAEAAAABAAAAEQEEAAEAAACWAQAAFQEDAAEAAAAGAAAAFgEDAAEAAAADAAAAFwEEAAEAAAA2AAAAHAEDAAEAAAABAAAAUgEDAAUAAACqAgAAUwEDAAYAAAC0AgAADoMMAAMAAADAAgAAgoQMAAYAAADYAgAAr4cDACAAAAAIAwAAsYcCAB4AAABIAwAAgKQCAEkAAABmAwAAAAAAAAgACAAIAAgACAAIAAAAAAAAAAAAAAABAAEAAQABAAEAAQAAAAAAAAAkQAAAAAAAACRAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAgIQeQQAAAACIKlFBAAAAAAAAAAABAAEAAAAHAAAEAAABAAEAAQQAAAEAAQACBLGHFgAAAAEIsYcHABYABggAAAEAjiMADAAAAQBpfwQMAAABACkjV0dTIDg0IC8gVVRNIHpvbmUgMTdOfFdHUyA4NHwAPEdEQUxNZXRhZGF0YT4KICA8SXRlbSBuYW1lPSJURVJSQUlOX1VOSVQiPmluZGV4PC9JdGVtPgo8L0dEQUxNZXRhZGF0YT4KAA==';
test('dated multiband cube produces real trend raster and export',async({page})=>{
 await page.goto('/');await activateWorkspaceModule(page,'Temporal');
 await page.getByRole('button',{name:'Open Spatiotemporal Analysis'}).click();
 const d=page.getByRole('dialog',{name:'Spatiotemporal science workbench'});
 await expect(d).toContainText('88 scientific methods');
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
 await expect(page.getByLabel('Interactive geospatial map')).toHaveAttribute('data-terrain-raster-count','1');
 await openProjectDrawer(page,'layers');
 await expect(page.getByLabel('Spatiotemporal result layer')).toBeVisible();
 await expect(page.getByLabel('Spatiotemporal result layer')).toBeChecked();
});
