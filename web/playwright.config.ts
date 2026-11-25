import { defineConfig,devices } from '@playwright/test';
import {resolve} from 'node:path';

// Never silently test against a user's already-running frontend or backend.
// Reuse is an explicit local debugging option only; CI always starts fresh.
const reuseExistingServer=process.env.GEOFATHOM_E2E_REUSE_EXISTING==='1'&&!process.env.CI;
const testDatabase=process.env.GEOFATHOM_E2E_DATABASE_PATH||'data/e2e-geofathom.sqlite';
const testImagery=resolve('..',testDatabase)+'.imagery';

export default defineConfig({
  testDir:'./e2e',
  timeout:process.env.CI ? 90_000 : 45_000,
  expect:{timeout:12_000},
  fullyParallel:false,
  // Exercise independent browser sessions against the same backend in CI.
  workers:process.env.GEOFATHOM_E2E_WORKERS ? Number(process.env.GEOFATHOM_E2E_WORKERS) : (process.env.CI?1:undefined),
  retries:0,
  reporter:process.env.CI?'github':'list',
  use:{
    baseURL:'http://localhost:5173',
    ...devices['Desktop Chrome'],
    headless:true,
    launchOptions:{executablePath:process.env.GEOFATHOM_E2E_CHROMIUM_PATH||undefined,
      args:['--use-gl=angle','--use-angle=swiftshader','--enable-webgl',
                        '--disable-dev-shm-usage']},
    trace:'retain-on-failure',
    screenshot:'only-on-failure',
  },
  webServer:[
    {
      command:'python -m uvicorn core.main:app --host 127.0.0.1 --port 8000',
      // Liveness alone can expose a fresh, uninitialized SQLite database.
      // Readiness initializes and verifies storage before browsers start.
      cwd:'..',url:'http://127.0.0.1:8000/health/ready',
      timeout:90_000,reuseExistingServer,
      stderr:'pipe',
      env:{...process.env,
        GEOFATHOM_DATABASE_PATH:testDatabase,
        GEOFATHOM_IMAGERY_DIR:testImagery,
        GEOFATHOM_VISION_MODELS_DIR:resolve('..',testDatabase)+'.models',
        GEOFATHOM_BUILDING_RESULTS_DIR:resolve('..',testDatabase)+'.buildings',
        GEOFATHOM_BUILDING_DATASETS_DIR:resolve('..',testDatabase)+'.building-datasets',
        GEOFATHOM_BUILDING_RESEARCH_RESULTS_DIR:resolve('..',testDatabase)+'.building-research',
        GEOFATHOM_CORS_ORIGINS:'http://localhost:5173',
      },
    },
    {
      command:'npm run dev -- --host 127.0.0.1',
      cwd:'.',url:'http://localhost:5173',
      timeout:90_000,reuseExistingServer,
    },
  ],
});
