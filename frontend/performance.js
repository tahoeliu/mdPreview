/* 仅保留阶段名称与耗时，不记录文档内容、路径或标题。 */
window.RenderPerformance=(()=>{
 const samples=[];let serial=0;
 function start(stage){
  const id='mdpreview-'+(++serial),begin=performance.now();
  performance.mark?.(id);
  return ()=>{const duration=performance.now()-begin;samples.push({stage,duration});if(samples.length>200)samples.shift();
   if(performance.measure){performance.measure(stage,id);performance.clearMarks(id);performance.clearMeasures(stage);}return duration;};
 }
 function sync(stage,fn){const end=start(stage);try{return fn();}finally{end();}}
 async function asyncStage(stage,fn){const end=start(stage);try{return await fn();}finally{end();}}
 return {start,sync,async:asyncStage,snapshot:()=>samples.map(x=>({...x}))};
})();
window.LazyRender=(()=>{
 let observer=null,generation=0;const jobs=new Map();
 function reset(){generation++;observer?.disconnect();observer=null;jobs.clear();}
 function run(node){const job=jobs.get(node);if(!job)return Promise.resolve();if(job.promise)return job.promise;
  const current=generation;observer?.unobserve(node);
  job.promise=Promise.resolve().then(()=>{if(current===generation&&node.isConnected)return job.render(node);}).finally(()=>{if(jobs.get(node)===job)jobs.delete(node);});
  return job.promise;
 }
 function observe(nodes,render){
  if(!observer&&typeof IntersectionObserver!=='undefined')observer=new IntersectionObserver(entries=>{
   for(const entry of entries)if(entry.isIntersecting)run(entry.target).catch(()=>showStatus(t('Rendering failed','渲染失败'),true));
  },{root:document.querySelector('.scroll-wrap'),rootMargin:'800px'});
  for(const node of nodes){if(jobs.has(node))continue;jobs.set(node,{render});if(observer)observer.observe(node);}
  return observer?Promise.resolve():flush();
 }
 async function flush(){await Promise.all([...jobs.keys()].map(run));}
 return {reset,observe,flush,pending:()=>jobs.size};
})();
