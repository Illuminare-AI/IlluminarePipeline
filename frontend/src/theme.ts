// Display settings shared by the web app and the browser extension: text size, light/dark
// mode and a colour palette. Both stylesheets reference every colour as `var(--c-<hex>)`
// (see scripts/themeify-css.py), so a theme is applied by recomputing those variables from
// the original light-mode palette at runtime. Status colours (reds, ambers) keep their hue.

export type ThemeMode = 'system' | 'light' | 'dark';
export type PaletteName = 'forest' | 'ocean' | 'plum' | 'ember' | 'slate';

export type UiSettings = { textScale: number; mode: ThemeMode; palette: PaletteName };

export const DEFAULT_UI: UiSettings = { textScale: 1, mode: 'system', palette: 'forest' };

export const TEXT_SIZES: { label: string; scale: number }[] = [
  { label: 'Small', scale: 0.9 },
  { label: 'Default', scale: 1 },
  { label: 'Large', scale: 1.15 },
  { label: 'Larger', scale: 1.3 },
];

export const MODES: { label: string; mode: ThemeMode }[] = [
  { label: 'System', mode: 'system' },
  { label: 'Light', mode: 'light' },
  { label: 'Dark', mode: 'dark' },
];

/** Hue shift in degrees applied to the green brand band, and a saturation multiplier. */
export const PALETTES: Record<PaletteName, { label: string; hue: number; sat: number; swatch: string }> = {
  forest: { label: 'Forest', hue: 0, sat: 1, swatch: '#355440' },
  ocean: { label: 'Ocean', hue: 90, sat: 1.1, swatch: '#2f4f6b' },
  plum: { label: 'Plum', hue: 170, sat: 1, swatch: '#5a3c6b' },
  ember: { label: 'Ember', hue: -100, sat: 1.1, swatch: '#7a4a2a' },
  slate: { label: 'Slate', hue: 0, sat: 0.12, swatch: '#474d49' },
};

export function normalizeUiSettings(value: unknown): UiSettings {
  const v = (value && typeof value === 'object' ? value : {}) as Partial<UiSettings>;
  const textScale = TEXT_SIZES.some((t) => t.scale === v.textScale) ? (v.textScale as number) : DEFAULT_UI.textScale;
  const mode = MODES.some((m) => m.mode === v.mode) ? (v.mode as ThemeMode) : DEFAULT_UI.mode;
  const palette = v.palette && v.palette in PALETTES ? v.palette : DEFAULT_UI.palette;
  return { textScale, mode, palette };
}

export function prefersDark(): boolean {
  return typeof matchMedia === 'function' && matchMedia('(prefers-color-scheme: dark)').matches;
}

export function isDark(settings: UiSettings): boolean {
  return settings.mode === 'dark' || (settings.mode === 'system' && prefersDark());
}

// ---- colour maths ----

type Hsla = { h: number; s: number; l: number; a: number };

function parseHex(hex: string): Hsla | null {
  const m = /^#([0-9a-f]{6}|[0-9a-f]{8})$/i.exec(hex.trim());
  if (!m) return null;
  const n = m[1];
  const r = parseInt(n.slice(0, 2), 16) / 255;
  const g = parseInt(n.slice(2, 4), 16) / 255;
  const b = parseInt(n.slice(4, 6), 16) / 255;
  const a = n.length === 8 ? parseInt(n.slice(6, 8), 16) / 255 : 1;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const l = (max + min) / 2;
  let h = 0;
  let s = 0;
  if (max !== min) {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    if (max === r) h = (g - b) / d + (g < b ? 6 : 0);
    else if (max === g) h = (b - r) / d + 2;
    else h = (r - g) / d + 4;
    h *= 60;
  }
  return { h, s, l, a };
}

function toHex({ h, s, l, a }: Hsla): string {
  const f = (n: number) => {
    const k = (n + h / 30) % 12;
    const c = l - s * Math.min(l, 1 - l) * Math.max(-1, Math.min(k - 3, 9 - k, 1));
    return Math.round(c * 255).toString(16).padStart(2, '0');
  };
  const alpha = a < 1 ? Math.round(a * 255).toString(16).padStart(2, '0') : '';
  return `#${f(0)}${f(8)}${f(4)}${alpha}`;
}

/** The brand palette lives in the yellow-green to teal band; reds and ambers are status colours. */
const BRAND_HUE = { min: 60, max: 200 };

export function themedColor(hex: string, settings: UiSettings): string {
  const c = parseHex(hex);
  if (!c) return hex;
  const palette = PALETTES[settings.palette];
  let { h, s, l } = c;
  const isBrand = s < 0.02 || (h >= BRAND_HUE.min && h <= BRAND_HUE.max);
  if (isBrand) {
    h = (((h + palette.hue) % 360) + 360) % 360;
    s = Math.min(1, s * palette.sat);
  }
  if (isDark(settings)) {
    if (l >= 0.985) l = 0.15; // white cards become the lightest dark surface
    else if (l >= 0.85) { l = 0.05 + (1 - l) * 0.9; s *= 0.8; } // page, tints and borders
    else l = Math.min(0.92, 1 - l + 0.12); // text and mid tones
  }
  return toHex({ h, s, l, a: c.a });
}

/** Write `--ts` and one `--c-<hex>` variable per palette colour onto the root element. */
export function applyUiSettings(settings: UiSettings, hexes: readonly string[], root: HTMLElement = document.documentElement): void {
  root.style.setProperty('--ts', String(settings.textScale));
  root.style.colorScheme = isDark(settings) ? 'dark' : 'light';
  root.dataset.theme = isDark(settings) ? 'dark' : 'light';
  for (const hex of hexes) {
    root.style.setProperty(`--c-${hex.slice(1).toLowerCase()}`, themedColor(hex, settings));
  }
}

/** Re-apply when the OS theme flips and the mode is "system". Returns a disposer. */
export function watchSystemTheme(onChange: () => void): () => void {
  if (typeof matchMedia !== 'function') return () => undefined;
  const query = matchMedia('(prefers-color-scheme: dark)');
  query.addEventListener('change', onChange);
  return () => query.removeEventListener('change', onChange);
}
