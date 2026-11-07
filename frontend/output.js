// 导出载荷、打印与富文本输出事务：由入口显式注入依赖。
window.DocumentOutput = {
  create(deps) {
    const {
      document, window, FileReader, t, showStatus, documentLanguage, getCurrentMarkdown, escHtml, 
      ensureTurndown, ensureLib, toPlainText, buildDocxFromMarkdown, buildRichText, copyTextToClipboard, state,
    } = deps;
    function currentDocTitle() {
      return state.filePath && state.filePath !== 'Untitled.md' ? state.filePath.split('/').pop().replace(/\.[^.]+$/, '') : 'Untitled';
    }

    async function buildHtml() {
      const title = currentDocTitle();
      const mathCSS = await deps.MathRenderer.exportCSS(document.getElementById('content'));
      const clone = document.getElementById('content').cloneNode(true);
      clone.querySelectorAll('.frontmatter-toggle, .colgroup, colgroup,.code-copy-btn,.remote-image-bar').forEach(el => el.remove());
      clone.querySelectorAll('.task-toggle').forEach(el=>el.replaceWith(document.createTextNode(el.dataset.taskMarker||'')));
      clone.querySelectorAll('img[data-remote-src]').forEach(el=>el.setAttribute('src',el.dataset.remoteSrc));
      for (const image of clone.querySelectorAll('img[data-original-src]')) {
        if (!deps.Bridge.ready()) throw new Error(t('Local images cannot be embedded yet. Please retry.', '本地图片尚无法嵌入，请重试。'));
        const result = await deps.Bridge.call('read_image_for_export', image.getAttribute('data-original-src'), deps.documentSession.id);
        if (!result.success) throw new Error(t('Image export failed: ', '图片导出失败：') + result.error);
        image.setAttribute('src', result.data);
      }

      clone.querySelectorAll('*').forEach(el => {
        el.removeAttribute('contenteditable');
        el.removeAttribute('spellcheck');
        Array.from(el.attributes).forEach(attr => {
          if (attr.name.startsWith('data-')) el.removeAttribute(attr.name);
        });
      });
      const resources = await deps.Bridge.call('get_export_css');
      const text = clone.textContent || '';
      const lang = documentLanguage(getCurrentMarkdown());
      const headings = [...clone.querySelectorAll('h1,h2,h3')];
      let toc = '';
      if (headings.length >= 5) {
        toc = '<nav class="export-toc"><details><summary>' + t('Contents','目录') + '</summary><ul>' + headings.map((el,i) => {
          if (!el.id) el.id = 'export-heading-' + i;
          return '<li><a href="#' + escHtml(el.id) + '">' + escHtml(el.textContent) + '</a></li>';
        }).join('') + '</ul></details></nav>';
      }
      const options = await deps.Bridge.call('get_output_settings');
      if (options.hide_frontmatter) clone.querySelectorAll('.frontmatter').forEach(el => el.remove());
      const html = '<!doctype html>\n<html lang="' + lang + '"><head><meta charset="utf-8">' +
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">' +
        '<meta name="generator" content="mdPreview ' + escHtml(resources.version) + '"><title>' + escHtml(title) + '</title>' +
        '<style>' + resources.css + '\n' + mathCSS + '\nbody{margin:0;background:var(--bg);font-family:var(--font-sans)}.page{max-width:720px;margin:40px auto;padding:0 40px}.export-toc{margin-bottom:24px}</style>' +
        '</head><body><main class="page">' + toc + '<article class="markdown">' + deps.MarkdownPipeline.cleanExport(clone.innerHTML) + '</article></main></body></html>';
      return html;
    }

    // ── Export As (File menu): one native panel with a format popup ──
    async function exportAs() {
      if (!deps.Bridge.ready()) {
        showStatus(t('Export is not ready yet', '导出功能尚未就绪'), true);
        return;
      }
      try {
        const res = await deps.Bridge.call('export_as_choose', currentDocTitle() + '.md');
        if (!res || !res.success) return;
        const writeRes = await exportAsWrite(res.path, res.format);
        if (writeRes && writeRes.success) {
          showStatus(writeRes.paths ? t('Exported: ', '已导出：') + writeRes.paths.map(p => p.split('/').pop()).join('、') : (writeRes.split ? t('Exported in multiple pages/files', '已分段导出多页或多个文件') : t('Exported', '已导出')));
        } else {
          showStatus(t('Export failed: ', '导出失败：') + ((writeRes && writeRes.error) || ''), true);
        }
      } catch (err) {
        showStatus(t('Export failed: ', '导出失败：') + (err && err.message ? err.message : err), true);
      }
    }

    // Build the payload for a chosen export format and write it through the
    // native bridge. Shared by Export As and Save As (non-Markdown formats).
    // PDF/PNG capture the rendered DOM: in Source mode the textarea is only
    // viewport-tall and #content is hidden, so a capture would yield just the
    // visible area (or an empty image). We temporarily switch to Preview and
    // restore the UI after the write completes.
    async function exportAsWrite(path, format) {
      await ensureTurndown();
      if (state.outputBusy || state.closing) return { success: false, error: 'output-busy' };
      state.outputBusy = true;
      let restore;
      try {
        const options = await deps.Bridge.call('get_output_settings');
        if (format !== 'md') restore = await deps.OutputPrep.prepare(format, options);
        let content = '';
        if (format === 'md') content = getCurrentMarkdown();
        else if (format === 'txt') content = toPlainText(document.getElementById('content'));
        else if (format === 'html') content = await buildHtml();
        else if (format === 'docx') content = await buildDocxFromMarkdown(getCurrentMarkdown(), {root:document.getElementById('content'),options,title:currentDocTitle(),documentId:deps.documentSession.id});
        if (content === null) return { success: false, error: 'conversion-failed' };
        let pageSize = null;
        if (format === 'png') {
          const el = document.querySelector('.page');
          const box = el.getBoundingClientRect();
          pageSize = { x: box.left + window.scrollX, y: box.top + window.scrollY, width: Math.ceil(box.width), height: Math.ceil(el.scrollHeight), options };
        }
        if (format === 'pdf') {
          // createPDF defaults to the visible viewport; pass the full document
          // size so everything is captured. +100px keeps the last line off the
          // page edge. `breaks` lists the top edge of every block element so the
          // A4 slicing lands on element boundaries instead of mid-line.
          pageSize = {
            width: Math.max(document.body.scrollWidth, window.innerWidth),
            height: document.body.scrollHeight + 100,
          };
        }
        if (format === 'pdf') {
          pageSize.options = options;
          pageSize.meta = { title: currentDocTitle(), author: '', pageNumbers: options.page_numbers,
            links: [...document.querySelectorAll('#content a[href]')].filter(el => /^https?:/.test(el.href)).map(el => ({text: el.textContent.trim(), url: el.href})),
            headings: [...document.querySelectorAll('#content h1,#content h2,#content h3')].map(el => ({level:Number(el.tagName[1]),text:el.textContent.trim()})) };
        }
        return await deps.Bridge.call('export_as_write', path, format, content, pageSize);
      } finally {
        if (restore) restore();
        state.outputBusy = false;
      }
    }


    async function printDocument() {
      if (state.outputBusy || state.closing) return { success: false, error: 'output-busy' };
      state.outputBusy = true;
      let restore;
      try {
        const opts = await deps.Bridge.call('get_output_settings');
        restore = await deps.OutputPrep.prepare('print', opts);
        const result = await deps.Bridge.call('print_document', opts);
        if (!result.success && !result.cancelled) showStatus(t('Print failed', '打印失败'), true);
        return result;
      } catch (error) {
        showStatus(t('Print failed', '打印失败'), true);
        return { success: false, error: 'print-failed' };
      } finally {
        if (restore) restore();
        state.outputBusy = false;
      }
    }

    async function copyAsRichText() {
      if (state.outputBusy || state.closing) return {success:false,error:'output-busy'};
      const root=document.getElementById('content'), selection=window.getSelection();
      const range=!state.isSource && selection && !selection.isCollapsed && selection.rangeCount && root.contains(selection.getRangeAt(0).commonAncestorContainer) ? selection.getRangeAt(0).cloneRange() : null;
      state.outputBusy=true;let restore;
      try {
        restore=await deps.OutputPrep.prepare('richtext',await deps.Bridge.call('get_output_settings'));
        const payload=await buildRichText(root,range);
        const result=await deps.Bridge.call('set_clipboard_rich',payload.html,payload.plain);
        if(!result.success)throw new Error('clipboard-write-failed');
        showStatus(t('Copied as rich text','已复制为富文本'));return result;
      }catch(error){showStatus(t('Copy failed','复制失败'),true);return {success:false,error:'clipboard-write-failed'};}
      finally{
        try { if(restore)restore(); }
        finally {
          state.outputBusy=false;
          if(range&&!state.closing){selection.removeAllRanges();selection.addRange(range);}
        }
      }
    }

    async function copyAsMarkdown() {
      await ensureTurndown();
      let text=getCurrentMarkdown();
      const selection=window.getSelection();
      if(state.isSource){const ta=document.getElementById('textarea');if(ta.selectionEnd>ta.selectionStart)text=ta.value.slice(ta.selectionStart,ta.selectionEnd);}
      else if(selection && !selection.isCollapsed && selection.rangeCount && document.getElementById('content').contains(selection.getRangeAt(0).commonAncestorContainer)){
        const holder=document.createElement('div');holder.append(selection.getRangeAt(0).cloneContents());text=deps.turndownService.turndown(holder);
      }
      const success=await copyTextToClipboard(text);showStatus(success?t('Copied as Markdown','已复制为 Markdown'):t('Copy failed','复制失败'),!success);return success;
    }


    return {
      currentDocTitle, buildHtml, buildDocx, exportAs, exportAsWrite, printDocument, copyAsRichText, 
      copyAsMarkdown,
    };
  }
};
