import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import {execFileSync} from 'node:child_process';
import {dirname,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {coveragePlugin,coverageEnabled} from './scripts/instrument.mjs';

// Local-only development proxy; the production deployment must route /api
// to its own API service. Bind the dev server to loopback.
const proxy={'/api':{target:'http://127.0.0.1:8000',changeOrigin:true,
  rewrite:(path:string)=>path.replace(/^\/api(?=\/|$)/,'')}};

// Surface the actual frontend commit, so a stale Vite process can be identified.
let frontendRevision='unknown';
try{
  frontendRevision=execFileSync('git',['rev-parse','--short','HEAD'],{
    cwd:resolve(dirname(fileURLToPath(import.meta.url)),'..'),encoding:'utf8',timeout:2000,
  }).trim();
}catch{/* Source archives may legitimately omit .git. */}

export default defineConfig({
  define:{'import.meta.env.VITE_GEOFATHOM_REVISION':JSON.stringify(frontendRevision)},
  plugins: [...(coverageEnabled?[coveragePlugin()]:[]),react()],
  server: { host: '127.0.0.1', port: 5173, strictPort:true, proxy },
  preview:{host:'127.0.0.1',proxy},
  test: {env:{VITE_API_URL:'http://localhost:8000'},setupFiles:coverageEnabled?['./scripts/unit-coverage.ts']:[]},
});
