// Tests for the Result tab (ADR 0017 U3): the artifact bundle sections,
// the empty state, the bundle error with Retry, and the on-demand diff.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { api } from '../../../../shared/api';
import type { ArtifactBundle, TaskResult } from '../../../../shared/types';
import { ResultTab } from './ResultTab';

afterEach(cleanup);
afterEach(() => vi.restoreAllMocks());

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const RESULT: TaskResult = {
  schema: 1,
  status: 'done',
  summary: 'all good',
  commits: [],
  tests: null,
  open_questions: [],
  next_step: '',
  blocked_reason: '',
} as TaskResult;

function fullBundle(): ArtifactBundle {
  return {
    result: {
      name: 'RESULT.json',
      content: JSON.stringify({ status: 'done', summary: 'did it', next_steps: ['ship it'] }),
      mtime: 0,
      truncated: false,
    },
    state: { name: 'STATE.md', content: '# progress', mtime: 0, truncated: false },
    outputs: [{ name: 'report.pdf', path: '/tmp/w1/outputs/report.pdf', size: 2048 }],
    docs: [
      { name: 'NOTES.md', content: '# notes', mtime: 0, truncated: false },
      { name: 'data.json', content: '{"a": 1}', mtime: 0, truncated: true },
    ],
    files: [{ path: 'src/a.ts', read: 2, edit: 1, write: 0 }],
    worktree: { repo_root: '/r', base_ref: 'main', worktree_path: '/w/w1', exists: true },
  } as ArtifactBundle;
}

function emptyBundle(): ArtifactBundle {
  return { result: null, state: null, outputs: [], docs: [], files: [], worktree: null };
}

describe('ResultTab', () => {
  it('renders all six section headings, doc names and outputs with editor links', async () => {
    vi.spyOn(api, 'getArtifactBundle').mockResolvedValue(fullBundle());
    render(<ResultTab taskId="w1" status="done" result={RESULT} />, { wrapper });

    for (const name of ['Result', 'Outputs', 'Documents', 'State', 'Files touched', 'Diff']) {
      expect(await screen.findByRole('heading', { name })).toBeInTheDocument();
    }
    expect(screen.getByText('NOTES.md')).toBeInTheDocument();
    expect(screen.getByText('data.json')).toBeInTheDocument();
    expect(screen.getByText('(truncated)')).toBeInTheDocument();
    expect(screen.getByText('report.pdf')).toBeInTheDocument();
    expect(screen.getByText('2.0 KiB')).toBeInTheDocument();
    const editorLink = screen.getByRole('link', { name: 'Open in editor' });
    expect(editorLink.getAttribute('href')).toBe('vscode://file//tmp/w1/outputs/report.pdf');
    // Result content fields and state digest.
    expect(screen.getByText('did it')).toBeInTheDocument();
    expect(screen.getByText('branch vs main in /w/w1')).toBeInTheDocument();
    // Files table.
    expect(screen.getByText('src/a.ts')).toBeInTheDocument();
    // Header shows the update time.
    expect(screen.getByText(/^updated \d{2}:\d{2}:\d{2}$/)).toBeInTheDocument();
  });

  it('renders "Nothing produced." for an empty bundle on a finished task', async () => {
    vi.spyOn(api, 'getArtifactBundle').mockResolvedValue(emptyBundle());
    render(<ResultTab taskId="w1" status="done" result={null} />, { wrapper });

    expect(await screen.findByText('Nothing produced.')).toBeInTheDocument();
  });

  it('renders "Nothing produced yet." for an empty bundle on a running task', async () => {
    vi.spyOn(api, 'getArtifactBundle').mockResolvedValue(emptyBundle());
    render(<ResultTab taskId="w1" status="in_progress" result={null} />, { wrapper });

    expect(await screen.findByText('Nothing produced yet.')).toBeInTheDocument();
  });

  it('renders the error with Retry, and Retry refetches', async () => {
    const bundleSpy = vi.spyOn(api, 'getArtifactBundle').mockRejectedValue(new Error('boom'));
    render(<ResultTab taskId="w1" status="done" result={null} />, { wrapper });

    expect(await screen.findByText('Could not load result: boom', undefined, { timeout: 5000 })).toBeInTheDocument();
    expect(screen.queryByText('Nothing produced.')).not.toBeInTheDocument();
    const callsBefore = bundleSpy.mock.calls.length;

    bundleSpy.mockResolvedValue(fullBundle());
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByRole('heading', { name: 'Result' })).toBeInTheDocument();
    expect(bundleSpy.mock.calls.length).toBeGreaterThan(callsBefore);
  });

  it('"Load diff" fetches once and renders the note when the diff is empty', async () => {
    vi.spyOn(api, 'getArtifactBundle').mockResolvedValue(fullBundle());
    const diffSpy = vi
      .spyOn(api, 'getDiff')
      .mockResolvedValue({ diff: '', note: 'no working directory' });
    render(<ResultTab taskId="w1" status="done" result={null} />, { wrapper });

    await screen.findByRole('heading', { name: 'Diff' });
    expect(diffSpy).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Load diff' }));
    expect(await screen.findByText('no working directory')).toBeInTheDocument();
    expect(diffSpy).toHaveBeenCalledTimes(1);
  });

  it('disables "Load diff" with "worktree removed" when the worktree is gone', async () => {
    const bundle = fullBundle();
    bundle.worktree = { repo_root: '/r', base_ref: 'main', worktree_path: '/w/gone', exists: false };
    vi.spyOn(api, 'getArtifactBundle').mockResolvedValue(bundle);
    const diffSpy = vi.spyOn(api, 'getDiff').mockResolvedValue({ diff: 'x', note: '' });
    render(<ResultTab taskId="w1" status="done" result={null} />, { wrapper });

    expect(await screen.findByText('worktree removed')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Load diff' })).toBeDisabled();
    expect(diffSpy).not.toHaveBeenCalled();
  });
});
