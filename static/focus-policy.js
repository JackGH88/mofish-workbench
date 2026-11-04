/* Keyboard navigation enables a cue. Space must not add an outer ring to
   pointer-selected controls, including controls inside installed plugins. */
(() => {
  const root = document.documentElement;
  const marker = 'data-mofish-keyboard-navigation';
  const shadowRoots = new Set();
  const observedRoots = new WeakSet();
  const controls = ':is(button, a[href], [role="button"], [role="tab"], [role="menuitem"], summary, [tabindex]):not(input, select, textarea, [contenteditable]:not([contenteditable="false"]))';
  const shadowPolicy = `
    ${controls}:focus { outline: none !important; box-shadow: none !important; }
    :host([${marker}]) ${controls}:focus {
      text-decoration: underline;
      text-underline-offset: 4px;
      filter: brightness(.9);
    }
  `;
  function syncShadowCues() {
    for (const shadow of shadowRoots) {
      if (!shadow.host.isConnected) { shadowRoots.delete(shadow); continue; }
      shadow.host.toggleAttribute(marker, root.hasAttribute(marker));
    }
  }
  function applyShadowPolicy(shadow) {
    if (!shadow.querySelector('style[data-mofish-focus-policy]')) {
      const style = document.createElement('style');
      style.setAttribute('data-mofish-focus-policy', '');
      style.textContent = shadowPolicy;
      shadow.appendChild(style);
    }
    shadowRoots.add(shadow);
    if (!observedRoots.has(shadow)) {
      // Focus changes within one host can be retargeted away at document level.
      shadow.addEventListener('focusin', onFocus, true);
      observedRoots.add(shadow);
    }
  }
  // Document CSS cannot cross a shadow boundary. A composed focus event lets
  // the shared host apply its policy to old and newly loaded plugins without
  // altering their packages, inline styles, focus order or activation handlers.
  function onFocus(event) {
    for (const node of event.composedPath()) {
      if (node instanceof ShadowRoot) applyShadowPolicy(node);
    }
    syncShadowCues();
  }
  document.addEventListener('focusin', onFocus, true);
  document.addEventListener('keydown', (event) => {
    if (!['Tab', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    root.setAttribute(marker, '');
    syncShadowCues();
  }, true);
  document.addEventListener('pointerdown', () => {
    root.removeAttribute(marker);
    syncShadowCues();
  }, true);
  // A plugin can finish mounting before this deferred desktop script executes.
  let active = document.activeElement;
  while (active?.shadowRoot) {
    const shadow = active.shadowRoot;
    const focused = shadow.activeElement;
    if (!focused) break;
    applyShadowPolicy(shadow);
    active = focused;
  }
  syncShadowCues();
})();
