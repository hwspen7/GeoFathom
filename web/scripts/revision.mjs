// Resolve the actual checked-out revision for every Vite entry point, including
// a bare `npx playwright test` on Windows without a launcher script.
// Never emit a fabricated revision when neither Git nor CI metadata exists.
import { execFileSync } from 'node:child_process';

const valid = value => (
  typeof value === 'string' && /^[0-9a-f]{7,40}$/i.test(value.trim())
    ? value.trim().toLowerCase().slice(0,12)
    : null
);

export function resolveFrontendRevision(env = process.env) {
  const explicitlyProvided = valid(env.VITE_GEOFATHOM_REVISION);
  if (explicitlyProvided) return explicitlyProvided;
  try {
    const checkedOut = execFileSync('git', ['rev-parse', '--verify', 'HEAD'], {
      cwd: new URL('../../', import.meta.url),
      encoding: 'utf8',
      timeout: 2500,
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'ignore'],
    });
    const commit = valid(checkedOut);
    if (commit) return commit;
  } catch {
    // Exported source archives can lack .git; CI metadata is the fallback.
  }
  return valid(env.GITHUB_SHA) ?? 'unavailable';
}
