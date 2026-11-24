import {expect,test} from './coverage-fixture';
import {activateWorkspaceModule} from './workspace-ui';

const scene='SUkqAAgAAAAQAAABAwABAAAAAgAAAAEBAwABAAAAAgAAAAIBAwACAAAAIAAgAAMBAwABAAAAAQAAAAYBAwABAAAAAQAAABEBBAABAAAAdAEAABUBAwABAAAAAgAAABYBAwABAAAAAgAAABcBBAABAAAAIAAAABwBAwABAAAAAQAAAFIBAwABAAAAAAAAAFMBAwACAAAAAwADAA6DDAADAAAAzgAAAIKEDAAGAAAA5gAAAK+HAwAgAAAAFgEAALGHAgAeAAAAVgEAAAAAAAAAAAAAAAAkQAAAAAAAACRAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAgIQeQQAAAACIKlFBAAAAAAAAAAABAAEAAAAHAAAEAAABAAEAAQQAAAEAAQACBLGHFgAAAAEIsYcHABYABggAAAEAjiMADAAAAQBpfwQMAAABACkjV0dTIDg0IC8gVVRNIHpvbmUgMTdOfFdHUyA4NHwAmpkZP83MTD6amRk/zcxMPpqZGT/NzEw+mpkZP83MTD4=';

test('remote sensing maps two calibrated bands and exports actual NDVI',async({page})=>{
 await page.route('**/tile.openstreetmap.org/**',route=>route.fulfill({status:200,contentType:'image/png',body:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/ZecAAAAASUVORK5CYII=','base64')}));
 await page.goto('/');
 await activateWorkspaceModule(page,'Remote Sensing');
 await page.getByRole('button',{name:'Open Remote Sensing'}).click();
 const dialog=page.getByRole('dialog',{name:'Remote sensing workbench'});
 await expect(dialog).toContainText('139 scientific methods');
 await expect(dialog.getByLabel('Remote sensing method')).toHaveValue('ndvi');
 await dialog.getByLabel('GeoTIFF source').setInputFiles({name:'two-band.tif',mimeType:'image/tiff',buffer:Buffer.from(scene,'base64')});
 await dialog.getByLabel('nir source',{exact:true}).selectOption('0');
 await dialog.getByLabel('red source',{exact:true}).selectOption('0');
 await dialog.getByLabel('red band',{exact:true}).fill('2');
 const response=page.waitForResponse(r=>r.url().endsWith('/analysis/remote-sensing/run')&&r.request().method()==='POST');
 await dialog.getByRole('button',{name:'Run remote sensing',exact:true}).click();
 const result=await response;expect(result.ok()).toBeTruthy();
 expect((await result.json()).receipt.raster_summary.minimum).toBeCloseTo(.5,6);
 await expect(dialog.getByAltText('Georeferenced remote sensing preview')).toBeVisible();
 const download=page.waitForEvent('download');
 await dialog.getByRole('button',{name:'GeoTIFF',exact:true}).click();
 expect((await download).suggestedFilename()).toBe('ndvi.tif');
 await dialog.getByRole('button',{name:'Show remote raster on map'}).click();
 await expect(dialog).not.toBeVisible();
});
