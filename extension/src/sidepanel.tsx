// Side panel: shows the current check, its result card, and the backend setting.
import { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Fingerprint, Info, LoaderCircle, ScanLine, Settings, Sparkles, X } from 'lucide-react';
import { labels, sourceUrl, tactics, type CheckResult } from '../../frontend/src/check';
import { applyUiSettings, DEFAULT_UI, MODES, normalizeUiSettings, PALETTES, TEXT_SIZES, watchSystemTheme, type PaletteName, type UiSettings } from '../../frontend/src/theme';
import { PALETTE_HEXES } from './palette.ts';
import { DEFAULT_BACKEND, getBackendUrl, getJob, type Job, type PanelMessage } from './shared.ts';

function send(message: PanelMessage) {
  void chrome.runtime.sendMessage(message);
}

function useJob(): Job | null {
  const [job, setJobState] = useState<Job | null>(null);
  useEffect(() => {
    void getJob().then(setJobState);
    const onChange = (changes: Record<string, chrome.storage.StorageChange>, area: string) => {
      if (area === 'session' && 'job' in changes) setJobState((changes.job.newValue as Job | undefined) ?? null);
    };
    chrome.storage.onChanged.addListener(onChange);
    return () => chrome.storage.onChanged.removeListener(onChange);
  }, []);
  return job;
}

type Health = { state: 'checking' | 'online' | 'offline'; mode?: string };

function useHealth(backend: string): Health {
  const [health, setHealth] = useState<Health>({ state: 'checking' });
  useEffect(() => {
    let cancelled = false;
    setHealth({ state: 'checking' });
    fetch(`${backend}/health`)
      .then((r) => r.json())
      .then((data: { llm_backend?: string }) => !cancelled && setHealth({ state: 'online', mode: data.llm_backend }))
      .catch(() => !cancelled && setHealth({ state: 'offline' }));
    return () => { cancelled = true; };
  }, [backend]);
  return health;
}

/** Display settings live in chrome.storage.sync so they follow the profile. */
function useUiSettings(): [UiSettings, (next: UiSettings) => void] {
  const [ui, setUiState] = useState<UiSettings>(DEFAULT_UI);
  useEffect(() => {
    void chrome.storage.sync.get('ui').then((stored) => setUiState(normalizeUiSettings(stored.ui)));
  }, []);
  useEffect(() => {
    applyUiSettings(ui, PALETTE_HEXES);
    return watchSystemTheme(() => applyUiSettings(ui, PALETTE_HEXES));
  }, [ui]);
  const setUi = (next: UiSettings) => {
    setUiState(next);
    void chrome.storage.sync.set({ ui: next });
  };
  return [ui, setUi];
}

function useElapsed(job: Job | null): number {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (job?.status !== 'running') return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [job?.status, job?.id]);
  if (!job) return 0;
  return Math.round(((job.finishedAt ?? now) - job.startedAt) / 1000);
}

function App() {
  const job = useJob();
  const [backend, setBackend] = useState(DEFAULT_BACKEND);
  const [showSettings, setShowSettings] = useState(false);
  const [caption, setCaption] = useState('');
  const [ui, setUi] = useUiSettings();
  const health = useHealth(backend);
  const elapsed = useElapsed(job);

  useEffect(() => { void getBackendUrl().then(setBackend); }, []);

  const running = job?.status === 'running';

  return (
    <div className="app">
      <header>
        <h1><Sparkles size={16} /> Signal Check</h1>
        <div className="row">
          <span className={`pill ${health.state === 'online' ? 'on' : health.state === 'offline' ? 'off' : ''}`}>
            {health.state === 'checking' ? 'Checking backend' : health.state === 'online' ? `Backend online${health.mode === 'fake' ? ' (offline rules)' : ''}` : 'Backend offline'}
          </span>
          <button className="icon" title="Settings" onClick={() => setShowSettings((v) => !v)}><Settings size={15} /></button>
        </div>
      </header>

      {showSettings && <SettingsCard backend={backend} ui={ui} onUi={setUi} onSaved={(url) => { setBackend(url); setShowSettings(false); }} />}

      <section className="card">
        <h2>Check text</h2>
        <textarea rows={3} placeholder="Paste a claim or caption" value={caption} onChange={(e) => setCaption(e.target.value)} />
        <div className="row">
          <button className="primary" disabled={running || !caption.trim()} onClick={() => send({ type: 'check-text', caption })}>Check text</button>
          <span className="muted">Or right-click any page: pick a post, select text, an image, or drag a region.</span>
        </div>
      </section>

      {!job && (
        <section className="card">
          <h2>How to use</h2>
          <ol className="tips">
            <li>Right-click a post and choose <b>Check this post with Signal</b>, then hover and click the post. Its text is read from the page, so no OCR or image description is needed.</li>
            <li>Highlight text on a page, right-click, choose <b>Check selected text with Signal</b>.</li>
            <li>Right-click an image and choose <b>Check this image with Signal</b>.</li>
            <li>Right-click anywhere and choose <b>Check a region of this page</b>, then drag a box around the post.</li>
          </ol>
          <p className="muted">Checks run on your local backend and can take a minute or two.</p>
        </section>
      )}

      {job && <JobCard job={job} elapsed={elapsed} />}
      {job?.status === 'done' && job.result && <ResultCards result={job.result} />}
    </div>
  );
}

