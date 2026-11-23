// 更新反馈只消费后端状态；下载、验证及安装均由后端状态机负责。
window.UpdateFeedback = {
  create(deps) {
    const { document, t } = deps;
    const phases = new Set(['idle', 'checking', 'downloading', 'retrying', 'ready', 'preparing', 'deferred', 'installing', 'failed']);
    let current = { phase: 'idle', automatic: true, progress: null };
    let authoritative = false, generation = 0, request = 0;
    let dismissed = false, retryPending = false, requestFailed = null;
    let manualCheckResult = false, installAfterRetry = false;
    let knownVersion = null, dismissedVersion = null, presentedVersion = null;
    let consentPending = null, approvalWaiting = false;
    let manualViewing = false, downloadTimer = null;

    function scheduleDownloadHide() {
      if (downloadTimer !== null) window.clearTimeout(downloadTimer);
      downloadTimer = null;
      if (current.phase !== 'downloading' || !isVisible()) return;
      downloadTimer = window.setTimeout(() => {
        downloadTimer = null;
        if (current.phase === 'downloading') {
          dismissed = true;
          renderUpdateFeedback();
        }
      }, 5000);
    }

    function setUpdateBubbleText(text) {
      const el = document.querySelector('#updateBubble .update-bubble-text');
      if (el) el.textContent = text;
    }
    function percent(value) {
      return typeof value === 'number' && Number.isFinite(value) ? Math.max(0, Math.min(100, Math.round(value))) : 0;
    }
    function setUpdateProgress(value) {
      const bar = document.getElementById('updateProgressBar');
      if (bar) bar.style.width = percent(value) + '%';
    }
    function reason() {
      if (['quit-gap-inconclusive', 'quit-gap-version-unverified'].includes(current.code)) return t('Automatic installation is blocked. Installation records are preserved. Use Help > Report an Issue for recovery assistance.', '自动安装已阻止，安装记录已保留。请通过「帮助 > 报告问题」获取恢复协助。');
      if (current.code === 'helper-handshake-unavailable') return t('This updater requires a manual installation from github.com/tahoeliu/mdPreview/releases.', '此更新器需要从 github.com/tahoeliu/mdPreview/releases 手动安装。');
      if (current.code === 'release-signing-key-not-configured') return t('Updates are unavailable: this build has no release signing key.', '更新不可用：此版本未内置发布签名公钥。');
      if (current.code === 'tls-verification-failed') return t('Could not make a secure connection to the update server.', '无法与更新服务器建立安全连接。');
      const reasons = {
        network: t('Network error. Check your connection.', '网络错误，请检查网络连接。'),
        rate_limited: t('Too many update requests. Please try again later.', '更新请求过于频繁，请稍后重试。'),
        not_found: t('The update file was not found.', '未找到更新文件。'),
        forbidden: t('Access to the update was denied.', '更新访问被拒绝。'),
        http: t('The update server returned an HTTP error.', '更新服务器返回 HTTP 错误。'),
        incomplete: t('The downloaded file is incomplete.', '下载的文件不完整。'),
        mount: t('Failed to open the update image.', '安装包无法打开。'),
        verify: t('The update failed the version check.', '更新未通过版本校验。'),
        unknown: t('Unexpected error.', '未知错误。'),
      };
      // detail 是后端当时语言下的句子，不能把它当作可重新翻译的状态。
      const status = current.error === 'http' && Number.isInteger(current.http) && current.http >= 100 && current.http <= 599 ? ` (HTTP ${current.http})` : '';
      return (reasons[current.error] || reasons.unknown) + status;
    }
    function canRetry() {
      return current.automatic === false && ['failed', 'retrying'].includes(current.phase) && current.code !== 'quit-gap-settlement-pending'
        && !['quit-gap-inconclusive', 'quit-gap-version-unverified', 'helper-handshake-unavailable', 'release-signing-key-not-configured', 'update-requires-running-bundle'].includes(current.code);
    }
    function readyForConsent() {
      return authoritative && current.phase === 'ready' && typeof current.version === 'string' && !!current.version;
    }
    function busy() {
      return !!consentPending || approvalWaiting || ['preparing', 'installing'].includes(current.phase);
    }
    function isVisible() {
      if (dismissed) return false;
      if (current.code === 'quit-gap-settlement-pending') return false;
      if (current.phase === 'idle') return manualCheckResult;
      if (manualViewing) return true;
      if (current.automatic === false) return true;
      if (dismissedVersion === current.version) return false;
      return readyForConsent() || (presentedVersion === current.version && !!presentedVersion && ['preparing', 'installing'].includes(current.phase));
    }
    function renderUpdateFeedback() {
      const el = document.getElementById('updateBubble');
      if (!el) return;
      const visible = isVisible();
      if (visible && readyForConsent()) presentedVersion = current.version;
      const phase = approvalWaiting && current.phase === 'ready' ? 'preparing' : current.phase;
      const downloading = phase === 'downloading';
      el.dataset.phase = phase;
      el.setAttribute('role', 'status');
      el.setAttribute('aria-live', 'polite');
      el.setAttribute('aria-hidden', String(!visible));
      el.setAttribute('aria-busy', String(busy()));
      el.classList.toggle('visible', visible);
      el.classList.toggle('downloading', downloading);
      el.classList.toggle('installing', phase === 'installing');
      el.classList.toggle('retryable', canRetry() && !retryPending);
      // 选择态里“稍后 / 立即更新”就是全部决定，不再另画关闭按钮。
      el.classList.toggle('choosing', visible && (readyForConsent() || phase === 'preparing'));
      setUpdateProgress(downloading ? current.progress : 0);
      const readyText = current.version
        ? t('New version is ready.', '新版本已就绪。')
        : t('Update downloaded. Waiting for a safe restart.', '更新已下载，等待安全重启。');
      const texts = {
        idle: current.detail ? t("You're up to date!", '已是最新版本！') : t('Check for Updates…', '检查更新…'),
        checking: t('Checking for updates…', '正在检查更新…'),
        downloading: t('Downloading update... ', '正在下载更新… ') + percent(current.progress) + '%',
        retrying: t('Update will retry later.', '更新将稍后重试。') + ' ' + reason(),
        ready: readyText,
        preparing: t('Preparing a safe restart…', '正在准备安全重启…'),
        deferred: t('Update postponed. Keep editing or retry when ready.', '更新已延期。可继续编辑，就绪后再重试。'),
        installing: t('Installing update...', '正在安装更新…'),
        failed: (current.stage === 'download' ? t('Download failed: ', '下载失败：') : t('Update failed: ', '更新失败：')) + reason(),
      };
      const errors = {
        retry: t('Retry request failed. Please try again.', '重试请求失败，请再试一次。'),
        approve: t('The update request failed. Please try again.', '更新请求失败，请再试一次。'),
        decline: t('Could not dismiss the update. Please try again.', '未能关闭更新提示，请再试一次。'),
        help: t('Could not open the link. Please try again.', '无法打开链接，请重试。'),
      };
      setUpdateBubbleText(texts[phase] + (requestFailed ? ' ' + errors[requestFailed] : ''));
      const body = el.querySelector('.update-bubble-body');
      if (body) { body.removeAttribute('role'); body.removeAttribute('tabindex'); }
      const button = el.querySelector('.update-retry');
      if (button) {
        button.hidden = !visible || !canRetry();
        button.disabled = retryPending || busy();
        button.textContent = retryPending ? t('Requesting retry…', '正在请求重试…') : t('Retry update', '重试更新');
      }
      const help = el.querySelector('.update-help');
      if (help) {
        const blocked = ['quit-gap-inconclusive', 'quit-gap-version-unverified'].includes(current.code);
        help.hidden = !visible || current.automatic !== false || !['failed', 'retrying'].includes(current.phase);
        help.disabled = busy() || retryPending;
        help.textContent = blocked ? t('Report an Issue', '报告问题') : t('Download manually', '手动下载');
      }
      const approve = el.querySelector('.update-approve'), later = el.querySelector('.update-later');
      if (approve && later) {
        approve.hidden = later.hidden = !visible || !(readyForConsent() || phase === 'preparing');
        approve.disabled = later.disabled = busy();
        approve.textContent = t('Update now', '立即更新');
        later.textContent = t('Later', '稍后');
      }
      const close = el.querySelector('.update-bubble-close');
      if (close) {
        close.disabled = busy();
        close.title = t('Dismiss', '忽略'); close.setAttribute('aria-label', close.title);
      }
    }
    function updateFeedbackState(state) {
      if (!state || !phases.has(state.phase) || typeof state.automatic !== 'boolean') return false;
      const previousPhase = current.phase;
      const newVersion = typeof state.version === 'string' && !!state.version && state.version !== knownVersion;
      if (newVersion) {
        knownVersion = state.version;
        dismissedVersion = presentedVersion = null;
      }
      if (newVersion || state.phase !== current.phase || state.automatic !== current.automatic) {
        dismissed = false;
        manualCheckResult = false;
        requestFailed = null;
      }
      if (state.automatic && state.phase === 'ready' && presentedVersion === state.version
          && !['ready', 'preparing', 'installing'].includes(current.phase)) dismissed = true;
      // armedForQuit 只是后端已挂起退出更新的状态，不是用户已关闭提示的标记。
      if (newVersion || state.phase !== 'ready' || state.error || state.code) approvalWaiting = false;
      current = { ...state };
      if (state.phase !== previousPhase) {
        if (downloadTimer !== null) window.clearTimeout(downloadTimer);
        downloadTimer = null;
        if (state.phase === 'idle') manualViewing = false;
      }
      if (['failed', 'idle'].includes(state.phase)) installAfterRetry = false;
      authoritative = true;
      generation++;
      renderUpdateFeedback();
      if (state.phase === 'downloading' && previousPhase !== 'downloading') scheduleDownloadHide();
      if (installAfterRetry && readyForConsent() && !retryPending) {
        installAfterRetry = false;
        void requestConsent('approve');
      }
      return true;
    }
    function showManualUpdateCheckResult() {
      if (current.phase !== 'idle' || current.automatic || !current.detail) return;
      manualCheckResult = true;
      dismissed = false;
      renderUpdateFeedback();
    }
    function showActiveUpdate(state) {
      if (state) updateFeedbackState(state);
      manualViewing = true;
      dismissed = false;
      dismissedVersion = null;
      renderUpdateFeedback();
      scheduleDownloadHide();
    }
    async function refreshUpdateState() {
      if (!deps.Bridge.ready()) return false;
      const at = generation, id = ++request;
      try {
        const result = await deps.Bridge.call('get_update_state');
        // 初始查询或旧窗口的慢回包不能覆盖期间收到的广播。
        if (id !== request || at !== generation) return false;
        return updateFeedbackState(result);
      } catch (_) { return false; }
    }
    function legacy(patch) {
      // 新后端已经广播时，迟到的旧接口只能触发读取，不得降级状态。
      if (authoritative) { void refreshUpdateState(); return; }
      current = { ...current, ...patch };
      generation++;
      renderUpdateFeedback();
    }
    function showUpdateBubble() {
      // 旧自动路径没有版本或验签状态，默认静默，不据此提供批准入口。
      if (current.phase === 'failed') return;
      legacy({ phase: 'ready', progress: null });
    }
    function showUpdateDownloadProgress(value) {
      if (!authoritative) dismissed = false;
      legacy({ phase: 'downloading', automatic: false, progress: value, error: null });
    }
    function showUpdateDownloadFailed(code, detail) {
      legacy({ phase: 'failed', stage: 'download', progress: null, error: code, detail });
    }
    function showManualInstallGuide(dmgPath, message) {
      // 保留旧签名，但不把下载失败转换为安装入口，也不弹出自动路径 toast。
      legacy({ phase: 'failed', progress: null, error: 'unknown', detail: message });
    }
    function dismissUpdateBubble(event) {
      if (event) event.stopPropagation();
      if (busy() || dismissed) return false;
      if (readyForConsent()) return requestConsent('decline');
      dismissed = true;
      if (downloadTimer !== null) window.clearTimeout(downloadTimer);
      downloadTimer = null;
      installAfterRetry = false;
      renderUpdateFeedback();
      return true;
    }
    async function requestConsent(action) {
      if (!readyForConsent() || !isVisible() || busy() || retryPending) return false;
      const version = current.version, at = generation, previousDismissedVersion = dismissedVersion;
      consentPending = action;
      requestFailed = null;
      approvalWaiting = action === 'approve';
      if (action === 'approve') dismissedVersion = null;
      if (action === 'decline') { dismissed = true; dismissedVersion = version; }
      renderUpdateFeedback();
      let succeeded = false;
      try {
        if (!deps.Bridge.ready()) throw new Error('bridge-unavailable');
        // 批准只能由明确按钮触发，保存确认及退出始终交给后端现有流程。
        const result = await deps.Bridge.call(action === 'approve' ? 'approve_update' : 'decline_update');
        if (at === generation && result?.state) updateFeedbackState(result.state);
        succeeded = result?.success === true;
        return succeeded;
      } catch (_) { return false; }
      finally {
        consentPending = null;
        if (!succeeded) {
          approvalWaiting = false;
          if (current.version === version && current.phase === 'ready') {
            dismissed = false;
            dismissedVersion = previousDismissedVersion;
            requestFailed = action;
          }
        }
        renderUpdateFeedback();
      }
    }
    async function updateHelp() {
      if (!deps.Bridge.ready() || busy() || retryPending) return;
      const blocked = ['quit-gap-inconclusive', 'quit-gap-version-unverified'].includes(current.code);
      try {
        const result = await deps.Bridge.call(blocked ? 'report_issue' : 'open_external_link',
          ...(blocked ? [] : ['https://github.com/tahoeliu/mdPreview/releases/latest']));
        if (!result || result.success !== true) throw new Error('open-failed');
      } catch (_) {
        requestFailed = 'help';
        renderUpdateFeedback();
      }
    }
    async function installUpdate() {
      // 兼容旧函数名；这里只能重试手动失败，绝不批准安装。
      if (!canRetry() || retryPending || busy() || !deps.Bridge.ready()) return false;
      retryPending = true;
      installAfterRetry = true;
      requestFailed = null;
      const at = generation;
      renderUpdateFeedback();
      try {
        const result = await deps.Bridge.call('retry_update');
        if (at === generation) {
          if (result?.state) updateFeedbackState(result.state);
          if (result?.success !== true) requestFailed = 'retry';
        }
        if (result?.success !== true) return false;
        await refreshUpdateState();
        return true;
      } catch (_) {
        installAfterRetry = false;
        if (at === generation) requestFailed = 'retry';
        return false;
      } finally {
        retryPending = false;
        if (requestFailed) installAfterRetry = false;
        renderUpdateFeedback();
        if (installAfterRetry && readyForConsent()) {
          installAfterRetry = false;
          void requestConsent('approve');
        }
      }
    }
    const body = document.querySelector('#updateBubble .update-bubble-body');
    if (body) {
      const actions = document.createElement('div');
      actions.className = 'update-actions';
      for (const [className, handler] of [
        ['update-approve', () => requestConsent('approve')],
        ['update-later', dismissUpdateBubble],
        ['update-retry', installUpdate],
        ['update-help', updateHelp],
      ]) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = className;
        button.addEventListener('click', event => { event.stopPropagation(); void handler(); });
        actions.appendChild(button);
      }
      body.appendChild(actions);
    }
    renderUpdateFeedback();
    return {
      setUpdateBubbleText, setUpdateProgress, showUpdateBubble, showUpdateDownloadProgress,
      showUpdateDownloadFailed, showManualInstallGuide, dismissUpdateBubble, installUpdate,
      updateFeedbackState, showManualUpdateCheckResult, refreshUpdateState, renderUpdateFeedback,
      showActiveUpdate,
    };
  }
};
