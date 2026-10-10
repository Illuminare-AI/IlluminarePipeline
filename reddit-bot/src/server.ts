import { Hono } from "hono";
import { getRequestListener } from "@hono/node-server";
import { settings, reddit, redis, createServer, getServerPort } from "@devvit/web/server";
import { handleMention, type BotComment, type BotPost, BotError } from "./core.js";
import { requestAnalysis } from "./client.js";
import { liveConfig } from "./live-config.js";

const app = new Hono();
// Devvit exports GalleryMediaStatus as a type; VALID is wire enum value 1.
const VALID_GALLERY_MEDIA = 1;
app.post("/internal/comment-created", async c => {
  const event = await c.req.json();
  if (!event.comment?.id) return c.json({ status: "ignored" });
  // Re-fetch authoritative comment rather than trusting a payload snapshot.
  const source = await reddit.getCommentById(event.comment.id);
  const comment: BotComment = {
    id: source.id, body: source.body, authorName: source.authorName,
    postId: source.postId, parentId: source.parentId,
  };
  const status = await handleMention(comment, {
    username: liveConfig.username,
    getPost: async id => {
      const post = await reddit.getPostById(id as `t3_${string}`);
      const images = post.gallery.filter(media => media.status === VALID_GALLERY_MEDIA).map(media => media.url.replace(/&amp;/g, "&"));
      if (!images.length && /^https:\/\/i\.redd\.it\/.+\.(png|jpe?g|webp)(?:\?|$)/i.test(post.url)) images.push(post.url);
      return { id: post.id, title: post.title, body: post.body, permalink: post.permalink,
        imageUrls: [...new Set(images)], removed: post.removed } satisfies BotPost;
    },
    analyze: async (post, trigger) => {
      if (!liveConfig.externalOcrApproved || !liveConfig.serviceUrl.startsWith("https://")) throw new BotError("LIVE_NOT_CONFIGURED", "This demo isn't connected to an approved image service yet.");
      const apiKey = await settings.get<string>("CONTEXT_API_KEY");
      if (!apiKey) throw new BotError("LIVE_NOT_CONFIGURED", "The image service API key hasn't been configured.");
      return requestAnalysis(post, trigger, { url: liveConfig.serviceUrl,
        apiKey, includeVision: false, timeoutMs: 25_000 });
    },
    reply: async (id, text) => { await reddit.submitComment({ id: id as `t1_${string}`, text }); },
    // Atomic NX claim prevents duplicate trigger deliveries from double-posting.
    claim: async id => !!(await redis.set(`reply:${id}`, "pending", { nx: true, expiration: new Date(Date.now() + 7 * 86400_000) })),
    complete: async id => { await redis.set(`reply:${id}`, "done", { expiration: new Date(Date.now() + 7 * 86400_000) }); },
    release: async id => { await redis.del(`reply:${id}`); },
  });
  return c.json({ status });
});

createServer(getRequestListener(app.fetch)).listen(getServerPort());
