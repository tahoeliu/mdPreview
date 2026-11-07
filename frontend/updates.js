// 更新状态反馈与安装交互：由入口显式注入依赖。
window.UpdateFeedback = {
  create(deps) {
    const {
      document, t, showStatus, pushContentToPython, state,
    } = deps;
    let _updateBubbleDismissed = false;

    function setUpdateBubbleText(text) {
      const el = document.getElementById('updateBubble');
      const txt = el ? el.querySelector('.update-bubble-text') : null;
      if (txt) txt.textContent = text;
    }

    function setUpdateProgress(percent) {
      const bar = document.getElementById('updateProgressBar');
      if (bar) bar.style.width = Math.max(0, Math.min(100, percent || 0)) + '%';
    }

    function showUpdateBubble() {
      if (_updateBubbleDismissed) return;
      const el = document.getElementById('updateBubble');
      if (el) {
        el.classList.remove('downloading');
        el.classList.add('visible');
        setUpdateProgress(0);
        setUpdateBubbleText(t('Update available, click to install...', '有新版本可用，点击安装…'));
      }
    }

    function showUpdateDownloadProgress(percent) {
      _updateBubbleDismissed = false;
      const el = document.getElementById('updateBubble');
      const p = Math.max(0, Math.min(100, Math.round(percent || 0)));
      if (el) {
        el.classList.remove('installing');
        el.classList.add('visible', 'downloading');
        setUpdateProgress(p);
        setUpdateBubbleText(t('Downloading update... ', '正在下载更新… ') + p + '%');
      }
    }

    function showUpdateDownloadFailed(code, detail) {
      // `code` comes from the Python updater: 'network' | 'incomplete' |
      // 'mount' | 'verify' | 'unknown'. `detail` is an already-localized
      // sentence from Python (may be empty) for the status bar.
      const reasons = {
        network: t('Network error. Check your connection.', '网络错误，请检查网络连接。'),
        incomplete: t('The downloaded file is incomplete.', '下载的文件不完整。'),
        mount: t('Failed to open the update image.', '安装包无法打开。'),
        verify: t('The update failed the version check.', '更新未通过版本校验。'),
        unknown: t('Unexpected error.', '未知错误。'),
      };
      const reason = reasons[code] || reasons.unknown;
      const el = document.getElementById('updateBubble');
      if (el) {
        el.classList.remove('downloading', 'installing');
        el.classList.add('visible');
        setUpdateProgress(0);
        setUpdateBubbleText(t('Download failed: ', '下载失败：') + reason);
      }
      showStatus(t('Update download failed: ', '更新下载失败：') + (detail || reason), true);
    }

    function showManualInstallGuide(dmgPath, message) {
      const hint = dmgPath
        ? t(' Open the DMG and drag mdPreview to Applications: ', ' 请打开 DMG，并将 mdPreview 拖到 Applications：') + dmgPath
        : t(' Please download the DMG manually and drag mdPreview to Applications.', ' 请手动下载 DMG，并将 mdPreview 拖到 Applications。');
      showStatus((message || t('Update failed.', '更新失败。')) + hint, true);
    }

    function dismissUpdateBubble(event) {
      if (event) event.stopPropagation();
      _updateBubbleDismissed = true;
      const el = document.getElementById('updateBubble');
      if (el) el.classList.remove('visible');
    }

    async function installUpdate() {
      if (state.isDirty) await pushContentToPython(true);
      const el = document.getElementById('updateBubble');
      if (el && (el.classList.contains('installing') || el.classList.contains('downloading'))) return;
      if (el) {
        setUpdateBubbleText(t('Installing...', '正在安装…'));
        el.classList.remove('downloading');
        el.classList.add('installing');
      }
      showStatus(t('Installing update...', '正在安装更新…'));
      if (deps.Bridge.ready()) {
        deps.Bridge.call('perform_auto_install').then(function(result) {
          if (result && result.success) {
            showStatus(t('Update prepared. Finish saving to restart.', '更新已准备，请完成保存以重启。'));
          } else {
            const error = result ? result.error : t('unknown', '未知');
            if (result && result.manual_install) {
              showManualInstallGuide(result.manual_dmg_path || '', t('Automatic install failed.', '自动安装失败。'));
            } else {
              showStatus(t('Update failed: ', '更新失败：') + error, true);
            }
            if (el) {
              setUpdateBubbleText(t('Update available, click to install...', '有新版本可用，点击安装…'));
              el.classList.remove('installing');
            }
          }
        }).catch(function(err) {
          showStatus(t('Update failed: ', '更新失败：') + err, true);
          if (el) {
            setUpdateBubbleText(t('Update available, click to install...', '有新版本可用，点击安装…'));
            el.classList.remove('installing');
          }
        });
      }
    }


    return {
      setUpdateBubbleText, setUpdateProgress, showUpdateBubble, showUpdateDownloadProgress, 
      showUpdateDownloadFailed, showManualInstallGuide, dismissUpdateBubble, installUpdate,
    };
  }
};
