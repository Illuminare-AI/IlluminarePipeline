import assert from 'node:assert/strict';
import { test } from 'node:test';

import { cropRect, dragToRect, thumbnailSize } from '../src/geometry.ts';

test('dragToRect normalises a drag in any direction', () => {
  assert.deepEqual(dragToRect(100, 80, 20, 30), { x: 20, y: 30, width: 80, height: 50 });
  assert.deepEqual(dragToRect(20, 30, 100, 80), { x: 20, y: 30, width: 80, height: 50 });
});

test('cropRect scales by device pixel ratio and clamps to the screenshot', () => {
  const rect = { x: 10, y: 20, width: 100, height: 50 };
  assert.deepEqual(cropRect(rect, 2, 1000, 1000), { x: 20, y: 40, width: 200, height: 100 });
  // Partly off the right edge: width is cut to what the screenshot holds.
  assert.deepEqual(cropRect({ x: 950, y: 0, width: 100, height: 50 }, 1, 1000, 1000), { x: 950, y: 0, width: 50, height: 50 });
});

test('cropRect rejects selections that are off screen or tiny', () => {
  assert.equal(cropRect({ x: 2000, y: 0, width: 50, height: 50 }, 1, 1000, 1000), null);
  assert.equal(cropRect({ x: 0, y: 0, width: 2, height: 2 }, 1, 1000, 1000), null);
});

test('thumbnailSize never upscales and keeps the aspect ratio', () => {
  assert.deepEqual(thumbnailSize(200, 100, 480), { width: 200, height: 100 });
  assert.deepEqual(thumbnailSize(1920, 1080, 480), { width: 480, height: 270 });
});
