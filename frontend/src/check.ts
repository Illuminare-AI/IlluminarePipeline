export type CheckInput = { image: File | null; caption: string; ocrText: string; isExample: boolean };
export type CheckResult = {
  check_id: string;
  analysis_mode: 'live' | 'fake' | 'replay' | 'unknown';
  claims: {
    claim: string;
    label: 'supported' | 'refuted' | 'missing_context' | 'not_enough_evidence';
    explanation: string;
    sources: { title: string; url: string; publisher: string; quote: string; rating: string | null }[];
  }[];
  origin: {
    status: 'credentials_present' | 'possible_ai_signal' | 'no_signal_found' | 'unavailable';
    note: string;
    credentials: { issuer: string; generator: string | null } | null;
    detector: { provider: string; score: number; threshold: number } | null;
  };
  persuasion: { tactic: string; phrase: string }[];
  from_memory: boolean;
  stages: Record<string, { state: 'ok' | 'skipped' | 'failed' | 'timeout'; detail: string | null }>;
  extraction: { ocr_text: string; image_description: string } | null;
};

export const exampleText = 'A new government rule requires everyone to register their home battery before Friday or face a $500 fine. Share before it is deleted!';
export const labels = {
  supported: 'Supported', refuted: 'Refuted', missing_context: 'Missing context',
  not_enough_evidence: 'Not enough evidence', credentials_present: 'Content Credentials present',
  possible_ai_signal: 'Possible AI signal', no_signal_found: 'No authenticity signal found',
  unavailable: 'Origin checks unavailable',
};
export const tactics: Record<string, { name: string; explanation: string }> = {
  urgency: { name: 'Urgency', explanation: 'A deadline or call to act can pressure you to share before checking.' },
  authority: { name: 'Authority', explanation: 'An appeal to authority can make a claim feel more credible.' },
  fear: { name: 'Fear', explanation: 'A threatened consequence can make a claim feel more compelling.' },
  promised_reward: { name: 'Promised reward', explanation: 'A promised benefit can encourage action before verification.' },
};

export function sourceUrl(value: string): string | undefined {
  try {
    const url = new URL(value);
    return ['http:', 'https:'].includes(url.protocol) ? url.href : undefined;
  } catch { return undefined; }
}

export async function checkScreenshot(input: CheckInput, signal: AbortSignal): Promise<CheckResult> {
  const body = new FormData();
  if (input.image) body.append('image', input.image);
  body.append('caption', input.caption);
  body.append('ocr_text', input.isExample ? exampleText : input.ocrText);
  const base = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '');
  let response: Response;
  try {
    response = await fetch(`${base}/check`, { method: 'POST', body, signal });
  } catch (error) {
    if (signal.aborted) throw error;
    throw new Error('Could not reach the analysis service. Check that the backend is running and try again.');
  }
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(typeof detail?.detail === 'string' ? detail.detail : `Analysis failed (${response.status}). Please try again.`);
  }
  const card: CheckResult = await response.json();
  if (!card.check_id || !Array.isArray(card.claims) || !card.origin || !card.stages || !Array.isArray(card.persuasion)) {
    throw new Error('The analysis service returned an unexpected response.');
  }
  return card;
}