function JobCard({ job, elapsed }: { job: Job; elapsed: number }) {
  const kind = { text: 'Selected text', image: 'Image', region: 'Page region', post: 'Post' }[job.input.kind];
  return (
    <section className="card">
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <h2>
          {job.status === 'running' && <LoaderCircle size={14} className="spin" />}
          {job.status === 'running' ? `Checking ${kind.toLowerCase()}` : job.status === 'done' ? `Checked ${kind.toLowerCase()}` : 'Check failed'}
        </h2>
        <span className="muted">{elapsed}s</span>
        {job.status === 'running' && <button className="icon" title="Cancel" onClick={() => send({ type: 'cancel' })}><X size={14} /></button>}
      </div>
      {job.input.preview && <img className="preview" src={job.input.preview} alt="Captured image" />}
      {job.input.caption && <p className="excerpt">{job.input.caption}</p>}
      {job.input.timestamp && <p className="muted">Posted {new Date(job.input.timestamp).toLocaleString()}</p>}
      {job.input.sourceUrl && sourceUrl(job.input.sourceUrl) && (
        <p className="muted">From <a href={job.input.sourceUrl} target="_blank" rel="noopener noreferrer">{new URL(job.input.sourceUrl).hostname}</a></p>
      )}
      {job.status === 'error' && <p className="notice error">{job.error}</p>}
    </section>
  );
}

function ResultCards({ result }: { result: CheckResult }) {
  const problems = Object.entries(result.stages).filter(([, s]) => s.state === 'failed' || s.state === 'timeout');
  const description = result.image_context?.observations?.description || result.extraction?.image_description;
  return (
    <>
      {result.summary && (
        <section className={`verdict verdict-${result.summary.verdict}`} role="status">
          <span className="kicker">AT A GLANCE</span>
          <h3>{result.summary.headline}</h3>
          <p>{result.summary.detail}</p>
          {result.summary.flags.length > 0 && (
            <div className="verdict-flags">{result.summary.flags.map((flag) => <span className="badge" key={flag}>{flag}</span>)}</div>
          )}
        </section>
      )}
      {result.analysis_mode === 'fake' && <p className="notice warn">The backend is using offline rules, not a live model. Verdicts are placeholders.</p>}
      {problems.map(([name]) => (
        <p className="notice warn" key={name}>{name.replaceAll('_', ' ')}: unavailable for this check. Results may be incomplete.</p>
      ))}

      <section className="card">
        <h2><ScanLine size={14} /> Claims</h2>
        {result.claims.length === 0 && <p className="muted">No checkable claims were found.</p>}
        {result.claims.map((claim, i) => (
          <div className="claim" key={i}>
            <span className={`badge ${claim.label}`}><Info size={11} />{labels[claim.label]}</span>
            <h3>{claim.claim}</h3>
            {claim.explanation && <p style={{ margin: 0 }}>{claim.explanation}</p>}
            {claim.sources.length === 0 && <p className="muted" style={{ margin: 0 }}>No sources returned for this claim.</p>}
            {claim.sources.map((source, j) => {
              const href = sourceUrl(source.url);
              return (
                <div className="source" key={j}>
                  <strong>{href ? <a href={href} target="_blank" rel="noopener noreferrer">{source.title || source.publisher || source.url}</a> : source.title || source.publisher || 'Source'}</strong>
                  <span className="muted">{source.publisher}{source.rating ? ` · ${source.rating}` : ''}</span>
                  {source.quote && <blockquote>{source.quote}</blockquote>}
                </div>
              );
            })}
          </div>
        ))}
      </section>

      <section className="card">
        <h2><Fingerprint size={14} /> Origin</h2>
        <h3>{labels[result.origin.status]}</h3>
        <p className="muted" style={{ margin: 0 }}>{result.origin.note}</p>
        {result.origin.detector && (
          <p className="muted" style={{ margin: 0 }}>AI detector: {result.origin.detector.provider} {result.origin.detector.score.toFixed(2)} (threshold {result.origin.detector.threshold.toFixed(2)})</p>
        )}
        {result.origin.matches?.map((m, i) => {
          const href = sourceUrl(m.url);
          return (
            <div className="source" key={i}>
              <strong>{href ? <a href={href} target="_blank" rel="noopener noreferrer">{m.title || m.domain}</a> : m.domain}</strong>
              <span className="muted">{m.domain}{m.kind === 'partial' ? ' · partial match' : ''}</span>
            </div>
          );
        })}
      </section>

      <section className="card">
        <h2><Sparkles size={14} /> Persuasion</h2>
        {result.persuasion.length === 0 && <p className="muted" style={{ margin: 0 }}>No persuasion tags returned.</p>}
        {result.persuasion.map((tag, i) => (
          <div key={i}>
            <strong>{tactics[tag.tactic]?.name ?? tag.tactic}</strong>: <span className="muted">“{tag.phrase}”</span>
            {tactics[tag.tactic] && <p className="muted" style={{ margin: '2px 0 0' }}>{tactics[tag.tactic].explanation}</p>}
          </div>
        ))}
      </section>

      {description && (
        <section className="card">
          <h2>What's in the image?</h2>
          <p style={{ margin: 0 }}>{description}</p>
          {result.image_context?.observations?.uncertainties?.length ? (
            <p className="muted" style={{ margin: 0 }}>Uncertain: {result.image_context.observations.uncertainties.join('; ')}</p>
          ) : null}
        </section>
      )}
    </>
  );
}

