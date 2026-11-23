/** Open the transient project/search drawer only when needed by a UI test.
 * Project switching and the searchable object tree stay visible outside it.
 */
import {expect,type Page} from '@playwright/test';

/** Follow the rendered navigation at both desktop and compact widths. */
export async function activateWorkspaceModule(page:Page,name:string,expanded=false){
 const navigation=page.getByRole('navigation',{name:'Workspace tools'});
 await expect(navigation).toBeVisible();
 const compact=navigation.getByLabel('Workspace module',{exact:true});
 if(await compact.isVisible())await compact.selectOption({label:name});
 else await navigation.getByRole('button',{name,exact:true}).click();
 await expectWorkspaceModule(page,name);
 if(expanded)await page.getByRole('button',{name:'Open full operations view',exact:true}).click();
}

export async function expectWorkspaceModule(page:Page,name:string){
 const navigation=page.getByRole('navigation',{name:'Workspace tools'});
 const compact=navigation.getByLabel('Workspace module',{exact:true});
 if(await compact.isVisible())await expect(compact.locator('option:checked')).toHaveText(name);
 else await expect(navigation.getByRole('button',{name,exact:true})).toHaveAttribute('aria-pressed','true');
}
export async function openProjectDrawer(page:Page,tab:'project'|'layers'|'search'='project',expanded=false){
 const drawer=page.getByLabel('Project and layers',{exact:true});
 if(!(await drawer.isVisible())){
   const menu=page.locator('.gis-workspace-menu > summary');
   if(!(await page.locator('.gis-workspace-menu[open]').count()))await menu.click();
   await page.locator('.gis-workspace-menu button').filter({hasText:'Project / Layers'}).click();
   await menu.click();
 }
 await drawer.getByRole('tab',{name:tab==='project'?'Project':tab==='layers'?'Layers':'Search',exact:true}).click();
 if(expanded&&await page.getByRole('button',{name:'Open full project view',exact:true}).isVisible())
   await page.getByRole('button',{name:'Open full project view',exact:true}).click();
}

export async function closeProjectDrawer(page:Page){
 const drawer=page.getByLabel('Project and layers',{exact:true});
 if(!(await drawer.isVisible()))return;
 const closeExpanded=page.getByRole('button',{name:'Close full project view',exact:true});
 if(await closeExpanded.isVisible())await closeExpanded.click();
 const menu=page.locator('.gis-workspace-menu > summary');
 if(!(await page.locator('.gis-workspace-menu[open]').count()))await menu.click();
 await page.locator('.gis-workspace-menu button').filter({hasText:'Project / Layers'}).click();
 await menu.click();
}

export async function openFileMenu(page:Page){
 const panel=page.locator('.gis-file-menu');
 if(!(await page.locator('.gis-file-menu[open]').count()))await panel.locator('summary').click();
}
