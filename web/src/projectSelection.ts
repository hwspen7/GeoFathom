/** Active project belongs to the current browser tab, not the server's sort order. */
const KEY = 'geofathom-active-project';

export function storedProject(): string {
  try { return window.sessionStorage.getItem(KEY) ?? ''; }
  catch { return ''; }
}

export function rememberProject(id: string): void {
  try {
    if (id) window.sessionStorage.setItem(KEY, id);
    else window.sessionStorage.removeItem(KEY);
  } catch { /* A browser may block session storage; selection still works in memory. */ }
}

export function restoreProject(list: ReadonlyArray<{id:string}>, preferred: string): string {
  return list.some(project => project.id === preferred) ? preferred : (list[0]?.id ?? '');
}
