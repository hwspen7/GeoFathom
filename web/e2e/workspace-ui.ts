/** Open the transient project/search drawer only when needed by a UI test.
 * Project switching and the searchable object tree stay visible outside it.
 */
import type {Page} from '@playwright/test';
export async function openProjectDrawer(page:Page){
 const button=page.getByRole('button',{name:'Toggle project and layers'});
 if(await button.getAttribute('aria-expanded')!=='true')await button.click();
}

export async function closeProjectDrawer(page:Page){
 const button=page.getByRole('button',{name:'Toggle project and layers'});
 if(await button.getAttribute('aria-expanded')==='true')await button.click();
}
