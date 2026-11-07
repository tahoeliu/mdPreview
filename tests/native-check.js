(async () => {
  const checks = [];
  const check = (condition, name) => { if (!condition) throw new Error(name); checks.push(name); };
  try {
    await ensureTurndown();
    const paths = await pywebview.api.selftest_paths();
    if (!isSource) await toggleView();
    const textarea = document.getElementById('textarea');
    const value = '# Native test\n\n中文 日本語 العربية café 🧪\n\n```bash\necho $HOME $USER\n```';
    textarea.value = value; textarea.dispatchEvent(new Event('input'));
    check((await saveFile()).saved, 'Native bridge saves current revision');
    check(getCurrentMarkdown() === value, 'Unicode source remains intact');
    await toggleView();
    check(document.querySelector('#content code').textContent.includes('$HOME $USER'), 'WKWebView code preservation');
    await toggleView();
    textarea.value = value + '\n\nNEW CONTENT'; textarea.dispatchEvent(new Event('input'));
    check((await exportAsWrite(paths.html, 'html')).success, 'Native HTML export from latest source');
    check((await exportAsWrite(paths.pdf, 'pdf')).success, 'WKWebView PDF export');
    check((await saveFile()).saved, 'Final Markdown save');
    await pywebview.api.native_integrity_completed({success:true, checks});
  } catch (error) {
    await pywebview.api.native_integrity_completed({success:false, checks, error:String(error && error.stack || error)});
  }
})();
