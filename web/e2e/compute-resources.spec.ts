import {test,expect} from './coverage-fixture';

test('Settings exposes live backend compute resources and effective limits',async({page})=>{
 await page.goto('/');
 await page.locator('.gis-settings > summary').click();
 await page.locator('.gis-settings details').filter({has:page.getByText('Computing Resources',{exact:true})}).locator('summary').click();
 await expect(page.getByLabel('Compute resource mode')).toHaveValue('automatic');
 await expect(page.getByRole('table',{name:'Effective terrain cell limits'})).toBeVisible();
 await expect(page.getByText(/Backend CPU:.*logical cores/)).toBeVisible();
 // Backend persistence is independently tested by the Python API tests.
 // Do not change shared server settings while other browser workers run.
 await page.getByLabel('Compute resource mode').selectOption('manual');
 await expect(page.getByLabel('Compute memory percent')).toBeVisible();
 await expect(page.getByLabel('Local surfaces cell ceiling')).toBeVisible();
 await page.getByLabel('Compute resource mode').selectOption('automatic');
 await expect(page.getByLabel('Compute memory percent')).toHaveCount(0);
});