function SettingsCard({ backend, ui, onUi, onSaved }: { backend: string; ui: UiSettings; onUi: (next: UiSettings) => void; onSaved: (url: string) => void }) {
  const [value, setValue] = useState(backend);
  const [message, setMessage] = useState('');

  async function save() {
    const url = value.trim().replace(/\/+$/, '') || DEFAULT_BACKEND;
    let origin: string;
    try {
      origin = new URL(url).origin;
    } catch {
      setMessage('Enter a full URL such as http://127.0.0.1:8000');
      return;
    }
    const isDefault = /^http:\/\/(127\.0\.0\.1|localhost):8000$/.test(origin);
    if (!isDefault) {
      const granted = await chrome.permissions.request({ origins: [`${origin}/*`] });
      if (!granted) {
        setMessage('Permission for that host was not granted.');
        return;
      }
    }
    await chrome.storage.sync.set({ backendUrl: url });
    onSaved(url);
  }

  return (
    <section className="card settings">
      <h2>Settings</h2>
      <label>
        Backend URL
        <input type="url" value={value} onChange={(e) => setValue(e.target.value)} placeholder={DEFAULT_BACKEND} />
      </label>
      <div className="row">
        <button className="primary" onClick={() => void save()}>Save</button>
        <button onClick={() => setValue(DEFAULT_BACKEND)}>Reset</button>
        {message && <span className="notice error">{message}</span>}
      </div>
      <p className="muted" style={{ margin: 0 }}>A non-local URL asks for permission to contact that host.</p>
      <label>Text size</label>
      <div className="seg-row">
        {TEXT_SIZES.map((t) => <button key={t.label} className={`seg ${ui.textScale === t.scale ? 'active' : ''}`} aria-pressed={ui.textScale === t.scale} onClick={() => onUi({ ...ui, textScale: t.scale })}>{t.label}</button>)}
      </div>
      <label>Theme</label>
      <div className="seg-row">
        {MODES.map((m) => <button key={m.mode} className={`seg ${ui.mode === m.mode ? 'active' : ''}`} aria-pressed={ui.mode === m.mode} onClick={() => onUi({ ...ui, mode: m.mode })}>{m.label}</button>)}
      </div>
      <label>Colours</label>
      <div className="seg-row">
        {(Object.keys(PALETTES) as PaletteName[]).map((name) => (
          <button key={name} className={`swatch ${ui.palette === name ? 'active' : ''}`} title={PALETTES[name].label} aria-label={PALETTES[name].label} aria-pressed={ui.palette === name} style={{ background: PALETTES[name].swatch }} onClick={() => onUi({ ...ui, palette: name })} />
        ))}
      </div>
    </section>
  );
}

createRoot(document.getElementById('root')!).render(<App />);
