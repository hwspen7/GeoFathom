/** Open the transient project/search drawer only when needed by a UI test.
 * Project switching and the searchable object tree stay visible outside it.
 */
import type {Page} from '@playwright/test';
export async function openProjectDrawer(page:Page,tab:'project'|'layers'|'search'='project'){
 const drawer=page.getByLabel('Project and layers',{exact:true});
 if(!(await drawer.isVisible())){
   const menu=page.locator('.gis-workspace-menu > summary');
   if(!(await page.locator('.gis-workspace-menu[open]').count()))await menu.click();
   await page.locator('.gis-workspace-menu button').filter({hasText:'Project / Layers'}).click();
 }
 await drawer.getByRole('tab',{name:tab==='project'?'Project':tab==='layers'?'Layers':'Search',exact:true}).click();
}

export async function closeProjectDrawer(page:Page){
 const drawer=page.getByLabel('Project and layers',{exact:true});
 if(!(await drawer.isVisible()))return;
 const menu=page.locator('.gis-workspace-menu > summary');
 if(!(await page.locator('.gis-workspace-menu[open]').count()))await menu.click();
 await page.locator('.gis-workspace-menu button').filter({hasText:'Project / Layers'}).click();
}

export async function openFileMenu(page:Page){
 const panel=page.locator('.gis-file-menu');
 if(!(await page.locator('.gis-file-menu[open]').count()))await panel.locator('summary').click();
}
