/* 此脚本在应用和第三方库之前执行；无头导出拒绝网络与对话框。 */
window.HEADLESS_EXPORT = new URLSearchParams(location.search).get('headless') === '1';
if (window.HEADLESS_EXPORT) {
  const policy=document.createElement('meta');policy.httpEquiv='Content-Security-Policy';
  policy.content="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src file: data: blob:; font-src 'self' data:; connect-src 'none'; frame-src 'none'; object-src 'none'";
  document.head.append(policy);
  window.alert=()=>{throw new Error('headless-dialog-forbidden');};
  window.confirm=()=>false;
  window.prompt=()=>null;
  window.open=()=>null;
}
window.runHeadlessExport=async function(data){
 if(!window.HEADLESS_EXPORT||!data.headless)return;
 try{
  await loadContent(data.path,data.content,720,false,false,data);
  const result=await exportAsWrite(data.outputPath,data.outputFormat);
  await Bridge.call('headless_finish',result?.success===true);
 }catch(error){await Bridge.callSafe('headless_finish',false);}
};
