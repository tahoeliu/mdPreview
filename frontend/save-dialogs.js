// 关闭确认与保存冲突交互：由入口显式注入依赖。
window.SaveDialogs = {
  create(deps) {
    const {
      document, t, escHtml, ensureTurndown, pushContentToPython, forceCloseWindow, saveFile, saveAsFile, 
      setModal, closeModal, showStatus, state,
    } = deps;
    async function promptBeforeClose(force = false) {
      await ensureTurndown();
      if (state.isDirty) await pushContentToPython(true);
      if (!force && !state.isDirty) {
        forceCloseWindow();
        return;
      }
      if (state.closePromptVisible) return;
      state.closePromptVisible = true;
      // Native TextEdit-style dialog (keep question + name/location + red
      // Delete / gray Cancel / blue Save) shown from the Python side. The
      // in-page modal below is only a fallback for non-Cocoa environments.
      if (deps.Bridge.ready()) {
        deps.Bridge.call('native_save_prompt')
          .then(async (res) => {
            state.closePromptVisible = false;
            if (!res || !res.action) return;
            if (res.action === 'save') {
              if (res.path && res.path !== state.filePath) state.filePath = res.path;
              const result = await saveFile(false, null, { closeOnSuccess: true });
              if (result && result.saved && !state.isDirty) {
                await forceCloseWindow();
              } else {
                state.closePromptVisible = false;
              }
            } else if (res.action === 'delete') {
              await forceCloseWindow(true);
            }
            // cancel: keep the window open and do nothing
          })
          .catch(() => { state.closePromptVisible = false; });
        return;
      }
      const name = state.filePath && state.filePath !== 'Untitled.md' ? state.filePath.split('/').pop() : 'Untitled.md';
      const bodyHtml = '<p>' + t('Do you want to save the changes you made to {name}?', '是否保存对 {name} 所做的更改？').replace('{name}', '<strong>' + escHtml(name) + '</strong>') + '</p>' +
        '<p style="color:#666;margin-bottom:0;">' + t('Your changes will be lost if you do not save them.', '若不保存，更改将丢失。') + '</p>';
      const actionsHtml = '<button class="modal-button secondary" id="closeCancel">' + t('Cancel', '取消') + '</button>' +
        '<button class="modal-button danger" id="closeDiscard">' + t("Don't Save", '不保存') + '</button>' +
        '<button class="modal-button" id="closeSave">' + t('Save', '保存') + '</button>';
      setModal(t('Save Changes?', '保存更改？'), bodyHtml, actionsHtml);
      document.getElementById('closeCancel').addEventListener('click', () => {
        state.closePromptVisible = false;
        closeModal();
      });
      document.getElementById('closeDiscard').addEventListener('click', async () => {
        closeModal();
        await forceCloseWindow(true);
      });
      document.getElementById('closeSave').addEventListener('click', async () => {
        closeModal();
        state.closePromptVisible = false;
        const result = await saveFile(false, null, { closeOnSuccess: true });
        if (result && result.saved && !state.isDirty) await forceCloseWindow();
      });
    }

    function showSaveConflictDialog(path, markdown, options = {}) {
      const finishOverwrite = async () => {
        const result = await saveFile(true);
        if (options.closeOnSuccess && result && result.saved) await forceCloseWindow();
      };
      const finishSaveAs = async () => {
        const result = await saveAsFile();
        if (options.closeOnSuccess && result && result.saved) await forceCloseWindow();
      };
      const finishCancel = () => {
        showStatus(t('Save cancelled', '已取消保存'));
        if (options.closeOnCancel) promptBeforeClose();
      };
      // Native macOS sheet (Save Current / Save As / Cancel); the HTML modal
      // below stays as a fallback for non-Cocoa environments.
      if (deps.Bridge.ready()) {
        deps.Bridge.call('native_conflict_prompt', path)
          .then((res) => {
            if (!res || !res.action) return finishCancel();
            if (res.action === 'overwrite') return finishOverwrite();
            if (res.action === 'save_as') return finishSaveAs();
            return finishCancel();
          })
          .catch(() => finishCancel());
        return;
      }
      const name = path ? path.split('/').pop() : t('this file', '此文件');
      const bodyHtml = '<p>' + t('The file {name} has changed on disk since it was opened or last saved.', '文件 {name} 自打开或上次保存以来已在磁盘上发生变化。').replace('{name}', '<strong>' + escHtml(name) + '</strong>') + '</p>' +
        '<p>' + t('Choose how to continue:', '请选择如何继续：') + '</p>' +
        '<ul style="margin:8px 0 0 18px;padding:0;color:#555;line-height:1.5;">' +
        '<li><strong>' + t('Save As', '另存为') + '</strong> ' + t('keeps the changed file untouched and saves this document to a new path.', '保持磁盘文件不变，将本文档保存到新路径。') + '</li>' +
        '<li><strong>' + t('Save Current', '保存当前') + '</strong> ' + t('overwrites the file on disk with the content in this window.', '用当前窗口内容覆盖磁盘文件。') + '</li>' +
        '<li><strong>' + t('Cancel', '取消') + '</strong> ' + t('stops saving.', '停止保存。') + '</li>' +
        '</ul>';
      const actionsHtml = '<button class="modal-button secondary" id="conflictCancel">' + t('Cancel', '取消') + '</button>' +
        '<button class="modal-button" id="conflictSaveAs">' + t('Save As...', '另存为…') + '</button>' +
        '<button class="modal-button danger" id="conflictOverwrite">' + t('Save Current', '保存当前') + '</button>';
      setModal(t('Save Conflict', '保存冲突'), bodyHtml, actionsHtml);
      document.getElementById('conflictCancel').addEventListener('click', () => {
        closeModal();
        finishCancel();
      });
      document.getElementById('conflictSaveAs').addEventListener('click', () => {
        closeModal();
        finishSaveAs();
      });
      document.getElementById('conflictOverwrite').addEventListener('click', () => {
        closeModal();
        finishOverwrite();
      });
    }


    return {
      promptBeforeClose, showSaveConflictDialog,
    };
  }
};
