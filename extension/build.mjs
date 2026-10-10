// Bundles the three extension entry points into dist/ and copies the static files.
// Load dist/ as an unpacked extension in chrome://extensions.
import { build } from 'esbuild';
import { cp, mkdir, rm } from 'node:fs/promises';

const out = 'dist';
await rm(out, { recursive: true, force: true });
await mkdir(out, { recursive: true });

const common = { bundle: true, sourcemap: false, target: 'chrome116', logLevel: 'info', define: { 'process.env.NODE_ENV': '"production"' } };

await Promise.all([
  // Module service worker: declared as "type": "module" in the manifest.
  build({ ...common, entryPoints: ['src/background.ts'], outfile: `${out}/background.js`, format: 'esm' }),
  // Injected with chrome.scripting as a classic script, so it must be self-contained.
  build({ ...common, entryPoints: ['src/content.ts'], outfile: `${out}/content.js`, format: 'iife' }),
  build({ ...common, entryPoints: ['src/picker.ts'], outfile: `${out}/picker.js`, format: 'iife' }),
  build({ ...common, entryPoints: ['src/sidepanel.tsx'], outfile: `${out}/sidepanel.js`, format: 'esm' }),
]);

await Promise.all([
  cp('manifest.json', `${out}/manifest.json`),
  cp('src/sidepanel.html', `${out}/sidepanel.html`),
  cp('src/sidepanel.css', `${out}/sidepanel.css`),
  cp('icons', `${out}/icons`, { recursive: true }),
]);
console.log(`Extension built in ${out}/`);
