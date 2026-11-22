import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import {coveragePlugin,coverageEnabled} from './scripts/instrument.mjs';

// This TS project intentionally omits @types/node; Vite executes this config in Node.
declare const process:{env:Record<string,string|undefined>};

// Local-only development proxy; the production deployment must route /api
// to its own API service. Bind the dev server to loopback.
const proxy={'/api':{target:'http://127.0.0.1:8000',changeOrigin:true,
  rewrite:(path:string)=>path.replace(/^\/api(?=\/|$)/,'')}};

// The launcher injects its checked-out git SHA. CI supplies GITHUB_SHA.
 // Avoid Node imports here: the frontend tsconfig intentionally excludes Node types.
const frontendRevision=process.env.VITE_GEOFATHOM_REVISION ??
  process.env.GITHUB_SHA?.slice(0,7) ?? 'unavailable';

export default defineConfig({
  define:{'import.meta.env.VITE_GEOFATHOM_REVISION':JSON.stringify(frontendRevision)},
  plugins: [...(coverageEnabled?[coveragePlugin()]:[]),react()],
  server: { host: '127.0.0.1', port: 5173, strictPort:true, proxy },
  preview:{host:'127.0.0.1',proxy},
  test: {env:{VITE_API_URL:'http://localhost:8000'},setupFiles:coverageEnabled?['./scripts/unit-coverage.ts']:[]},
});
