import { useEffect, useRef, useState } from 'react';
import { ArrowDown, ArrowRight, Check, ChevronDown, Clipboard, FileImage, Fingerprint, ImagePlus, Info, LoaderCircle, ScanLine, ShieldCheck, Sparkles, Upload, X } from 'lucide-react';
import { checkScreenshot, labels, sourceUrl, tactics, type CheckResult } from './check';

const maxSize = 10 * 1024 * 1024;

export default function App() {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState('');
  const [isExample, setIsExample] = useState(false);
  const [caption, setCaption] = useState('');
  const [ocrText, setOcrText] = useState('');
  const [error, setError] = useState('');
  const [dragging, setDragging] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [result, setResult] = useState<CheckResult | null>(null);
  const [howOpen, setHowOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const controller = useRef<AbortController | null>(null);
  const resultRef = useRef<HTMLDivElement>(null);

  useEffect(() => () => controller.current?.abort(), []);
  useEffect(() => {
    if (!file) return;
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);
  useEffect(() => {
    if (result) resultRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, [result]);

  function acceptFile(next: File) {
    if (processing) return;
    if (!['image/png', 'image/jpeg', 'image/webp'].includes(next.type)) {
      setError('Please choose a PNG, JPG, or WebP image.');
      return;
    }
    if (next.size > maxSize) { setError('This image is too large. Please choose one under 10 MB.'); return; }
    setFile(next);
    setOcrText('');
    setIsExample(false);
    setResult(null);
    setError('');
  }

  useEffect(() => {
    function onPaste(event: ClipboardEvent) {
      const image = Array.from(event.clipboardData?.items || []).find(item => item.type.startsWith('image/'))?.getAsFile();
      if (image && !processing) { event.preventDefault(); acceptFile(image); }
    }
    window.addEventListener('paste', onPaste);
    return () => window.removeEventListener('paste', onPaste);
  }, [processing]);

  function useExample() {
    setFile(null);
    setPreview('/example-post.svg');
    setIsExample(true);
    setCaption('');
    setOcrText('');
    setResult(null);
    setError('');
  }

  function reset() {
    controller.current?.abort();
    setProcessing(false);
    setFile(null);
    setPreview('');
    setIsExample(false);
    setCaption('');
    setOcrText('');
    setResult(null);
    setError('');
    if (inputRef.current) inputRef.current.value = '';
  }

  async function analyze() {
    if (!preview || processing) return;
    const request = new AbortController();
    controller.current = request;
    setProcessing(true);
    setResult(null);
    setError('');
    try {
      const response = await checkScreenshot({ image: file, caption, ocrText, isExample }, request.signal);
      if (!request.signal.aborted) setResult(response);
    } catch (failure) {
      if (!request.signal.aborted) setError(failure instanceof Error ? failure.message : 'Something went wrong. Please try again.');
    } finally {
      if (controller.current === request) setProcessing(false);
    }
  }

  return (
    <div className="app-shell">
      <header className="site-header">
        <a className="brand" href="#" aria-label="Signal home"><span className="brand-mark"><ScanLine size={22} strokeWidth={1.8} /></span>signal<span className="brand-dot">.</span></a>
        <div className="header-right"><span className="demo-pill"><span />Screenshot analysis</span><button className="text-button how-button" onClick={() => setHowOpen(!howOpen)} aria-expanded={howOpen}>How it works <ChevronDown size={14} className={howOpen ? 'rotated' : ''} /></button></div>
      </header>

      <main>
        {howOpen && <section className="how-panel" aria-label="How Signal works"><strong>A screenshot. Three perspectives.</strong><p>Your image and context are sent to the analysis service to review origin signals, factual claims, and persuasion techniques. The local image service reads text and describes what is visible in the uploaded image. You can also supply the text yourself. Results identify when fact-checks use offline rules.</p><button className="text-button" onClick={() => setHowOpen(false)}>Got it <Check size={15} /></button></section>}
        <section className="intro">
          <div className="eyebrow"><span className="little-line" /> PAUSE. CHECK. THEN SHARE.</div>
          <h1>A little context.<br />A clearer picture<span>.</span></h1>
          <p>Not sure about a post? Drop in a screenshot.<br className="desktop-break" /> Explore where it came from, what it claims, and how it persuades.</p>
        </section>

        <div className="workspace">
          <section className="upload-card" aria-labelledby="upload-title">
            <div className="card-heading"><div><span className="step-label">01 / START HERE</span><h2 id="upload-title">What caught your eye?</h2></div><ImagePlus size={23} className="muted-icon" /></div>
            <input ref={inputRef} className="visually-hidden" type="file" accept="image/png,image/jpeg,image/webp" aria-label="Choose screenshot" disabled={processing} onChange={event => { const chosen = event.target.files?.[0]; if (chosen) acceptFile(chosen); event.target.value = ''; }} />
            {!preview ? <div className={`drop-zone ${dragging ? 'dragging' : ''}`} onDragOver={event => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={event => { event.preventDefault(); setDragging(false); const dropped = event.dataTransfer.files[0]; if (dropped) acceptFile(dropped); }}>
              <div className="upload-icon"><Upload size={25} strokeWidth={1.5} /></div>
              <h3>Drop your screenshot here</h3><p>or choose an image from your device</p>
              <button className="choose-button" onClick={() => inputRef.current?.click()}><FileImage size={16} /> Choose image</button>
              <span className="file-hint">PNG, JPG, WebP · up to 10 MB</span>
              <div className="paste-hint"><Clipboard size={13} /> You can also paste a screenshot</div>
            </div> : <div className="preview-zone"><img src={preview} alt={isExample ? 'Fictional social post claiming a home battery registration deadline and fine' : 'Your uploaded screenshot'} onError={() => { setError('This image could not be opened. Please choose a different image.'); setPreview(''); setFile(null); setIsExample(false); }} /><div className="preview-bar"><span><FileImage size={15} />{isExample ? 'Example screenshot' : file?.name}</span><button className="icon-button" aria-label="Remove screenshot" disabled={processing} onClick={reset}><X size={17} /></button></div></div>}
            {error && <p className="error-message" role="alert">{error}</p>}
            <label className="caption-label" htmlFor="caption">Add a little context <span>optional</span></label>
            <textarea id="caption" placeholder="A caption, a claim, or where you saw this…" value={caption} disabled={processing} maxLength={2000} onChange={event => { setCaption(event.target.value); setResult(null); }} />
            {!isExample && <><label className="caption-label" htmlFor="ocr-text">Text visible in the image <span>optional override</span></label><textarea id="ocr-text" placeholder="Paste the screenshot’s text if automatic extraction is unavailable…" value={ocrText} disabled={processing} maxLength={16000} onChange={event => { setOcrText(event.target.value); setResult(null); }} /></>}
            <button className="analyze-button" disabled={!preview || processing} onClick={analyze}>{processing ? <><LoaderCircle size={18} className="spin" /> Taking a closer look…</> : <>Check this screenshot <ArrowRight size={18} /></>}</button>
            <p className="privacy-note"><ShieldCheck size={13} />Your image and text are sent to the analysis service. Checks may be stored.</p>
            <div className="example-row"><span>Just looking around?</span><button className="text-button" disabled={processing} onClick={useExample}>Try an example <ArrowRight size={14} /></button></div>
          </section>

          <aside className="context-column">
            <div className="section-caption">LOOK BEYOND THE POST <ArrowDown size={14} /></div>
            <div className="perspective"><div className="perspective-icon origin-icon"><Fingerprint size={24} strokeWidth={1.5} /></div><div><span className="perspective-number">01</span><h3>Where did it come from?</h3><p>Trace the origin and look for signals about the image’s authenticity.</p></div></div>
            <div className="perspective"><div className="perspective-icon claim-icon"><ScanLine size={24} strokeWidth={1.5} /></div><div><span className="perspective-number">02</span><h3>What is it claiming?</h3><p>Separate checkable facts from opinions, and see what the evidence says.</p></div></div>
            <div className="perspective"><div className="perspective-icon persuasion-icon"><Sparkles size={24} strokeWidth={1.5} /></div><div><span className="perspective-number">03</span><h3>How is it persuading you?</h3><p>Spot language that uses urgency, authority, fear, or a promised reward.</p></div></div>
            <div className="context-note"><span className="quote-mark">“</span><p>Strong feelings are a good reason<br />to take a second look.</p><span className="note-rule" /></div>
            <div className="demo-note"><Info size={16} /><p><strong>Evidence has limits.</strong> Results depend on configured services. Missing signals do not establish authenticity.</p></div>
          </aside>
        </div>

        {processing && <section className="processing-card" role="status" aria-live="polite"><div className="processing-top"><LoaderCircle className="spin" size={20} /><div><h3>Reading and describing your screenshot</h3><p>The local image model may take a few minutes, especially on its first image.</p></div><button className="text-button" onClick={() => { controller.current?.abort(); setProcessing(false); }}>Cancel</button></div></section>}

        {result && <section className="results-section" ref={resultRef} aria-labelledby="results-title">
          <div className="results-heading"><div><span className="step-label">02 / THE BIGGER PICTURE</span><h2 id="results-title">Here’s a closer look.</h2></div><button className="text-button" onClick={() => { reset(); inputRef.current?.click(); }}>Check another <ArrowRight size={16} /></button></div>
          <div className="result-disclaimer"><Info size={16} /><span><strong>{result.analysis_mode === 'fake' ? 'Offline fact-check mode.' : result.analysis_mode === 'replay' ? 'Replayed result.' : result.analysis_mode === 'unknown' ? 'Stored result; model configuration unknown.' : 'Backend analysis.'}</strong> {result.analysis_mode === 'fake' ? 'Claims are extracted by simple text rules; this is not a live fact-check.' : result.analysis_mode === 'replay' ? 'Saved output; this is not a new fact-check. Confirm the original model configuration.' : 'Review the evidence and service limitations before sharing.'} {isExample && 'The input is a fictional example.'} {result.from_memory && 'This check reused stored evidence.'}</span></div>
          {Object.entries(result.stages).filter(([name, status]) => status.state === 'failed' || status.state === 'timeout' || (name === 'ocr' && status.detail === 'OCR service not configured')).map(([name, status]) => <p className="error-message" key={name}>{name === 'ocr' ? 'Image text extraction' : name.replaceAll('_', ' ')}: {status.state === 'skipped' ? 'not configured. Supply the image text above to check its wording.' : 'unavailable for this check. Results may be incomplete.'}</p>)}
          {result.image_context?.vision_status === 'ok' && result.image_context.observations && <article className="result-card image-description"><div className="result-title"><FileImage size={20} /><h3>What’s in the image?</h3><span>Local model</span></div><p>{result.image_context.observations.description}</p>{result.image_context.observations.objects.length > 0 && <p><strong>Visible objects:</strong> {result.image_context.observations.objects.join(', ')}</p>}{result.image_context.observations.uncertainties.length > 0 && <p><strong>Uncertainties:</strong> {result.image_context.observations.uncertainties.join(' ')}</p>}<p className="small-note">Described locally by {result.image_context.model}. Observations can be incorrect and do not verify the claims.</p></article>}
          {file && result.stages.vision?.state === 'skipped' && <p className="error-message">Image description is disabled or the image service is not configured.</p>}
          <div className="result-grid">
            <article className="result-card"><div className="result-title"><Fingerprint size={20} /><h3>Origin</h3><span>01</span></div><h4>{labels[result.origin.status]}</h4><p>{result.origin.note}</p><div className="signal-row"><span>Content Credentials</span><span>{result.origin.credentials ? result.origin.credentials.issuer || 'Present; issuer unknown' : 'No credentials returned'}</span></div><div className="signal-row"><span>AI detector</span><span>{result.origin.detector ? `${result.origin.detector.provider}: ${result.origin.detector.score.toFixed(2)} (threshold ${result.origin.detector.threshold.toFixed(2)})` : 'Unavailable'}</span></div><div className="signal-row"><span>Reverse image search</span><span>{result.origin.matches?.length ? result.origin.matches.map((m, i) => <span key={i}>{i > 0 && ', '}{sourceUrl(m.url) ? <a href={sourceUrl(m.url)} target="_blank" rel="noopener noreferrer">{m.title || m.domain}</a> : m.domain}{m.kind === 'partial' ? ' (partial)' : ''}</span>) : 'No matches on reputable sources'}</span></div><p className="small-note">Authenticity signals add context; they do not establish whether a claim is true.</p></article>
            <article className="result-card claim-result"><div className="result-title"><ScanLine size={20} /><h3>Claims</h3><span>02</span></div>{result.claims.length === 0 && <p>{result.stages.extract?.state === 'ok' ? 'No checkable claims were extracted from the supplied input.' : 'Claim extraction did not complete. Try again or supply the image text.'}</p>}{result.claims.map((claim, index) => <div className="claim-entry" key={index}><span className="verdict-badge"><Info size={13} />{labels[claim.label]}</span><h4>{claim.claim}</h4><p>{claim.explanation}</p><div className="sources"><span className="step-label">EVIDENCE</span>{claim.sources.length === 0 && <p>No sources returned for this claim.</p>}{claim.sources.map((source, sourceIndex) => <div className="source-item" key={sourceIndex}><span className="source-dot" /><div><strong>{sourceUrl(source.url) ? <a href={sourceUrl(source.url)} target="_blank" rel="noopener noreferrer">{source.title || source.publisher || source.url}</a> : source.title || source.publisher || 'Source'}</strong><p>{source.publisher}{source.rating && ` · ${source.rating}`}</p>{source.quote && <blockquote>{source.quote}</blockquote>}</div></div>)}</div></div>)}</article>
            <article className="result-card"><div className="result-title"><Sparkles size={20} /><h3>Persuasion</h3><span>03</span></div><p className="persuasion-intro">Notice the wording. A persuasive technique is a cue to pause, not proof that a post is false.</p>{result.persuasion.length === 0 && <p>No persuasion tags returned.</p>}{result.persuasion.map((tag, index) => <div className="persuasion-tag" key={index}><span className="tag-name">{tactics[tag.tactic]?.name || tag.tactic}</span><blockquote>{tag.phrase}</blockquote><p>{tactics[tag.tactic]?.explanation}</p></div>)}</article>
          </div>
        </section>}
      </main>
      <footer><span className="footer-brand">signal.</span><span>A little curiosity goes a long way.</span><span className="footer-label">A SCREENSHOT-FIRST VERIFICATION DEMO</span></footer>
    </div>
  );
}
