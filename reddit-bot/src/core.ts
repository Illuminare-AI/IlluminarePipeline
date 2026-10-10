export type BotComment = {
  id: string; body: string; authorName: string; postId?: string;
  parentId?: string; subredditName?: string;
};
export type BotPost = {
  id: string; title: string; body?: string; permalink?: string;
  imageUrls: string[]; imageBase64?: string; removed?: boolean;
};
export type Analysis = {
  images: Array<{
    ocr: { status: string; text?: string };
    vision: { status: string; observations?: { description: string; uncertainties: string[] } };
    warnings: string[];
  }>;
};
export type Dependencies = {
  username: string;
  getPost(id: string): Promise<BotPost | undefined>;
  analyze(post: BotPost, comment: BotComment): Promise<Analysis>;
  reply(id: string, text: string): Promise<void>;
  claim(id: string): Promise<boolean>;
  complete(id: string): Promise<void>;
  release(id: string): Promise<void>;
};

export class BotError extends Error {
  constructor(public code: string, message: string) { super(message); }
}

export function isSummoned(body: string, username: string): boolean {
  const escaped = username.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`(?:^|[\\s(])/?u/${escaped}(?=$|[\\s,.!?:;)])`, "i").test(body);
}

export async function parentPost(comment: BotComment, deps: Pick<Dependencies, "getPost">): Promise<BotPost> {
  // postId identifies the containing submission even for nested replies.
  const id = comment.postId || (comment.parentId?.startsWith("t3_") ? comment.parentId : undefined);
  if (!id?.startsWith("t3_")) throw new BotError("NO_PARENT_POST", "I couldn't find the post you replied to. Mention me in a comment under an image post.");
  let post: BotPost | undefined;
  try { post = await deps.getPost(id); } catch { /* Deleted/inaccessible post is a user-visible error. */ }
  if (!post || post.removed) throw new BotError("POST_UNAVAILABLE", "The parent post is deleted, removed, or unavailable.");
  if (!post.imageBase64 && !post.imageUrls.length) throw new BotError("NO_IMAGE", "The parent post has no supported image to analyze. Videos and external article pages aren't supported yet.");
  return post;
}

function quote(text: string): string {
  // Render extracted/model text as quotation; neutralize markdown links/mentions.
  return text.slice(0, 1800).replace(/([\\`*_{}\[\]<>])/g, "\\$1").replace(/\r/g, "").split("\n").map(line => `> ${line}`).join("\n");
}

export function formatReply(result: Analysis): string {
  const parts = ["Image context — automated extraction, not a fact-check."];
  for (const [index, image] of result.images.entries()) {
    parts.push(`\nImage ${index + 1}`);
    if (image.ocr.status === "ok") parts.push("Visible text:\n" + quote(image.ocr.text || "No text detected."));
    else parts.push("OCR is unavailable; no transcription was produced.");
    if (image.vision.status === "ok" && image.vision.observations) {
      parts.push("Image description:\n" + quote(image.vision.observations.description));
      if (image.vision.observations.uncertainties.length) parts.push("Uncertainties:\n" + quote(image.vision.observations.uncertainties.join("; ")));
    } else parts.push(`Image description: ${image.vision.status}.`);
    for (const warning of image.warnings) parts.push(quote(warning));
  }
  return parts.join("\n\n").slice(0, 9000);
}

export async function handleMention(comment: BotComment, deps: Dependencies): Promise<string> {
  if (comment.authorName.toLowerCase() === deps.username.toLowerCase() || !isSummoned(comment.body, deps.username)) return "ignored";
  if (!(await deps.claim(comment.id))) return "duplicate";
  try {
    let text: string;
    try {
      const post = await parentPost(comment, deps);
      text = formatReply(await deps.analyze(post, comment));
    } catch (error) {
      text = error instanceof BotError ? `${error.code}: ${error.message}` : "ANALYSIS_FAILED: Image analysis is unavailable. Please try again later.";
    }
    await deps.reply(comment.id, text);
    await deps.complete(comment.id);
    return "replied";
  } catch (error) {
    // Retain the claim when posting fails ambiguously: a reply may have succeeded.
    // This scaffold favors avoiding duplicates; reconcile failures before retrying.
    throw error;
  }
}
