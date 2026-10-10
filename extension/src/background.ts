// Service worker: context menus, capture, and the call to the fact-check backend.
import { cropRect, thumbnailSize } from './geometry.ts';
import {
  getBackendUrl,
  getJob,
  setJob,
  type ContentMessage,
  type Job,
  type JobInput,
  type PanelMessage,
  type Rect,
} from './shared.ts';

const MENU_SELECTION = 'signal-selection';
const MENU_IMAGE = 'signal-image';
const MENU_REGION = 'signal-region';

let controller: AbortController | null = null;
let keepAlive: ReturnType<typeof setInterval> | null = null;

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({ id: MENU_SELECTION, title: 'Check selected text with Signal', contexts: ['selection'] });
    chrome.contextMenus.create({ id: MENU_IMAGE, title: 'Check this image with Signal', contexts: ['image'] });
    chrome.contextMenus.create({
      id: MENU_REGION,
      title: 'Check a region of this page with Signal',
      contexts: ['page', 'selection', 'image', 'link'],
    });
  });
  void chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (!tab?.id) return;
  // Must run synchronously inside the click handler: opening the panel needs a user gesture.
  void chrome.sidePanel.open({ tabId: tab.id }).catch(() => undefined);
  const pageUrl = info.pageUrl ?? tab.url ?? '';
  if (info.menuItemId === MENU_SELECTION) {
    void runJob({ kind: 'text', caption: (info.selectionText ?? '').trim(), sourceUrl: pageUrl }, null);
  } else if (info.menuItemId === MENU_IMAGE && info.srcUrl) {
    void checkImage(info.srcUrl, info.selectionText ?? '', pageUrl, tab);
  } else if (info.menuItemId === MENU_REGION) {
    void startRegionSelection(tab);
  }
});

chrome.runtime.onMessage.addListener((message: PanelMessage | ContentMessage, sender) => {
  if (message.type === 'check-text') {
    void runJob({ kind: 'text', caption: message.caption.trim(), sourceUrl: '' }, null);
  } else if (message.type === 'cancel') {
    controller?.abort();
  } else if (message.type === 'region-selected' && sender.tab?.id !== undefined) {
    void captureRegion(sender.tab, message.rect, message.dpr);
  }
});

// ---------- capture paths ----------

async function checkImage(srcUrl: string, selection: string, pageUrl: string, tab: chrome.tabs.Tab) {
  const input: JobInput = { kind: 'image', caption: selection.trim(), sourceUrl: pageUrl };
  try {
    let blob = await fetchImage(srcUrl);
    if (!blob) blob = await captureImageElement(tab, srcUrl);
    await runJob(input, blob);
  } catch (error) {
    await failWithoutRun(input, error);
  }
}

/** Full-resolution original when the host allows it; null when CORS or the host say no. */
async function fetchImage(srcUrl: string): Promise<Blob | null> {
  try {
    const response = await fetch(srcUrl);
    if (!response.ok) return null;
    const blob = await response.blob();
    return blob.type.startsWith('image/') && blob.size > 0 ? blob : null;
  } catch {
    return null;
  }
}

/** Fallback: screenshot the visible tab and crop to the image element's box. */
async function captureImageElement(tab: chrome.tabs.Tab, srcUrl: string): Promise<Blob> {
  const [result] = await chrome.scripting.executeScript({
    target: { tabId: tab.id! },
    func: locateImage,
    args: [srcUrl],
  });
  const found = result?.result as { rect: Rect; dpr: number } | null | undefined;
  if (!found) throw new Error('Could not find that image on the page. Try selecting a region instead.');
  return cropVisibleTab(tab.windowId, found.rect, found.dpr);
}

/** Runs inside the page. Scrolls the image into view and reports its viewport box. */
function locateImage(src: string): { rect: { x: number; y: number; width: number; height: number }; dpr: number } | null {
  const images = Array.from(document.images);
  const img = images.find((el) => el.currentSrc === src || el.src === src) ?? null;
  if (!img) return null;
  img.scrollIntoView({ block: 'center', inline: 'center' });
  const box = img.getBoundingClientRect();
  const x = Math.max(0, box.left);
  const y = Math.max(0, box.top);
  const right = Math.min(window.innerWidth, box.right);
  const bottom = Math.min(window.innerHeight, box.bottom);
  if (right - x < 4 || bottom - y < 4) return null;
  return { rect: { x, y, width: right - x, height: bottom - y }, dpr: window.devicePixelRatio || 1 };
}

