import { defineConfig } from '@playwright/test';
export default defineConfig({
 testDir:'./tests',testMatch:'*.spec.ts',fullyParallel:true,
 use:{baseURL:'http://127.0.0.1:4173',viewport:{width:360,height:800},screenshot:'only-on-failure',
  launchOptions:{executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH}},
 webServer:{command:'node tests/serve.mjs',url:'http://127.0.0.1:4173',reuseExistingServer:false},
 reporter:[['list'],['html',{open:'never'}]],
});
