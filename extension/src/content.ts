// Injected on demand: lets the user drag a rectangle, then reports it to the service worker.
// Self-contained classic script (no imports), see build.mjs.
(() => {
  const flag = '__signalRegionSelectorActive';
  const w = window as unknown as Record<string, boolean>;
  if (w[flag]) return;
  w[flag] = true;

  const overlay = document.createElement('div');
  overlay.setAttribute('style', [
    'position:fixed', 'inset:0', 'z-index:2147483647', 'cursor:crosshair',
    'background:rgba(20,30,25,0.28)', 'user-select:none',
  ].join(';'));
  const box = document.createElement('div');
  box.setAttribute('style', [
    'position:fixed', 'display:none', 'border:2px solid #f5f6f1', 'border-radius:3px',
    'box-shadow:0 0 0 100vmax rgba(20,30,25,0.28)', 'background:transparent', 'pointer-events:none',
  ].join(';'));
  const hint = document.createElement('div');
  hint.textContent = 'Drag to select the part to check. Press Esc to cancel.';
  hint.setAttribute('style', [
    'position:fixed', 'top:16px', 'left:50%', 'transform:translateX(-50%)', 'padding:8px 14px',
    'border-radius:999px', 'background:#293e33', 'color:#f5f6f1', 'font:13px/1.4 system-ui,sans-serif',
    'pointer-events:none',
  ].join(';'));
  overlay.append(box, hint);
  overlay.style.background = 'transparent';
  document.documentElement.append(overlay);

  let startX = 0;
  let startY = 0;
  let dragging = false;

  const rectFrom = (x2: number, y2: number) => ({
    x: Math.min(startX, x2), y: Math.min(startY, y2), width: Math.abs(x2 - startX), height: Math.abs(y2 - startY),
  });

  const cleanup = () => {
    overlay.remove();
    window.removeEventListener('keydown', onKey, true);
    w[flag] = false;
  };

  const send = (message: unknown) => {
    // Wait for the overlay to be gone before the worker screenshots the tab.
    requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(() => chrome.runtime.sendMessage(message), 60)));
  };

  const onKey = (event: KeyboardEvent) => {
    if (event.key !== 'Escape') return;
    event.preventDefault();
    cleanup();
    chrome.runtime.sendMessage({ type: 'region-cancelled' });
  };

  overlay.addEventListener('mousedown', (event) => {
    event.preventDefault();
    dragging = true;
    startX = event.clientX;
    startY = event.clientY;
    box.style.display = 'block';
    overlay.style.background = 'transparent';
    const r = rectFrom(startX, startY);
    Object.assign(box.style, { left: `${r.x}px`, top: `${r.y}px`, width: `${r.width}px`, height: `${r.height}px` });
  });
  overlay.addEventListener('mousemove', (event) => {
    if (!dragging) return;
    const r = rectFrom(event.clientX, event.clientY);
    Object.assign(box.style, { left: `${r.x}px`, top: `${r.y}px`, width: `${r.width}px`, height: `${r.height}px` });
  });
  overlay.addEventListener('mouseup', (event) => {
    if (!dragging) return;
    dragging = false;
    const rect = rectFrom(event.clientX, event.clientY);
    cleanup();
    if (rect.width < 8 || rect.height < 8) {
      chrome.runtime.sendMessage({ type: 'region-cancelled' });
      return;
    }
    send({ type: 'region-selected', rect, dpr: window.devicePixelRatio || 1 });
  });
  window.addEventListener('keydown', onKey, true);
})();
