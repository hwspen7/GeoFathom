/** Active project belongs to the current browser tab, not the server's sort order. */
const KEY = 'geofathom-active-project';
const LOCAL = '@local';

export function storedProject(): string {
  try { return window.sessionStorage.getItem(KEY) ?? ''; }
  catch { return ''; }
}

export function rememberProject(id: string): void {
  try {
    if (id) window.sessionStorage.setItem(KEY, id);
    else window.sessionStorage.setItem(KEY, LOCAL);
  } catch { /* A browser may block session storage; selection still works in memory. */ }
}

export function restoreProject(list: ReadonlyArray<{id:string}>, preferred: string): string {
  if(preferred===LOCAL)return '';
  return list.some(project => project.id === preferred) ? preferred : (list[0]?.id ?? '');
}
