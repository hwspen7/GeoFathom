import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import {coveragePlugin,coverageEnabled} from './scripts/instrument.mjs';
import {resolveFrontendRevision} from './scripts/revision.mjs';

// This TS project intentionally omits @types/node; Vite executes this config in Node.
declare const process:{env:Record<string,string|undefined>};

// Local-only development proxy; the production deployment must route /api
// to its own API service. Bind the dev server to loopback.
const proxy={'/api':{target:'http://127.0.0.1:8000',changeOrigin:true,
  rewrite:(path:string)=>path.replace(/^\/api(?=\/|$)/,'')}};

// All entry points (launcher, Vite dev server, Playwright and CI) report a
// real checked-out revision, even when no environment variable was supplied.
const frontendRevision=resolveFrontendRevision(process.env);

export default defineConfig({
  define:{'import.meta.env.VITE_GEOFATHOM_REVISION':JSON.stringify(frontendRevision)},
  plugins: [...(coverageEnabled?[coveragePlugin()]:[]),react()],
  server: { host: '127.0.0.1', port: 5173, strictPort:true, proxy },
  preview:{host:'127.0.0.1',proxy},
  test: {env:{VITE_API_URL:'http://localhost:8000'},setupFiles:coverageEnabled?['./scripts/unit-coverage.ts']:[]},
});
