import type { Analysis, BotComment, BotPost } from "./core.js";
import { BotError } from "./core.js";

export async function requestAnalysis(post: BotPost, comment: BotComment, options: {
  url: string; apiKey?: string; includeVision: boolean; timeoutMs?: number;
}): Promise<Analysis> {
  const images = post.imageBase64 ? [{ base64: post.imageBase64 }] : post.imageUrls.slice(0, 4).map(url => ({ url }));
  const response = await fetch(options.url.replace(/\/$/, "") + "/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(options.apiKey ? { "X-API-Key": options.apiKey } : {}) },
    signal: AbortSignal.timeout(options.timeoutMs ?? 240_000),
    body: JSON.stringify({ images, include_vision: options.includeVision, context: {
      title: post.title.slice(0, 2000), body: (post.body || "").slice(0, 14000),
      request: comment.body.slice(0, 4000), permalink: post.permalink || "",
    } }),
  });
  if (!response.ok) throw new BotError("SERVICE_ERROR", `Image service returned HTTP ${response.status}.`);
  const result: unknown = await response.json();
  if (!result || typeof result !== "object" || !("images" in result) || !Array.isArray(result.images) || result.images.length === 0) throw new BotError("SERVICE_ERROR", "Image service returned an invalid response.");
  // formatReply validates use through the outer error boundary; reject malformed fields here.
  for (const image of result.images) {
    if (!image?.ocr || typeof image.ocr.status !== "string" || !image.vision || typeof image.vision.status !== "string" || !Array.isArray(image.warnings)) throw new BotError("SERVICE_ERROR", "Image service returned malformed image data.");
  }
  return result as Analysis;
}
