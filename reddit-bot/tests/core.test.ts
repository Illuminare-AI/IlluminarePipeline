import { test } from "node:test";
import assert from "node:assert/strict";
import { handleMention, parentPost, isSummoned, type Dependencies, type BotComment } from "../src/core.js";
import { requestAnalysis } from "../src/client.js";

const comment: BotComment = { id: "t1_trigger", postId: "t3_parent", parentId: "t1_nested", authorName: "someone", body: "u/signal-context-demo describe this" };
function setup() {
  const replies: string[] = [];
  const claimed = new Set<string>();
  let calls = 0;
  const deps: Dependencies = {
    username: "signal-context-demo",
    getPost: async id => ({ id, title: "Demo", imageUrls: ["https://i.redd.it/image.png"] }),
    analyze: async () => { calls++; return { images: [{ ocr: { status: "ok", text: "HELLO" }, vision: { status: "disabled" }, warnings: [] }] }; },
    reply: async (_id, text) => { replies.push(text); },
    claim: async id => { if (claimed.has(id)) return false; claimed.add(id); return true; },
    complete: async () => {}, release: async id => { claimed.delete(id); },
  };
  return { deps, replies, calls: () => calls };
}

test("exact mention matching avoids other usernames and regular discussion", () => {
  assert.equal(isSummoned("/u/Signal-Context-Demo, help", "signal-context-demo"), true);
  assert.equal(isSummoned("u/signal-context-demo-other help", "signal-context-demo"), false);
  assert.equal(isSummoned("signal-context-demo is nice", "signal-context-demo"), false);
});
test("nested comment resolves containing post", async () => {
  const { deps } = setup();
  let fetched = "";
  const original = deps.getPost;
  deps.getPost = async id => { fetched = id; return original(id); };
  await parentPost(comment, deps);
  assert.equal(fetched, "t3_parent");
});
test("no parent produces error reply without inference", async () => {
  const s = setup();
  await handleMention({ ...comment, postId: undefined, parentId: undefined }, s.deps);
  assert.match(s.replies[0], /NO_PARENT_POST/);
  assert.equal(s.calls(), 0);
});
test("deleted post and no-image post do not call inference", async () => {
  for (const post of [undefined, { id: "t3_parent", title: "text", imageUrls: [] }]) {
    const s = setup(); s.deps.getPost = async () => post;
    await handleMention(comment, s.deps);
    assert.match(s.replies[0], /POST_UNAVAILABLE|NO_IMAGE/);
    assert.equal(s.calls(), 0);
  }
});
test("duplicate deliveries and self mentions do not reply twice", async () => {
  const s = setup();
  assert.equal(await handleMention(comment, s.deps), "replied");
  assert.equal(await handleMention(comment, s.deps), "duplicate");
  assert.equal(await handleMention({ ...comment, id: "t1_self", authorName: s.deps.username }, s.deps), "ignored");
  assert.equal(s.replies.length, 1);
  assert.match(s.replies[0], /HELLO/);
});
test("inference failure returns a useful error", async () => {
  const s = setup(); s.deps.analyze = async () => { throw new Error("offline"); };
  await handleMention(comment, s.deps);
  assert.match(s.replies[0], /ANALYSIS_FAILED/);
});
test("ambiguous posting failure keeps claim to prevent duplicate posting", async () => {
  const s = setup(); s.deps.reply = async () => { throw new Error("timeout"); };
  await assert.rejects(handleMention(comment, s.deps), /timeout/);
  assert.equal(await handleMention(comment, s.deps), "duplicate");
});
test("service request carries parent content and explicit vision mode", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async (_url, init) => {
    const body = JSON.parse(String(init?.body));
    assert.equal(body.context.title, "parent title");
    assert.equal(body.context.request, comment.body);
    assert.equal(body.include_vision, false);
    assert.deepEqual(body.images, [{ url: "https://i.redd.it/a.png" }]);
    return new Response(JSON.stringify({ images: [{ ocr: { status: "ok", text: "hi" }, vision: { status: "disabled" }, warnings: [] }] }));
  };
  try {
    await requestAnalysis({ id: "t3_parent", title: "parent title", imageUrls: ["https://i.redd.it/a.png"] }, comment, { url: "http://localhost:8000", includeVision: false });
  } finally { globalThis.fetch = original; }
});
