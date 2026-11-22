import { defineConfig,devices } from '@playwright/test';

const freshServer = !!process.env.CI || process.env.GEOFATHOM_E2E_FRESH === '1';

export default defineConfig({
  testDir:'./e2e',
  timeout:45_000,
  expect:{timeout:12_000},
  fullyParallel:false,
  workers:process.env.CI?1:undefined,
  retries:process.env.CI?1:0,
  reporter:process.env.CI?'github':'list',
  use:{
    baseURL:'http://localhost:5173',
    ...devices['Desktop Chrome'],
    headless:true,
    launchOptions:{args:['--use-gl=angle','--use-angle=swiftshader','--enable-webgl',
                        '--disable-dev-shm-usage']},
    trace:'retain-on-failure',
    screenshot:'only-on-failure',
  },
  webServer:[
    {
      command:'python -m uvicorn core.main:app --host 127.0.0.1 --port 8000',
      cwd:'..',url:'http://127.0.0.1:8000/health',
      timeout:90_000,reuseExistingServer:!freshServer,
      env:{...process.env,
        GEOFATHOM_DATABASE_PATH:process.env.GEOFATHOM_E2E_DATABASE_PATH || 'data/e2e-geofathom.sqlite',
        GEOFATHOM_CORS_ORIGINS:'http://localhost:5173',
      },
    },
    {
      command:'npm run dev -- --host 127.0.0.1',
      cwd:'.',url:'http://localhost:5173',
      timeout:90_000,reuseExistingServer:!freshServer,
    },
  ],
});
