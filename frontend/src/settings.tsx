import { useEffect, useState } from 'react';
import { Settings } from 'lucide-react';
import { applyUiSettings, DEFAULT_UI, MODES, normalizeUiSettings, PALETTES, TEXT_SIZES, watchSystemTheme, type PaletteName, type UiSettings } from './theme';
import { PALETTE_HEXES } from './palette';

const STORAGE_KEY = 'luminate.ui';

function load(): UiSettings {
  try {
    return normalizeUiSettings(JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null'));
  } catch {
    return DEFAULT_UI;
  }
}

/** Applies the stored display settings on mount and whenever they change. */
export function useUiSettings(): [UiSettings, (next: UiSettings) => void] {
  const [ui, setUi] = useState<UiSettings>(load);
  useEffect(() => {
    applyUiSettings(ui, PALETTE_HEXES);
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(ui)); } catch { /* private mode */ }
    return watchSystemTheme(() => applyUiSettings(ui, PALETTE_HEXES));
  }, [ui]);
  return [ui, setUi];
}

export function SettingsMenu({ ui, onChange }: { ui: UiSettings; onChange: (next: UiSettings) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="settings-wrap">
      <button className="icon-button" aria-label="Display settings" aria-expanded={open} onClick={() => setOpen(!open)}><Settings size={18} /></button>
      {open && (
        <div className="settings-pop" role="dialog" aria-label="Display settings">
          <SettingGroup label="Text size">
            {TEXT_SIZES.map((t) => <Seg key={t.label} active={ui.textScale === t.scale} onClick={() => onChange({ ...ui, textScale: t.scale })}>{t.label}</Seg>)}
          </SettingGroup>
          <SettingGroup label="Theme">
            {MODES.map((m) => <Seg key={m.mode} active={ui.mode === m.mode} onClick={() => onChange({ ...ui, mode: m.mode })}>{m.label}</Seg>)}
          </SettingGroup>
          <SettingGroup label="Colours">
            {(Object.keys(PALETTES) as PaletteName[]).map((name) => (
              <button key={name} className={`swatch ${ui.palette === name ? 'active' : ''}`} title={PALETTES[name].label} aria-label={PALETTES[name].label} aria-pressed={ui.palette === name} style={{ background: PALETTES[name].swatch }} onClick={() => onChange({ ...ui, palette: name })} />
            ))}
          </SettingGroup>
          <button className="text-button" onClick={() => onChange(DEFAULT_UI)}>Reset to defaults</button>
        </div>
      )}
    </div>
  );
}

function SettingGroup({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className="setting-group"><span className="setting-label">{label}</span><div className="seg-row">{children}</div></div>;
}

function Seg({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return <button className={`seg ${active ? 'active' : ''}`} aria-pressed={active} onClick={onClick}>{children}</button>;
}
