const {defineConfig,devices}=require('@playwright/test');
module.exports=defineConfig({
  testDir:'./WorkSpace/tests/e2e',timeout:60000,fullyParallel:false,workers:1,
  outputDir:'WorkSpace/test-results',
  reporter:[['list'],['json',{outputFile:'WorkSpace/browser-results.json'}]],
  use:{baseURL:'http://127.0.0.1:29381',screenshot:'only-on-failure',trace:'retain-on-failure'},
  projects:[{name:'chromium',use:{...devices['Desktop Chrome']}},{name:'webkit',use:{...devices['Desktop Safari']}}],
  webServer:{command:'node scripts/test-server.cjs',url:'http://127.0.0.1:29381',reuseExistingServer:false,timeout:10000}
});
