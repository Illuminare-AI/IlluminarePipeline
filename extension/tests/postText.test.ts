import assert from 'node:assert/strict';
import { test } from 'node:test';

import { cleanPostText, pickPermalink } from '../src/postText.ts';

test('cleanPostText keeps the post and drops interface chrome', () => {
  const text = cleanPostText([
    'BBC News',
    '@BBCNews',
    '11:24 AM · Oct 10, 2026',
    'A man has died after entering a tiger enclosure at Yorkshire Wildlife Park, police say.',
    '417.2K Views',
    '1.2K reposts',
    '3.4K   likes',
    'Reply',
    'Show more',
    '2h',
    'A man has died after entering a tiger enclosure at Yorkshire Wildlife Park, police say.',
  ]);
  assert.equal(text, 'BBC News\n@BBCNews\nA man has died after entering a tiger enclosure at Yorkshire Wildlife Park, police say.');
});

test('cleanPostText keeps numbers that are part of a sentence', () => {
  assert.equal(cleanPostText(['The video has 417K views and that is the problem.']), 'The video has 417K views and that is the problem.');
});

test('cleanPostText caps very long text', () => {
  const text = cleanPostText(['x'.repeat(5000)]);
  assert.equal(text.length, 4000);
  assert.ok(text.endsWith('…'));
});

test('pickPermalink prefers a post permalink over the page', () => {
  const hrefs = ['https://x.com/home', 'https://x.com/BBCNews', 'https://x.com/BBCNews/status/12345', 'https://x.com/i/bookmarks'];
  assert.equal(pickPermalink(hrefs, 'https://x.com/home'), 'https://x.com/BBCNews/status/12345');
  assert.equal(pickPermalink(['https://www.reddit.com/r/news/comments/abc123/title/'], 'https://www.reddit.com/r/news/'), 'https://www.reddit.com/r/news/comments/abc123/title/');
  assert.equal(pickPermalink(['https://example.com/about'], 'https://example.com/article'), 'https://example.com/article');
});
