/* Keep wheel/touch gestures within floating UI, including non-scrolling headers.
   Event delegation also covers dialogs and menus created after page startup. */
(() => {
  'use strict';
  const floating = 'dialog[open], .prompt-modal, .account-switcher-popover, '
    + '[popover]:popover-open:not([role="status"]), [role="menu"], .topics-select-menu';
  const modal = 'dialog[open], .prompt-modal, [aria-modal="true"]';
  const visible = node => !node.closest('[hidden]') && node.getClientRects().length > 0
    && getComputedStyle(node).visibility !== 'hidden';

  function boundary(target) {
    const root = target.closest(floating);
    if (root && visible(root)) return root;
    // Unlike a non-modal menu, a modal must also block gestures over its backdrop.
    return [...document.querySelectorAll(modal)].some(visible) ? false : null;
  }

  function canScroll(target, root, dx, dy) {
    const horizontal = Math.abs(dx) > Math.abs(dy);
    const delta = horizontal ? dx : dy;
    if (!delta) return true;
    for (let node = target; node; node = node.parentElement) {
      const css = getComputedStyle(node);
      const overflow = horizontal ? css.overflowX : css.overflowY;
      const size = horizontal ? node.clientWidth : node.clientHeight;
      const extent = horizontal ? node.scrollWidth : node.scrollHeight;
      const position = horizontal ? node.scrollLeft : node.scrollTop;
      if (/^(auto|scroll|overlay)$/.test(overflow) && extent > size + 1
        && (delta < 0 ? position > 0 : position < extent - size - 1)) return true;
      if (node === root) break;
    }
    return false;
  }

  function guard(event, dx, dy, x, y) {
    const target = event.target instanceof Element ? event.target : event.target.parentElement;
    if (!target) return;
    const root = boundary(target);
    if (root === null) return;
    if (root === false) { event.preventDefault(); return; }
    // Native dialog backdrop events are retargeted to the dialog itself.
    const rect = root.getBoundingClientRect();
    if (x < rect.left || x > rect.right || y < rect.top || y > rect.bottom
      || !canScroll(target, root, dx, dy)) event.preventDefault();
  }

  document.addEventListener('wheel', event => {
    if (event.ctrlKey || event.defaultPrevented) return; // Preserve pinch-to-zoom.
    guard(event, event.shiftKey && !event.deltaX ? event.deltaY : event.deltaX,
      event.shiftKey && !event.deltaX ? 0 : event.deltaY, event.clientX, event.clientY);
  }, { passive: false });

  let touch = null;
  document.addEventListener('touchstart', event => {
    touch = event.touches.length === 1 ? event.touches[0] : null;
  }, { passive: true });
  document.addEventListener('touchmove', event => {
    if (!touch || event.touches.length !== 1) { touch = null; return; }
    const next = event.touches[0];
    guard(event, touch.clientX - next.clientX, touch.clientY - next.clientY,
      next.clientX, next.clientY);
    touch = next;
  }, { passive: false });
  for (const type of ['touchend', 'touchcancel']) {
    document.addEventListener(type, () => { touch = null; }, { passive: true });
  }
})();
