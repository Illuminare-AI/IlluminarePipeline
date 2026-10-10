// Pure helpers for turning a selection in CSS pixels into a crop of a tab screenshot.
import type { Rect } from './shared.ts';

/** Normalise a drag from (x1, y1) to (x2, y2) into a rectangle with positive size. */
export function dragToRect(x1: number, y1: number, x2: number, y2: number): Rect {
  return {
    x: Math.min(x1, x2),
    y: Math.min(y1, y2),
    width: Math.abs(x2 - x1),
    height: Math.abs(y2 - y1),
  };
}

/**
 * Scale a CSS-pixel rectangle by the device pixel ratio and clamp it to the screenshot.
 * Returns null when nothing usable remains (off-screen or smaller than a few pixels).
 */
export function cropRect(rect: Rect, dpr: number, imageWidth: number, imageHeight: number): Rect | null {
  const x1 = Math.max(0, Math.round(rect.x * dpr));
  const y1 = Math.max(0, Math.round(rect.y * dpr));
  const x2 = Math.min(imageWidth, Math.round((rect.x + rect.width) * dpr));
  const y2 = Math.min(imageHeight, Math.round((rect.y + rect.height) * dpr));
  const width = x2 - x1;
  const height = y2 - y1;
  if (width < 4 || height < 4) return null;
  return { x: x1, y: y1, width, height };
}

/** Size that fits `width` x `height` inside a `max` square without upscaling. */
export function thumbnailSize(width: number, height: number, max: number): { width: number; height: number } {
  const scale = Math.min(1, max / Math.max(width, height, 1));
  return { width: Math.max(1, Math.round(width * scale)), height: Math.max(1, Math.round(height * scale)) };
}
