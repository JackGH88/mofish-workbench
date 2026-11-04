/* Media previews always follow the currently bound publishing assets. */
(() => {
  const buttons = [...document.querySelectorAll('[data-publish-preview]')];
  if (!buttons.length) return;
  // Clone the original SVG placeholders so resets use the same icons as initial HTML.
  const placeholders = new Map(buttons.map(button => [
    button.dataset.publishPreview, button.querySelector('.publish-preview-placeholder').cloneNode(true),
  ]));
  const card = document.createElement('div');
  card.className = 'publish-preview-card';
  card.id = 'publishAssetPreview';
  card.setAttribute('role', 'tooltip');
  card.hidden = true;
  document.body.append(card);
  let active = null;
  let previousAssets;
  let context = '';
  let revision = 0;
  let closeTimer;
  let openTimer;
  const states = new WeakMap();

  function close() {
    clearTimeout(closeTimer);
    clearTimeout(openTimer);
    active?.removeAttribute('aria-describedby');
    active = null;
    card.hidden = true;
    const video = card.querySelector('video');
    if (video) {
      video.pause();
      video.removeAttribute('src');
      video.load();
    }
    card.replaceChildren();
  }
  function position() {
    if (!active) return;
    const rect = active.getBoundingClientRect();
    if (!active.getClientRects().length) { close(); return; }
    const width = card.offsetWidth;
    const height = card.offsetHeight;
    const left = rect.left - width - 10 >= 8 ? rect.left - width - 10 : rect.right + 10;
    card.style.left = `${Math.max(8, Math.min(left, innerWidth - width - 8))}px`;
    card.style.top = `${Math.max(8, Math.min(rect.top + rect.height / 2 - height / 2, innerHeight - height - 8))}px`;
  }
  function sizeMedia(media, width, height) {
    // CSS auto sizing depends on the poster/metadata download. Freeze the final
    // proportional box before mounting so a cold video cannot flash elsewhere.
    const scale = Math.min(1, Math.min(320, innerWidth - 16) / width, Math.min(420, innerHeight - 16) / height);
    media.style.width = `${width * scale}px`;
    media.style.height = `${height * scale}px`;
  }
  function soundButton(media) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'publish-preview-sound';
    // Safari does not focus buttons on mouse clicks; transfer focus explicitly
    // so the thumbnail's blur cannot dismiss the player before the click.
    button.addEventListener('mousedown', event => {
      event.preventDefault();
      button.focus({ preventScroll: true });
    });
    const update = () => {
      const label = media.muted ? '取消静音' : '静音';
      button.title = label;
      button.setAttribute('aria-label', label);
      button.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M11 5 6 9H3v6h3l5 4Z"/><path d="${media.muted ? 'm3 3 18 18' : 'M15 8a6 6 0 0 1 0 8M18 5a10 10 0 0 1 0 14'}"/></svg>`;
    };
    button.addEventListener('click', () => {
      media.muted = !media.muted;
      update();
    });
    media.addEventListener('volumechange', update);
    update();
    return button;
  }
  function open(button) {
    const state = states.get(button);
    if (!state?.ready || !button.getClientRects().length) return;
    clearTimeout(closeTimer);
    clearTimeout(openTimer);
    // Hover, focus and load can overlap. Keep this playback session intact.
    if (active === button && !card.hidden) return;
    close();
    active = button;
    button.setAttribute('aria-describedby', card.id);
    const isVideo = button.dataset.publishPreview === 'video';
    card.setAttribute('role', isVideo ? 'group' : 'tooltip');
    card.setAttribute('aria-label', button.getAttribute('aria-label'));
    const media = document.createElement(isVideo ? 'video' : 'img');
    media.setAttribute('aria-label', button.getAttribute('aria-label'));
    sizeMedia(media, state.width, state.height);
    if (isVideo) {
      media.muted = true;
      media.defaultMuted = true;
      media.autoplay = true;
      media.loop = true;
      media.playsInline = true;
      media.poster = state.url;
      media.width = state.width;
      media.height = state.height;
      media.src = `${state.url}&playback=true`;
      media.onloadedmetadata = () => {
        if (active !== button || !media.isConnected) return;
        media.width = media.videoWidth;
        media.height = media.videoHeight;
        sizeMedia(media, media.videoWidth, media.videoHeight);
        position();
      };
      media.onerror = () => {
        if (active !== button || !media.isConnected) return;
        const notice = document.createElement('p');
        notice.textContent = '视频暂时无法播放';
        card.append(notice);
        position();
      };
    } else {
      media.alt = button.getAttribute('aria-label');
      media.width = state.width;
      media.height = state.height;
      media.src = state.url;
      media.onload = () => { if (active === button) position(); };
    }
    card.style.visibility = "hidden";
    card.append(media);
    if (isVideo) card.append(soundButton(media));
    card.hidden = false;
    position();
    card.style.visibility = "visible";
    if (isVideo) media.play().catch(() => {
      if (active === button && media.isConnected) media.controls = true;
    });
  }
  function scheduleClose() {
    clearTimeout(openTimer);
    clearTimeout(closeTimer);
    closeTimer = setTimeout(close, 120);
  }
  function onFocusOut(event) {
    if (event.relatedTarget === active || card.contains(event.relatedTarget)) return;
    close();
  }
  for (const button of buttons) {
    button.addEventListener('pointerenter', event => {
      if (event.pointerType === 'touch') return;
      clearTimeout(closeTimer);
      clearTimeout(openTimer);
      openTimer = setTimeout(() => open(button), 150);
    });
    button.addEventListener('pointerleave', scheduleClose);
    button.addEventListener('focus', () => open(button));
    button.addEventListener('blur', onFocusOut);
    button.addEventListener('keydown', event => {
      const sound = card.querySelector('.publish-preview-sound');
      if (event.key === 'Tab' && !event.shiftKey && active === button && sound) {
        event.preventDefault();
        sound.focus({ preventScroll: true });
      }
    });
    button.addEventListener('click', () => open(button));
  }
  card.addEventListener('pointerenter', () => clearTimeout(closeTimer));
  card.addEventListener('pointerleave', scheduleClose);
  card.addEventListener('focusin', () => clearTimeout(closeTimer));
  card.addEventListener('focusout', onFocusOut);
  card.addEventListener('keydown', event => {
    if (event.key === 'Tab' && active) {
      const trigger = active;
      trigger.focus({ preventScroll: true });
      if (event.shiftKey) event.preventDefault();
    }
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      if (card.contains(document.activeElement)) active?.focus({ preventScroll: true });
      close();
    }
  });
  window.addEventListener('resize', close);
  document.addEventListener('scroll', close, true);
  // Navigation can hide an ancestor without re-rendering the publishing stage.
  new MutationObserver(() => {
    if (active && !active.getClientRects().length) close();
  }).observe(document.body, { attributes: true, subtree: true, attributeFilter: ['hidden', 'class'] });

  function render({ accountId, scriptId, assets, generated = [] }) {
    const nextContext = `${accountId || ''}:${scriptId || ''}`;
    if (nextContext !== context || previousAssets !== assets) {
      context = nextContext;
      previousAssets = assets;
      revision += 1;
      close();
    }
    const sources = {
      video: assets?.video,
      portrait: assets?.covers?.['3:4'] || generated[0],
      landscape: assets?.covers?.['4:3'] || generated[1],
    };
    for (const button of buttons) {
      const kind = button.dataset.publishPreview;
      const source = scriptId && sources[kind];
      const url = source ? `/api/scripts/${encodeURIComponent(scriptId)}/publish-assets/preview/${kind}?v=${revision}&source=${encodeURIComponent(source.path || source.imageUrl || '')}` : '';
      if (states.get(button)?.url === url) continue;
      if (active === button) close();
      const previous = states.get(button);
      const identity = JSON.stringify([nextContext, kind, source?.path || source?.imageUrl || '']);
      const retain = previous?.ready && previous.identity === identity;
      button.dataset.publishPreviewIdentity = identity;
      previous?.settle?.();
      const state = { url, identity, ready: false };
      state.pending = new Promise(resolve => { state.settle = resolve; });
      states.set(button, state);
      button.disabled = !source;
      button.removeAttribute('title');
      button.classList.remove('is-preview-error');
      if (!retain) delete button.dataset.videoOrientation;
      const placeholder = placeholders.get(kind).cloneNode(true);
      if (!retain) button.replaceChildren(placeholder);
      if (!url) { state.settle(); continue; }
      const image = new Image();
      image.alt = '';
      image.onload = () => {
        if (states.get(button) !== state || state.ready) return;
        // Reparenting a loaded image must not trigger another replacement/open cycle.
        image.onload = null;
        state.ready = true;
        state.settle();
        state.width = image.naturalWidth;
        state.height = image.naturalHeight;
        if (kind === 'video') button.dataset.videoOrientation = state.height > state.width ? 'portrait' : 'landscape';
        button.replaceChildren(image);
        if (kind === 'video') {
          const icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
          icon.classList.add('publish-thumbnail-play');
          icon.setAttribute('viewBox', '0 0 24 24');
          icon.setAttribute('aria-hidden', 'true');
          icon.setAttribute('focusable', 'false');
          const triangle = document.createElementNS('http://www.w3.org/2000/svg', 'path');
          triangle.setAttribute('d', 'M7 5.5a1 1 0 0 1 1.5-.86l10 5.75a1.85 1.85 0 0 1 0 3.22l-10 5.75A1 1 0 0 1 7 18.5Z');
          icon.append(triangle);
          button.append(icon);
        }
        if (document.activeElement === button || button.matches(':hover')) open(button);
      };
      image.onerror = () => {
        if (states.get(button) !== state) return;
        state.settle();
        button.classList.add('is-preview-error');
        placeholder.textContent = '预览不可用';
        button.title = '预览不可用';
        if (active === button) close();
      };
      image.src = url;
    }
  }
  function seedFromSnapshot(snapshot) {
    for (const button of buttons) {
      const state = states.get(button);
      const cached = snapshot.querySelector(`[data-publish-preview="${button.dataset.publishPreview}"]`);
      // Transfer only decoded imagery for the same account, script and bound file.
      // Fresh data unlocks the page immediately; new image downloads stay independent.
      if (!state || state.ready || cached?.dataset.publishPreviewIdentity !== state.identity || !cached.querySelector('img')) continue;
      button.replaceChildren(...Array.from(cached.childNodes, node => node.cloneNode(true)));
      if (cached.dataset.videoOrientation) button.dataset.videoOrientation = cached.dataset.videoOrientation;
    }
  }
  function whenReady() {
    return new Promise(resolve => {
      const timer = setTimeout(resolve, 5000);
      Promise.all(buttons.map(button => states.get(button)?.pending)).then(() => { clearTimeout(timer); resolve(); });
    });
  }
  window.WorkbenchPublishPreviews = { render, close, whenReady, seedFromSnapshot };
})();
