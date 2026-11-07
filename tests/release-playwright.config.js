const {defineConfig}=require('@playwright/test');
module.exports=defineConfig({testDir:__dirname,testMatch:['perf.spec.js','accessibility.spec.js'],forbidOnly:true,retries:0,workers:1,reporter:'list',projects:[{name:'webkit',use:{browserName:'webkit'}}]});
