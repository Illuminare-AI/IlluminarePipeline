import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { handleMention, type BotComment, type BotPost } from "./core.js";
import { requestAnalysis } from "./client.js";

const args = process.argv.slice(2);
const value = (flag: string) => { const index = args.indexOf(flag); return index >= 0 ? args[index + 1] : undefined; };
const fixture = JSON.parse(await readFile(resolve(value("--fixture") || "fixtures/mention.json"), "utf8")) as { comment: BotComment; post?: BotPost };
const imagePath = value("--image");
if (imagePath && fixture.post) fixture.post.imageBase64 = (await readFile(resolve(imagePath))).toString("base64");
const claimed = new Set<string>();
await handleMention(fixture.comment, {
  username: process.env.BOT_USERNAME || "signal-context-demo",
  getPost: async id => fixture.post?.id === id ? fixture.post : undefined,
  analyze: (post, comment) => requestAnalysis(post, comment, {
    url: process.env.CONTEXT_SERVICE_URL || "http://127.0.0.1:8001",
    apiKey: process.env.CONTEXT_API_KEY, includeVision: process.env.DEMO_INCLUDE_VISION !== "false",
  }),
  claim: async id => { if (claimed.has(id)) return false; claimed.add(id); return true; },
  complete: async () => {}, release: async id => { claimed.delete(id); },
  reply: async (_id, text) => { console.log("DEMO ONLY — would reply:\n\n" + text); },
});
