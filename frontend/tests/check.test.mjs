import assert from 'node:assert/strict';
import { test } from 'node:test';
import { build } from 'esbuild';

const compiled = await build({ entryPoints: ['src/check.ts'], bundle: true, write: false,
  format: 'esm', define: { 'import.meta.env': '{}' } });
const { checkScreenshot, sourceUrl, exampleText } = await import(
  `data:text/javascript;base64,${Buffer.from(compiled.outputFiles[0].text).toString('base64')}`);
const card = { check_id: '123', analysis_mode: 'fake', claims: [], origin: {}, stages: {}, persuasion: [] };

test('uploads image, caption and OCR as multipart, preserving signal and every claim', async () => {
  const image = new File(['bytes'], 'post.png', { type: 'image/png' });
  const signal = new AbortController().signal;
  const result = { ...card, claims: [{ claim: 'first' }, { claim: 'second' }] };
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async (url, init) => {
      assert.equal(url, '/api/check');
      assert.equal(init.signal, signal);
      assert.equal(init.body.get('image').name, 'post.png');
      assert.equal(init.body.get('caption'), 'context');
      assert.equal(init.body.get('ocr_text'), 'image text');
      assert.equal(init.headers, undefined); // Browser must supply the multipart boundary.
      return Response.json(result);
    };
    assert.deepEqual(await checkScreenshot({ image, caption: 'context', ocrText: 'image text', isExample: false }, signal), result);
  } finally { globalThis.fetch = original; }
});

test('fictional example sends its text without claiming to upload its preview', async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async (_url, init) => {
      assert.equal(init.body.get('image'), null);
      assert.equal(init.body.get('ocr_text'), exampleText);
      return Response.json(card);
    };
    await checkScreenshot({ image: null, caption: '', ocrText: '', isExample: true }, new AbortController().signal);
  } finally { globalThis.fetch = original; }
});

test('surfaces service and connection errors and preserves cancellation', async () => {
  const original = globalThis.fetch;
  const input = { image: null, caption: 'test', ocrText: '', isExample: false };
  try {
    globalThis.fetch = async () => Response.json({ detail: 'image too large' }, { status: 413 });
    await assert.rejects(checkScreenshot(input, new AbortController().signal), /image too large/);
    globalThis.fetch = async () => { throw new TypeError('fetch failed'); };
    await assert.rejects(checkScreenshot(input, new AbortController().signal), /Could not reach/);
    const controller = new AbortController();
    controller.abort();
    globalThis.fetch = async () => { throw new DOMException('Cancelled', 'AbortError'); };
    await assert.rejects(checkScreenshot(input, controller.signal), { name: 'AbortError' });
    globalThis.fetch = async () => Response.json({ message: 'wrong endpoint' });
    await assert.rejects(checkScreenshot(input, new AbortController().signal), /unexpected response/);
  } finally { globalThis.fetch = original; }
});

test('source links allow only absolute web URLs', () => {
  assert.equal(sourceUrl('https://example.com/evidence'), 'https://example.com/evidence');
  for (const url of ['javascript:alert(1)', 'data:text/html,hi', '/relative', 'bad url']) {
    assert.equal(sourceUrl(url), undefined);
  }
});
