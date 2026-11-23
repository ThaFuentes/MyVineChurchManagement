/* Phone Bible reading: site menu and reader tools sit on the side edges.
   The chapter row keeps Books, the title, and previous/next. A sideways
   swipe on the chapter also moves one chapter. Desktop layout is unchanged. */
(function () {
  const body = document.body;
  if (!body.classList.contains('bible-reading')) return;

  const mq = window.matchMedia('(max-width: 767px)');
  const menuBtn = document.querySelector('.bible-edge-menu');
  const toolsBtn = document.querySelector('.bible-edge-tools');
  const topBar = document.querySelector('header.top-bar');
  const actions = document.querySelector('.bible-stage-toolbar-actions');
  const toolbar = document.querySelector('.bible-stage-toolbar');
  const title = document.querySelector('.bible-stage-title');
  const books = document.getElementById('member-open-canon') || document.getElementById('bible-open-canon');
  const hideBarBtn = document.querySelector('.bible-bar-hide');
  const focusTab = document.querySelector('.bible-edge-focus');
  const focusMq = window.matchMedia('(max-width: 900px)');
  const FOCUS_KEY = 'mvos.bible.barHidden';
  /* Remember where the restore tab lives in the markup, so turning focus off
     puts it back exactly where it came from. */
  const focusTabHome = focusTab ? focusTab.parentNode : null;
  const focusTabNext = focusTab ? focusTab.nextSibling : null;

  /* The bar leaves the top of the screen as soon as the reader scrolls into a
     chapter, and until now it only came back by scrolling all the way up.
     When it goes out of sight the same edge tab appears, so the bar is one tap
     away instead of a full scroll back to the top. */
  function syncBarOffscreen(off) {
    if (!focusMq.matches) off = false;
    body.classList.toggle('bible-bar-offscreen', off);
  }

  function nearestScroller() {
    let el = toolbar ? toolbar.parentElement : null;
    while (el && el !== document.body && el !== document.documentElement) {
      const style = window.getComputedStyle(el);
      if (/(auto|scroll)/.test(style.overflowY) && el.scrollHeight > el.clientHeight + 4) return el;
      el = el.parentElement;
    }
    return null;
  }

  function scrollReaderToTop() {
    const scroller = nearestScroller();
    if (scroller) scroller.scrollTo({ top: 0, behavior: 'smooth' });
    else window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  /* Being on screen is not the same as being usable. The chapter bar is
     sticky on a phone, and the chapter paints over it the moment it scrolls
     up — the bar stays parked at the top, buried under the verses and
     swallowing nothing. So test the bar's actual face: if it left the
     viewport, or if whatever sits at its own position is not the bar, treat
     it as gone and let the edge tab take over. */
  function barUsable() {
    if (!toolbar) return true;
    const rect = toolbar.getBoundingClientRect();
    const vh = window.innerHeight || document.documentElement.clientHeight || 0;
    /* Folded by focus mode, or not laid out yet: nothing to rescue. */
    if (rect.width < 2 || rect.height < 2) return true;
    if (rect.bottom <= 4 || rect.top >= vh - 4) return false;
    const x = Math.round(rect.left + Math.min(rect.width * 0.5, 90));
    const y = Math.round(rect.top + Math.min(rect.height * 0.5, 16));
    const hit = document.elementFromPoint(x, y);
    if (!hit) return false;
    return !!(hit.closest && hit.closest('.bible-stage-toolbar'));
  }

  let barSyncQueued = false;
  function queueBarSync() {
    if (barSyncQueued) return;
    barSyncQueued = true;
    const run = () => {
      barSyncQueued = false;
      syncBarOffscreen(!barUsable());
    };
    if (window.requestAnimationFrame) window.requestAnimationFrame(run);
    else setTimeout(run, 16);
  }

  /* Capture-phase scroll also catches an inner reader that scrolls itself. */
  document.addEventListener('scroll', queueBarSync, { capture: true, passive: true });
  window.addEventListener('resize', queueBarSync);
  window.addEventListener('orientationchange', queueBarSync);
  queueBarSync();

  /* The tools panel starts inside the sticky toolbar. On a phone that
     toolbar is a stacking context, so a fixed drawer paints under the
     chapter. Parking the side controls on the body lets them cover the page. */
  function parkChrome() {
    if (!toolbar) return;
    /* The restore tab must never sit inside the bar it just folded away, nor
       under a transformed ancestor, so it lives on the body at every width
       where focus mode exists. */
    if (focusTab) {
      if (focusMq.matches && focusTab.parentNode !== document.body) document.body.appendChild(focusTab);
      else if (!focusMq.matches && focusTabHome && focusTab.parentNode === document.body) {
        const anchor = focusTabNext && focusTabNext.parentNode === focusTabHome ? focusTabNext : null;
        focusTabHome.insertBefore(focusTab, anchor);
      }
    }
    if (mq.matches) {
      if (menuBtn && menuBtn.parentNode !== document.body) document.body.appendChild(menuBtn);
      if (toolsBtn && toolsBtn.parentNode !== document.body) document.body.appendChild(toolsBtn);
      if (actions && actions.parentNode !== document.body) document.body.appendChild(actions);
      return;
    }
    if (menuBtn && menuBtn.parentNode !== toolbar) toolbar.insertBefore(menuBtn, toolbar.firstChild);
    if (actions && actions.parentNode !== toolbar) toolbar.appendChild(actions);
    if (toolsBtn && actions && toolsBtn.parentNode !== toolbar) toolbar.insertBefore(toolsBtn, actions);
    else if (toolsBtn && toolsBtn.parentNode !== toolbar) toolbar.appendChild(toolsBtn);
  }

  if (topBar && !topBar.id) topBar.id = 'site-top-bar';
  if (actions && !actions.id) actions.id = 'bible-tools-drawer';
  if (toolsBtn && actions) toolsBtn.setAttribute('aria-controls', actions.id);

  function closeFlyouts() {
    document.querySelectorAll('.bible-flyout.open, .bible-flyout-backdrop.open').forEach((node) => {
      node.classList.remove('open');
      if (node.classList.contains('bible-flyout')) node.setAttribute('aria-hidden', 'true');
    });
    document.querySelectorAll('.bible-flyout-trigger.active').forEach((node) => {
      node.classList.remove('active');
    });
  }

  function syncHidden() {
    const phone = mq.matches;
    const menuOpen = body.classList.contains('bible-menu-open');
    const toolsOpen = body.classList.contains('bible-tools-open');
    if (topBar) topBar.setAttribute('aria-hidden', phone && !menuOpen ? 'true' : 'false');
    if (actions) actions.setAttribute('aria-hidden', phone && !toolsOpen ? 'true' : 'false');
    if (title) {
      if (phone) {
        title.setAttribute('role', 'button');
        title.tabIndex = 0;
        title.title = 'Choose a book or chapter';
      } else {
        title.removeAttribute('role');
        title.removeAttribute('tabindex');
        title.removeAttribute('title');
      }
    }
  }

  /* Focus reading folds the chapter bar away to one edge tab. */
  function focusActive() {
    return body.classList.contains('bible-focus');
  }

  function applyFocus(on, remember) {
    if (!focusMq.matches) on = false;
    if (on && focusTab && focusTab.parentNode !== document.body) document.body.appendChild(focusTab);
    body.classList.toggle('bible-focus', on);
    if (hideBarBtn) hideBarBtn.setAttribute('aria-expanded', on ? 'false' : 'true');
    if (focusTab) focusTab.setAttribute('aria-expanded', on ? 'true' : 'false');
    if (toolbar) toolbar.setAttribute('aria-hidden', on ? 'true' : 'false');
    if (remember) {
      try { localStorage.setItem(FOCUS_KEY, on ? '1' : '0'); } catch (err) { /* private mode */ }
    }
    parkChrome();
  }

  if (hideBarBtn) {
    hideBarBtn.addEventListener('click', (event) => {
      event.preventDefault();
      applyFocus(true, true);
      syncHidden();
      if (focusTab) focusTab.focus();
    });
  }
  if (focusTab) {
    focusTab.addEventListener('click', (event) => {
      event.preventDefault();
      if (focusActive()) {
        applyFocus(false, true);
        syncHidden();
        /* The bar was folded, so bring it back into view rather than leaving
           the reader halfway down a chapter with nothing on screen. */
        if (body.classList.contains('bible-bar-offscreen')) scrollReaderToTop();
      } else {
        /* Not folded: the bar is simply off-screen, so go back to it. */
        scrollReaderToTop();
      }
      if (hideBarBtn && focusMq.matches) hideBarBtn.focus({ preventScroll: true });
    });
  }

  let storedFocus = null;
  try { storedFocus = localStorage.getItem(FOCUS_KEY); } catch (err) { /* private mode */ }

  function closeAll() {
    body.classList.remove('bible-menu-open', 'bible-tools-open');
    if (menuBtn) menuBtn.setAttribute('aria-expanded', 'false');
    if (toolsBtn) toolsBtn.setAttribute('aria-expanded', 'false');
    syncHidden();
  }

  function toggleDrawer(which) {
    if (!mq.matches) return;
    const open = !body.classList.contains(which);
    closeAll();
    if (!open) return;
    closeFlyouts();
    body.classList.add(which);
    const btn = which === 'bible-menu-open' ? menuBtn : toolsBtn;
    if (btn) btn.setAttribute('aria-expanded', 'true');
    syncHidden();
  }

  if (menuBtn) {
    menuBtn.addEventListener('click', (event) => {
      event.stopPropagation();
      toggleDrawer('bible-menu-open');
    });
  }
  if (toolsBtn) {
    toolsBtn.addEventListener('click', (event) => {
      event.stopPropagation();
      toggleDrawer('bible-tools-open');
    });
  }

  document.addEventListener('click', (event) => {
    if (!mq.matches) return;
    if (!body.classList.contains('bible-menu-open') && !body.classList.contains('bible-tools-open')) return;
    if (event.target.closest('header.top-bar, .bible-stage-toolbar-actions, .bible-edge-tab')) return;
    closeAll();
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      closeAll();
      applyFocus(false, true);
    }
  });

  document.querySelectorAll('.bible-flyout-trigger').forEach((btn) => {
    btn.addEventListener('click', () => closeAll());
  });

  function openBooks(event) {
    if (!mq.matches || !books) return;
    if (event) event.preventDefault();
    books.click();
  }
  if (title) {
    title.addEventListener('click', () => {
      if (mq.matches) books && books.click();
    });
    title.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') openBooks(event);
    });
  }

  const reader = document.querySelector('.bible-stage-main');
  if (reader) {
    let start = null;
    reader.addEventListener('touchstart', (event) => {
      if (!mq.matches || event.touches.length !== 1) return;
      if (body.classList.contains('bible-menu-open') || body.classList.contains('bible-tools-open')) return;
      const target = event.target;
      if (target && target.closest && target.closest('button, a, input, textarea, select, label')) return;
      start = { x: event.touches[0].clientX, y: event.touches[0].clientY };
    }, { passive: true });

    reader.addEventListener('touchend', (event) => {
      if (!start || !event.changedTouches.length) return;
      const dx = event.changedTouches[0].clientX - start.x;
      const dy = event.changedTouches[0].clientY - start.y;
      start = null;
      if (Math.abs(dx) < 64 || Math.abs(dx) < Math.abs(dy) * 1.4) return;
      const prev = document.getElementById('member-bible-prev') || document.getElementById('bible-prev-chapter');
      const next = document.getElementById('member-bible-next') || document.getElementById('bible-next-chapter');
      const button = dx < 0 ? next : prev;
      if (button && !button.disabled) button.click();
    }, { passive: true });

    reader.addEventListener('touchcancel', () => { start = null; }, { passive: true });
  }

  function onViewportChange() {
    parkChrome();
    queueBarSync();
    if (!mq.matches) closeAll();
    else syncHidden();
    applyFocus(focusActive(), false);
    if (!focusMq.matches) body.classList.remove('bible-bar-offscreen');
  }
  if (mq.addEventListener) mq.addEventListener('change', onViewportChange);
  else if (mq.addListener) mq.addListener(onViewportChange);
  if (focusMq.addEventListener) focusMq.addEventListener('change', onViewportChange);
  else if (focusMq.addListener) focusMq.addListener(onViewportChange);
  parkChrome();
  syncHidden();
  if (storedFocus === '1') applyFocus(true, false);
  queueBarSync();
})();
