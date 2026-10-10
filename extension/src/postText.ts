// Pure helpers for turning the text found inside a post container into a clean caption.
// Kept free of DOM access so they can be unit-tested with node:test.

/** Lines that are interface text rather than the post: counters, timestamps, platform chrome. */
const INTERFACE_LINE = new RegExp(
  [
    String.raw`^\s*[\d.,]+\s*[kKmM]?\s*(views?|likes?|reposts?|retweets?|replies|comments?|shares?|followers?|quotes?|bookmarks?|upvotes?|awards?)\b`,
    String.raw`^\s*(reply|repost|retweet|like|share|bookmark|save|report|follow|subscribe|translate post|show more|see more|read more|view more|more|…|\.\.\.)\s*$`,
    String.raw`^\s*(promoted|sponsored|ad)\s*$`,
    String.raw`^\s*\d{1,2}:\d{2}\s*(am|pm)?(\s*[·•]\s*.*)?$`,
    String.raw`^\s*[·•]\s*$`,
    String.raw`^\s*(\d+\s*[hmsdw]|\d+\s*(hours?|minutes?|seconds?|days?|weeks?)\s*ago|yesterday|just now)\s*$`,
    String.raw`^\s*(joined|posted|edited)\b`,
  ].join('|'),
  'i',
);

const MAX_CAPTION = 4000;

/** Collapse whitespace, drop interface lines and duplicates, cap the length. */
export function cleanPostText(lines: string[]): string {
  const seen = new Set<string>();
  const kept: string[] = [];
  for (const raw of lines) {
    const line = raw.replace(/\s+/g, ' ').trim();
    if (!line || INTERFACE_LINE.test(line)) continue;
    const key = line.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    kept.push(line);
  }
  let text = kept.join('\n');
  if (text.length > MAX_CAPTION) text = `${text.slice(0, MAX_CAPTION - 1).trimEnd()}…`;
  return text;
}

/** Permalink-looking hrefs win over the page URL: a post inside a feed should cite itself. */
export function pickPermalink(hrefs: string[], pageUrl: string): string {
  const patterns = [/\/status\/\d+/, /\/comments\/[a-z0-9]+/i, /\/posts?\/[A-Za-z0-9_-]+/, /\/p\/[A-Za-z0-9_-]+/, /\/video\/\d+/];
  for (const pattern of patterns) {
    const hit = hrefs.find((h) => pattern.test(h));
    if (hit) return hit;
  }
  return pageUrl;
}
