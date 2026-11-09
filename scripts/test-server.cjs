const http=require('node:http'),fs=require('node:fs'),path=require('node:path');
const root=path.resolve(__dirname,'..');
const types={'.js':'text/javascript','.html':'text/html','.css':'text/css','.png':'image/png'};
http.createServer((req,res)=>{
  let relative;
  try{relative=decodeURIComponent(req.url.split('?')[0]);}catch(error){res.writeHead(400).end();return;}   // a malformed URL must not take the server down
  const file=path.resolve(root,'.'+(relative==='/'?'/index.html':relative));
  if(!file.startsWith(root+path.sep)||relative.includes('/.')||relative.includes('WorkSpace')||relative.includes('node_modules')) {res.writeHead(403).end();return;}
  fs.readFile(file,(error,data)=>{if(error){res.writeHead(404).end();return;}res.setHeader('Content-Type',types[path.extname(file)]||'application/octet-stream');res.end(data);});
}).listen(29381,'127.0.0.1');
process.on('uncaughtException',error=>{console.error(error);});
