/* Read-only image/diagram viewer. All presentation state lives outside #content. */
(function () {
  'use strict';
  window.createImageViewer = function ({ root, content, enabled, translate, cleanSVG, onError }) {
    const stage = root.querySelector('.image-viewer-stage');
    const surface = root.querySelector('.image-viewer-surface');
    const label = root.querySelector('.image-viewer-scale');
    const closeButton = root.querySelector('[data-viewer="close"]');
    const maxScale = 16;
    let minScale = 0.1, fitted = false;
    let active = false, ready = false, scale = 1, x = 0, y = 0, width = 1, height = 1;
    let previousFocus = null, savedRanges = [], scrollState = [], source = null;
    let drag = null, frame = 0, generation = 0, loadTimer = 0, clone = null;
    const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
    const text = (en, zh) => translate(en, zh);
    function bounds() {
      const box = stage.getBoundingClientRect();
      return { width: Math.max(1, box.width), height: Math.max(1, box.height), left: box.left, top: box.top };
    }
    function constrain() {
      const box = bounds();
      const limitX = Math.max(0, (width * scale - box.width) / 2 + 32);
      const limitY = Math.max(0, (height * scale - box.height) / 2 + 32);
      x = clamp(x, -limitX, limitX); y = clamp(y, -limitY, limitY);
    }
    function paint() {
      frame = 0;
      surface.style.width = width + 'px'; surface.style.height = height + 'px';
      surface.style.transform = `translate(-50%, -50%) translate(${x}px, ${y}px) scale(${scale})`;
      label.textContent = ready ? (scale < 0.1 ? (scale * 100).toFixed(1) : Math.round(scale * 100)) + '%' : text('Loading…', '加载中…');
      root.querySelector('[data-viewer="in"]').disabled = !ready || scale >= maxScale;
      root.querySelector('[data-viewer="out"]').disabled = !ready || scale <= minScale;
      root.querySelector('[data-viewer="fit"]').disabled = !ready;
      root.querySelector('[data-viewer="actual"]').disabled = !ready;
    }
    function draw() { if (!frame) frame = requestAnimationFrame(paint); }
    function zoom(value, clientX, clientY) {
      if (!active || !ready || !Number.isFinite(value)) return;
      fitted = false;
      const box = bounds(), next = clamp(value, minScale, maxScale);
      const px = Number.isFinite(clientX) ? clientX - box.left - box.width / 2 : 0;
      const py = Number.isFinite(clientY) ? clientY - box.top - box.height / 2 : 0;
      x = px - (px - x) * next / scale; y = py - (py - y) * next / scale;
      scale = next; constrain(); draw();
    }
    function fit() {
      if (!active || !ready) return;
      const box = bounds();
      // Even unusually wide/tall diagrams must fit fully, below the normal 10% floor.
      const fitScale = Math.max(0.000001, Math.min(Math.max(1, box.width - 48) / width, Math.max(1, box.height - 48) / height));
      minScale = Math.min(0.1, fitScale);
      scale = Math.min(fitScale, maxScale);
      fitted = true; x = 0; y = 0; draw();
    }
    function endDrag() {
      if (drag && stage.hasPointerCapture && stage.hasPointerCapture(drag.id)) stage.releasePointerCapture(drag.id);
      drag = null; stage.classList.remove('dragging');
    }
    function close(restore = true) {
      if (!active) return;
      active = false; ready = false; generation++; clearTimeout(loadTimer); endDrag();
      if (frame) { cancelAnimationFrame(frame); frame = 0; }
      if (clone) { clone.onload = null; clone.onerror = null; }
      clone = null; source = null; surface.replaceChildren();
      root.classList.remove('visible'); root.setAttribute('aria-hidden', 'true');
      for (const item of scrollState) { item.node.inert = item.inert; item.node.style.overflow = item.overflow; }
      if (restore) {
        if (previousFocus && previousFocus.isConnected) previousFocus.focus({ preventScroll: true });
        const selection = window.getSelection();
        if (selection) {
          selection.removeAllRanges();
          savedRanges.forEach(range => { if (range.commonAncestorContainer.isConnected) selection.addRange(range); });
        }
        scrollState.forEach(item => { item.node.scrollTop = item.top; item.node.scrollLeft = item.left; });
      }
      savedRanges = []; scrollState = []; previousFocus = null;
    }
    function fail(token) {
      if (!active || token !== generation) return;
      close(); onError(text('Unable to preview this image. Check that it has loaded.', '无法预览此图片，请检查图片是否已加载。'));
    }
    function finish(token, w, h) {
      if (!active || token !== generation) return;
      if (!(Number.isFinite(w) && Number.isFinite(h) && w > 0 && h > 0)) { fail(token); return; }
      clearTimeout(loadTimer); width = w; height = h; ready = true;
      surface.style.visibility = 'visible'; fit();
    }
    function copySVG(svg, token) {
      // Keep vectors and foreignObject labels, but isolate IDs/CSS from the original diagram.
      const holder = document.createElement('div');
      holder.innerHTML = cleanSVG(svg.outerHTML);
      const copy = holder.querySelector('svg');
      if (!copy) throw new Error('Missing SVG');
      const ids = new Map();
      [copy, ...copy.querySelectorAll('[id]')].forEach(node => {
        if (node.id) ids.set(node.id, 'viewer-' + token + '-' + ids.size);
      });
      const escape = value => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      const referencePattern = ids.size ? new RegExp('#(' + [...ids.keys()].sort((a, b) => b.length - a.length).map(escape).join('|') + ')(?![\\w-])', 'g') : null;
      function references(value) {
        return referencePattern ? value.replace(referencePattern, (_, id) => '#' + ids.get(id)) : value;
      }
      [copy, ...copy.querySelectorAll('*')].forEach(node => {
        for (const attr of [...node.attributes]) {
          if (attr.name === 'id') node.id = ids.get(attr.value);
          else if (attr.name === 'aria-labelledby' || attr.name === 'aria-describedby') node.setAttribute(attr.name, attr.value.split(/\s+/).map(id => ids.get(id) || id).join(' '));
          else node.setAttribute(attr.name, references(attr.value));
        }
        if (node.localName === 'style') node.textContent = references(node.textContent);
        if (node.localName === 'a') { node.removeAttribute('href'); node.removeAttribute('xlink:href'); }
        node.removeAttribute('tabindex'); node.removeAttribute('contenteditable');
      });
      const view = svg.viewBox && svg.viewBox.baseVal;
      const box = svg.getBoundingClientRect();
      const w = view && view.width > 0 ? view.width : box.width;
      const h = view && view.height > 0 ? view.height : box.height;
      if (!copy.hasAttribute('viewBox')) copy.setAttribute('viewBox', `0 0 ${w} ${h}`);
      copy.style.width = '100%'; copy.style.height = '100%'; copy.style.maxWidth = 'none';
      copy.setAttribute('width', '100%'); copy.setAttribute('height', '100%');
      copy.setAttribute('aria-hidden', 'true');
      surface.appendChild(copy); finish(token, w, h);
    }
    function open(target) {
      if (!enabled()) return false;
      const diagram = target.closest('.mermaid-diagram');
      const image = diagram ? diagram.querySelector('svg') : target.closest('img');
      if (!image || !content.contains(image)) return false;
      close(false); active = true; source = image; const token = ++generation;
      previousFocus = document.activeElement;
      const selection = window.getSelection(); savedRanges = [];
      if (selection) for (let i = 0; i < selection.rangeCount; i++) savedRanges.push(selection.getRangeAt(i).cloneRange());
      scrollState = [...document.body.children].filter(node => node !== root && node.tagName !== 'SCRIPT').map(node => ({ node, inert: node.inert, overflow: node.style.overflow, top: node.scrollTop, left: node.scrollLeft }));
      scrollState.forEach(item => { item.node.inert = true; if (item.node.classList.contains('scroll-wrap')) item.node.style.overflow = 'hidden'; });
      scale = 1; x = 0; y = 0; ready = false; surface.style.visibility = 'hidden';
      root.querySelector('#imageViewerTitle').textContent = diagram ? text('Diagram preview', '图表预览') : (image.alt || text('Image preview', '图片预览'));
      root.querySelector('.image-viewer-help').textContent = text('Scroll to zoom · Drag to pan · Shift+scroll to pan · Esc to close', '滚动缩放 · 拖动平移 · Shift+滚动平移 · Esc 关闭');
      const labels = { in: text('Zoom in', '放大'), out: text('Zoom out', '缩小'), fit: text('Fit', '适应窗口'), actual: '100%', close: text('Close', '关闭') };
      root.querySelectorAll('[data-viewer]').forEach(button => {
        const name = button.dataset.viewer; button.setAttribute('aria-label', labels[name]); button.title = labels[name];
        if (name !== 'in' && name !== 'out') button.textContent = labels[name];
      });
      root.classList.add('visible'); root.setAttribute('aria-hidden', 'false'); paint(); closeButton.focus({ preventScroll: true });
      if (selection) selection.removeAllRanges();
      try {
        if (diagram) copySVG(image, token);
        else {
          clone = new Image(); clone.id = 'imageLightboxImg'; clone.alt = image.alt || ''; clone.draggable = false;
          clone.onload = event => finish(token, event.currentTarget.naturalWidth, event.currentTarget.naturalHeight);
          clone.onerror = () => fail(token);
          loadTimer = setTimeout(() => fail(token), 15000);
          clone.src = image.currentSrc || image.src; surface.appendChild(clone);
          if (clone.complete) {
            if (clone.naturalWidth) finish(token, clone.naturalWidth, clone.naturalHeight);
            else fail(token);
          }
        }
      } catch (_) { fail(token); }
      return true;
    }
    content.addEventListener('click', event => {
      if (event.button !== 0 || !enabled() || !event.target.closest('img, .mermaid-diagram')) return;
      if (open(event.target)) { event.preventDefault(); event.stopImmediatePropagation(); }
    }, true);
    root.addEventListener('click', event => {
      const button = event.target.closest('[data-viewer]');
      if (!button) return;
      switch (button.dataset.viewer) {
        case 'close': close(); break;
        case 'fit': fit(); break;
        case 'actual': zoom(1); break;
        case 'in': zoom(scale * 1.25); break;
        case 'out': zoom(scale / 1.25); break;
      }
    });
    stage.addEventListener('wheel', event => {
      if (!active) return;
      event.preventDefault(); event.stopPropagation(); if (!ready) return;
      const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? bounds().height : 1;
      if (!Number.isFinite(event.deltaY) || !Number.isFinite(event.deltaX)) return;
      if (event.shiftKey) {
        x -= clamp(event.deltaX * unit, -2000, 2000); y -= clamp(event.deltaY * unit, -2000, 2000);
        constrain(); draw();
      } else if (event.deltaY) zoom(scale * Math.exp(-clamp(event.deltaY * unit, -300, 300) * 0.0025), event.clientX, event.clientY);
      else { x -= clamp(event.deltaX * unit, -2000, 2000); constrain(); draw(); }
    }, { passive: false });
    stage.addEventListener('pointerdown', event => {
      if (!active || !ready || event.button !== 0 || drag) return;
      event.preventDefault(); drag = { id: event.pointerId, x: event.clientX, y: event.clientY };
      stage.setPointerCapture(event.pointerId); stage.classList.add('dragging');
    });
    stage.addEventListener('pointermove', event => {
      if (!drag || drag.id !== event.pointerId) return;
      x += event.clientX - drag.x; y += event.clientY - drag.y;
      drag.x = event.clientX; drag.y = event.clientY; constrain(); draw();
    });
    ['pointerup', 'pointercancel', 'lostpointercapture'].forEach(name => stage.addEventListener(name, endDrag));
    window.addEventListener('blur', endDrag);
    stage.addEventListener('dragstart', event => event.preventDefault());
    stage.addEventListener('dblclick', event => { event.preventDefault(); fit(); });
    // WKWebView's native trackpad pinch uses gesture events rather than Ctrl+wheel.
    let gestureScale = 1;
    stage.addEventListener('gesturestart', event => { event.preventDefault(); gestureScale = scale; }, { passive: false });
    stage.addEventListener('gesturechange', event => { event.preventDefault(); zoom(gestureScale * event.scale, event.clientX, event.clientY); }, { passive: false });
    stage.addEventListener('gestureend', event => event.preventDefault(), { passive: false });
    document.addEventListener('keydown', event => {
      if (!active) return;
      // Do not let typing, paste, undo, or document hotkeys reach the editor behind the viewer.
      event.stopImmediatePropagation();
      if (event.key === 'Escape') { event.preventDefault(); close(); return; }
      if (event.key === 'Tab') {
        event.preventDefault(); const buttons = [...root.querySelectorAll('button')].filter(button => !button.disabled);
        const index = buttons.indexOf(document.activeElement);
        buttons[(index + (event.shiftKey ? -1 : 1) + buttons.length) % buttons.length].focus(); return;
      }
      if ((event.key === 'Enter' || event.key === ' ') && document.activeElement.matches('[data-viewer]')) return;
      event.preventDefault();
      if (event.key === '+' || event.key === '=') zoom(scale * 1.25);
      else if (event.key === '-') zoom(scale / 1.25);
      else if (event.key === '0') fit();
      else if (event.key === '1') zoom(1);
      else if (event.key.startsWith('Arrow') && ready) {
        const step = event.shiftKey ? 160 : 40;
        if (event.key === 'ArrowLeft') x += step;
        if (event.key === 'ArrowRight') x -= step;
        if (event.key === 'ArrowUp') y += step;
        if (event.key === 'ArrowDown') y -= step;
        constrain(); draw();
      }
    }, true);
    window.addEventListener('resize', () => { if (active) { endDrag(); if (fitted) fit(); else { constrain(); draw(); } } });
    // Cover document replacement, image deletion and render/source transitions, including native menus.
    const observer = new MutationObserver(() => { if (active && (!enabled() || !source || !source.isConnected)) close(); });
    observer.observe(content, { childList: true, subtree: true, attributes: true, attributeFilter: ['class'] });
    return { open, close, zoomIn: () => zoom(scale * 1.25), zoomOut: () => zoom(scale / 1.25), get active() { return active; } };
  };
})();
