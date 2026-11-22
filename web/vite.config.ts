import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import {coveragePlugin,coverageEnabled} from './scripts/instrument.mjs';

export default defineConfig({
  plugins: [...(coverageEnabled?[coveragePlugin()]:[]),react()],
  server: { host: '127.0.0.1', port: 5173 },
  test: {setupFiles:coverageEnabled?['./scripts/unit-coverage.ts']:[]},
});
