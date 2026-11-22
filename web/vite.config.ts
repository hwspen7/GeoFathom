import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import {coveragePlugin} from './scripts/instrument.mjs';

export default defineConfig({
  plugins: [...(process.env.GEOFATHOM_WEB_COVERAGE==='1'?[coveragePlugin()]:[]),react()],
  server: { host: '127.0.0.1', port: 5173 },
  test: {setupFiles:process.env.GEOFATHOM_WEB_COVERAGE==='1'?['./scripts/unit-coverage.ts']:[]},
});
