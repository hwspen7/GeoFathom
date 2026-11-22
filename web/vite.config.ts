import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import {coveragePlugin,coverageEnabled} from './scripts/instrument.mjs';

// Local-only development proxy; the production deployment must route /api
// to its own API service. Bind the dev server to loopback.
const proxy={'/api':{target:'http://127.0.0.1:8000',changeOrigin:true,
  rewrite:(path:string)=>path.replace(/^\/api(?=\/|$)/,'')}};

export default defineConfig({
  plugins: [...(coverageEnabled?[coveragePlugin()]:[]),react()],
  server: { host: '127.0.0.1', port: 5173, strictPort:true, proxy },
  preview:{host:'127.0.0.1',proxy},
  test: {env:{VITE_API_URL:'http://localhost:8000'},setupFiles:coverageEnabled?['./scripts/unit-coverage.ts']:[]},
});
