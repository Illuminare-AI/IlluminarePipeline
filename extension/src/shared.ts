// Types and helpers shared by the service worker and the side panel.
import type { CheckResult } from '../../frontend/src/check';

export const DEFAULT_BACKEND = 'http://127.0.0.1:8000';

export type JobKind = 'text' | 'image' | 'region' | 'post';

export type JobInput = {
  kind: JobKind;
  caption: string;
  sourceUrl: string;
  /** Small data-URL thumbnail of the captured image, for the panel only. */
  preview?: string;
  /** False when the client already has the post text: the backend skips the vision description. */
  describeImage?: boolean;
  /** The post's own timestamp, shown as context; never sent as a claim. */
  timestamp?: string;
};

export type Job = {
  id: string;
  status: 'running' | 'done' | 'error';
  startedAt: number;
  finishedAt?: number;
  input: JobInput;
  result?: CheckResult;
  error?: string;
};

/** Messages from the side panel to the service worker. */
export type PanelMessage =
  | { type: 'check-text'; caption: string }
  | { type: 'cancel' };

/** Messages from the injected region selector to the service worker. */
export type ContentMessage =
  | { type: 'region-selected'; rect: Rect; dpr: number }
  | { type: 'region-cancelled' }
  | {
      type: 'element-selected';
      text: string;
      permalink: string;
      timestamp: string;
      imageUrl: string;
      imageRect: Rect | null;
      dpr: number;
    };

export type Rect = { x: number; y: number; width: number; height: number };

export async function getBackendUrl(): Promise<string> {
  const stored = await chrome.storage.sync.get('backendUrl');
  const url = typeof stored.backendUrl === 'string' ? stored.backendUrl.trim() : '';
  return (url || DEFAULT_BACKEND).replace(/\/+$/, '');
}

export async function getJob(): Promise<Job | null> {
  const stored = await chrome.storage.session.get('job');
  return (stored.job as Job | undefined) ?? null;
}

export function setJob(job: Job | null): Promise<void> {
  return job ? chrome.storage.session.set({ job }) : chrome.storage.session.remove('job');
}
