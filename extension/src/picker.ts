// Injected on demand: hover to highlight the post container under the cursor, click to pick it.
// Reads the post text, its main image and permalink from the DOM so the backend can skip OCR
// and the vision model for the text. Arrow Up widens to the parent, Arrow Down narrows again.
import { cleanPostText, pickPermalink } from './postText.ts';

type Picked = {
  type: 'element-selected';
  text: string;
  permalink: string;
  timestamp: string;
  imageUrl: string;
  imageRect: { x: number; y: number; width: number; height: number } | null;
  dpr: number;
};

(() => {
  const flag = '__luminatePostPickerActive';
  const w = window as unknown as Record<string, boolean>;
  if (w[flag]) return;
  w[flag] = true;

  const CONTAINER = 'article, [role="article"], shreddit-post, [data-testid="tweet"], [data-testid="post-container"]';
  const SKIP = 'time, button, [role="button"], [aria-hidden="true"], nav, script, style, svg, noscript, [data-testid="caret"]';

  // ---- overlay ----
  const outline = document.createElement('div');
  outline.setAttribute('style', [
    'position:fixed', 'z-index:2147483647', 'pointer-events:none', 'border:2px solid #2f6b4f',
    'border-radius:6px', 'background:rgba(47,107,79,0.10)', 'box-shadow:0 0 0 2px rgba(245,246,241,0.9)',
    'transition:all 60ms ease-out', 'display:none',
  ].join(';'));
  const hint = document.createElement('div');
  hint.textContent = 'Hover a post and click to check it. ↑ widens, ↓ narrows, Esc cancels.';
  hint.setAttribute('style', [
    'position:fixed', 'z-index:2147483647', 'top:16px', 'left:50%', 'transform:translateX(-50%)',
    'padding:8px 14px', 'border-radius:999px', 'background:#293e33', 'color:#f5f6f1',
    'font:13px/1.4 system-ui,sans-serif', 'pointer-events:none',
  ].join(';'));
  document.documentElement.append(outline, hint);
  document.documentElement.style.cursor = 'crosshair';

  let current: Element | null = null;
  let narrower: Element[] = []; // where Arrow Down goes back to

  // ---- DOM helpers that cross shadow roots ----
  const parentOf = (el: Element): Element | null => {
    if (el.parentElement) return el.parentElement;
    const root = el.getRootNode();
    return root instanceof ShadowRoot ? root.host : null;
  };

  const matchesUp = (el: Element, selector: string): Element | null => {
    let node: Element | null = el;
    while (node) {
      if (node.matches(selector)) return node;
      node = parentOf(node);
    }
    return null;
  };

  const bigEnough = (el: Element) => {
    const r = el.getBoundingClientRect();
    return r.width >= 240 && r.height >= 60 && r.height <= window.innerHeight * 1.5 && r.width <= window.innerWidth;
  };

  /** The post container for a hovered node: a semantic article when there is one, else the smallest sizeable ancestor. */
  const containerFor = (target: Element): Element | null => {
    const semantic = matchesUp(target, CONTAINER);
    if (semantic && bigEnough(semantic)) return semantic;
    let node: Element | null = target;
    while (node && node !== document.body && node !== document.documentElement) {
      if (bigEnough(node) && textOf(node).length >= 40) return node;
      node = parentOf(node);
    }
    return null;
  };

  const forEachElement = (root: Element | ShadowRoot, fn: (el: Element) => void) => {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
    let node = walker.nextNode() as Element | null;
    while (node) {
      fn(node);
      if (node.shadowRoot) forEachElement(node.shadowRoot, fn);
      node = walker.nextNode() as Element | null;
    }
  };

  const visible = (el: Element) => (el as HTMLElement).checkVisibility?.({ checkOpacity: false }) ?? true;

  const BLOCK = new Set(['P', 'DIV', 'LI', 'BR', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'BLOCKQUOTE', 'SECTION', 'ARTICLE', 'TR', 'PRE']);

  /** Text of the element as the reader sees it, one line per block, without interface chrome. */
  const textLines = (root: Element): string[] => {
    const lines: string[] = [];
    let buffer = '';
    const flush = () => { if (buffer.trim()) lines.push(buffer); buffer = ''; };
    const walk = (node: Node) => {
      if (node.nodeType === Node.TEXT_NODE) {
        buffer += node.textContent ?? '';
        return;
      }
      if (!(node instanceof Element)) return;
      if (node.matches(SKIP) || !visible(node)) return;
      if (node instanceof HTMLImageElement && node.alt && /emoji/i.test(node.className)) { buffer += node.alt; return; }
      const block = BLOCK.has(node.tagName);
      if (block) flush();
      if (node.shadowRoot) node.shadowRoot.childNodes.forEach(walk);
      node.childNodes.forEach(walk);
      if (block) flush();
    };
    walk(root);
    flush();
    return lines;
  };

  const textOf = (el: Element) => cleanPostText(textLines(el));

  /** Largest visible content image; avatars (small or round) and icons are skipped. */
  const mainImage = (root: Element): HTMLImageElement | null => {
    let best: HTMLImageElement | null = null;
    let bestArea = 0;
    forEachElement(root, (el) => {
      if (!(el instanceof HTMLImageElement) || !visible(el)) return;
      const r = el.getBoundingClientRect();
      if (r.width < 120 || r.height < 120) return;
      const radius = getComputedStyle(el).borderRadius;
      if (/%$/.test(radius) && parseFloat(radius) >= 50) return;
      if (/avatar|profile|emoji|icon/i.test(`${el.className} ${el.alt} ${el.src}`)) return;
      const area = r.width * r.height;
      if (area > bestArea) { best = el; bestArea = area; }
    });
    return best;
  };

  const hrefsOf = (root: Element): string[] => {
    const out: string[] = [];
    forEachElement(root, (el) => { if (el instanceof HTMLAnchorElement && el.href) out.push(el.href); });
    return out;
  };

  const timestampOf = (root: Element): string => {
    let found = '';
    forEachElement(root, (el) => { if (!found && el instanceof HTMLTimeElement && el.dateTime) found = el.dateTime; });
    return found;
  };

  // ---- interaction ----
  const show = (el: Element | null) => {
    current = el;
    if (!el) { outline.style.display = 'none'; return; }
    const r = el.getBoundingClientRect();
    Object.assign(outline.style, { display: 'block', left: `${r.left}px`, top: `${r.top}px`, width: `${r.width}px`, height: `${r.height}px` });
  };

  const cleanup = () => {
    outline.remove();
    hint.remove();
    document.documentElement.style.cursor = '';
    window.removeEventListener('mousemove', onMove, true);
    window.removeEventListener('click', onClick, true);
    window.removeEventListener('keydown', onKey, true);
    w[flag] = false;
  };

  const onMove = (event: MouseEvent) => {
    const target = (event.composedPath()[0] as Element | undefined) ?? (event.target as Element | null);
    if (!target || target === outline || target === hint || !(target instanceof Element)) return;
    const container = containerFor(target);
    if (container && container !== current) { narrower = []; show(container); }
  };

  const onClick = (event: MouseEvent) => {
    event.preventDefault();
    event.stopPropagation();
    if (!current) return;
    const el = current;
    const text = textOf(el);
    const img = mainImage(el);
    let imageRect: Picked['imageRect'] = null;
    if (img) {
      const r = img.getBoundingClientRect();
      const x = Math.max(0, r.left);
      const y = Math.max(0, r.top);
      const right = Math.min(window.innerWidth, r.right);
      const bottom = Math.min(window.innerHeight, r.bottom);
      if (right - x >= 4 && bottom - y >= 4) imageRect = { x, y, width: right - x, height: bottom - y };
    }
    const message: Picked = {
      type: 'element-selected',
      text,
      permalink: pickPermalink(hrefsOf(el), location.href),
      timestamp: timestampOf(el),
      imageUrl: img?.currentSrc || img?.src || '',
      imageRect,
      dpr: window.devicePixelRatio || 1,
    };
    cleanup();
    // Let the outline disappear before the worker screenshots the image box.
    requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(() => chrome.runtime.sendMessage(message), 60)));
  };

  const onKey = (event: KeyboardEvent) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      cleanup();
      chrome.runtime.sendMessage({ type: 'region-cancelled' });
    } else if (event.key === 'ArrowUp' && current) {
      event.preventDefault();
      const parent = parentOf(current);
      if (parent && parent !== document.documentElement) { narrower.push(current); show(parent); }
    } else if (event.key === 'ArrowDown' && narrower.length) {
      event.preventDefault();
      show(narrower.pop()!);
    }
  };

  window.addEventListener('mousemove', onMove, true);
  window.addEventListener('click', onClick, true);
  window.addEventListener('keydown', onKey, true);
})();