async function startRegionSelection(tab: chrome.tabs.Tab) {
  try {
    await chrome.scripting.executeScript({ target: { tabId: tab.id! }, files: ['content.js'] });
  } catch (error) {
    await failWithoutRun({ kind: 'region', caption: '', sourceUrl: tab.url ?? '' }, error);
  }
}

async function captureRegion(tab: chrome.tabs.Tab, rect: Rect, dpr: number) {
  const input: JobInput = { kind: 'region', caption: '', sourceUrl: tab.url ?? '' };
  try {
    const blob = await cropVisibleTab(tab.windowId, rect, dpr);
    await runJob(input, blob);
  } catch (error) {
    await failWithoutRun(input, error);
  }
}

async function cropVisibleTab(windowId: number, rect: Rect, dpr: number): Promise<Blob> {
  const dataUrl = await chrome.tabs.captureVisibleTab(windowId, { format: 'png' });
  const bitmap = await createImageBitmap(await (await fetch(dataUrl)).blob());
  const crop = cropRect(rect, dpr, bitmap.width, bitmap.height);
  if (!crop) throw new Error('The selected area is too small or off screen.');
  const canvas = new OffscreenCanvas(crop.width, crop.height);
  canvas.getContext('2d')!.drawImage(bitmap, crop.x, crop.y, crop.width, crop.height, 0, 0, crop.width, crop.height);
  return canvas.convertToBlob({ type: 'image/png' });
}

// ---------- the check itself ----------

async function runJob(input: JobInput, image: Blob | null) {
  if (input.kind === 'text' && !input.caption) {
    await setJob(errorJob(input, 'Select some text first.'));
    return;
  }
  controller?.abort();
  const own = new AbortController();
  controller = own;

  const job: Job = { id: crypto.randomUUID(), status: 'running', startedAt: Date.now(), input };
  if (image) job.input.preview = await makeThumbnail(image);
  await setJob(job);
  startKeepAlive();

  try {
    const form = new FormData();
    if (image) form.append('image', image, 'capture.png');
    form.append('caption', input.caption);
    form.append('ocr_text', '');
    if (input.sourceUrl) form.append('source_url', input.sourceUrl);
    const base = await getBackendUrl();
    let response: Response;
    try {
      response = await fetch(`${base}/check`, { method: 'POST', body: form, signal: own.signal });
    } catch (error) {
      if (own.signal.aborted) throw new Error('Cancelled.');
      throw new Error(`Could not reach the backend at ${base}. Start it, or change the URL in settings.`);
    }
    if (!response.ok) {
      const detail = await response.json().catch(() => null);
      throw new Error(typeof detail?.detail === 'string' ? detail.detail : `The backend returned HTTP ${response.status}.`);
    }
    const result = (await response.json()) as Job['result'];
    if (!(await isCurrent(job))) return;
    await setJob({ ...job, status: 'done', finishedAt: Date.now(), result });
  } catch (error) {
    if (await isCurrent(job)) await setJob({ ...job, ...errorJob(input, error), id: job.id, startedAt: job.startedAt });
  } finally {
    if (controller === own) controller = null;
    stopKeepAlive();
  }
}

async function isCurrent(job: Job): Promise<boolean> {
  const current = await getJob();
  return current?.id === job.id;
}

function errorJob(input: JobInput, error: unknown): Job {
  const message = error instanceof Error ? error.message : String(error);
  return { id: crypto.randomUUID(), status: 'error', startedAt: Date.now(), finishedAt: Date.now(), input, error: message };
}

async function failWithoutRun(input: JobInput, error: unknown) {
  await setJob(errorJob(input, error));
}

/** A check can take minutes; touching an extension API every 20 s keeps the worker alive. */
function startKeepAlive() {
  stopKeepAlive();
  keepAlive = setInterval(() => void chrome.runtime.getPlatformInfo(), 20_000);
}

function stopKeepAlive() {
  if (keepAlive) clearInterval(keepAlive);
  keepAlive = null;
}

async function makeThumbnail(image: Blob): Promise<string | undefined> {
  try {
    const bitmap = await createImageBitmap(image);
    const size = thumbnailSize(bitmap.width, bitmap.height, 480);
    const canvas = new OffscreenCanvas(size.width, size.height);
    canvas.getContext('2d')!.drawImage(bitmap, 0, 0, size.width, size.height);
    const blob = await canvas.convertToBlob({ type: 'image/jpeg', quality: 0.8 });
    return `data:image/jpeg;base64,${toBase64(await blob.arrayBuffer())}`;
  } catch {
    return undefined;
  }
}

function toBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = '';
  for (let i = 0; i < bytes.length; i += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  }
  return btoa(binary);
}
