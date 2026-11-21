import {expect,test} from '@playwright/test';

const tile='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/ZecAAAAASUVORK5CYII=';
test.beforeEach(async({page})=>{
  await page.route('**/tile.openstreetmap.org/**',route=>
    route.fulfill({status:200,contentType:'image/png',body:Buffer.from(tile,'base64')}));
});

test('GeoAI controls expose distinct spectral, change and model workflows',async({page})=>{
  await page.goto('/');
  await page.getByText('GeoAI raster analysis & change detection').click();
  const mode=page.getByLabel('GeoAI analysis operation');
  await expect(mode).toBeVisible();
  await expect(page.getByRole('button',{name:'Run georeferenced analysis'})).toBeDisabled();
  await mode.selectOption('spectral_change');
  await expect(page.getByLabel('Second date georeferenced image')).toBeVisible();
  await expect(page.getByLabel('Spectral first band')).toBeVisible();
  await mode.selectOption('spectral_index');
  await expect(page.getByLabel('Spectral index')).toBeVisible();
  await page.getByLabel('Spectral index').selectOption('ndwi');
  await expect(page.getByLabel('Spectral first band')).toHaveValue('2');
  await page.getByLabel('Process full image at native pixel resolution').check();
  await expect(page.getByLabel('GeoAI tile size')).toBeVisible();
  await expect(page.getByLabel('GeoAI tile memory budget')).toHaveValue('32');
  await expect(page.getByLabel('GeoAI pixel processing limit')).toHaveValue('16777216');
  await expect(page.getByLabel('GeoAI processing resolution')).toHaveCount(0);
  await mode.selectOption('semantic_segmentation');
  await expect(page.getByLabel('Local ONNX vision model')).toBeVisible();
  await expect(page.getByText(/No model is silently downloaded/)).toBeVisible();
});
