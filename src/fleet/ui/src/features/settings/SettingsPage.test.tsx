// Tests for the settings page (ADR 0009): every RuntimeConfig field
// grouped in exactly one section, coder/model dropdowns from the coders
// fixture, restart badges, the constants table, per-section save posting
// only changed fields, PUT errors next to the field, and the legacy
// /config redirect.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { ToastProvider } from '../../shared/contexts/ToastContext';
import { api } from '../../shared/api';
import type { CoderInfo, ConfigConstant, RuntimeConfig } from '../../shared/types';
import { ConfigRedirect } from '../../app/App';
import { FIELD_DEFS, SECTIONS, fieldsFor } from './settingsSections';
import { SettingsPage } from './SettingsPage';

afterEach(cleanup);

beforeEach(() => {
  window.matchMedia = vi.fn().mockReturnValue({
    matches: false,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }) as unknown as typeof window.matchMedia;
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

const CONFIG_FIXTURE: RuntimeConfig = {
  max_concurrent: 3,
  model: 'sonnet',
  coder: 'claude',
  telegram_chat_id: '',
  telegram_allowed_ids: '',
  telegram_default_cwd: '',
  opencode_ollama_url: 'http://127.0.0.1:11435/v1',
  ollama_ssh_host: 'rtx',
  ollama_remote_port: 11434,
  max_concurrent_overrides: 'claude:2',
  context_windows: '',
  opencode_default_model: 'qwen3.6:latest',
  opencode_bedrock_region: '',
  opencode_bedrock_profile: '',
  stall_warning_minutes: 15,
  stall_action: 'kill',
  max_attempt_minutes: 120,
  continue_pack_max_bytes: 8192,
  state_max_bytes: 6144,
  compaction_enabled: true,
  compaction_coder: 'claude',
  compaction_model: 'haiku',
  context_checkpoint_pct: 75,
  context_kill_pct: 90,
  isolation: 'worktree',
  isolation_exclude: '',
  post_merge_command: '',
  triage_interval_minutes: 15,
  gc_retention_days: 30,
  gc_archive_days: 90,
  observer_max_followups: 10,
  observer_max_rounds: 3,
  job_gate: true,
  job_child_coder: 'claude',
  job_child_model: 'sonnet',
  job_max_children: 30,
  job_max_phase_attempts: 2,
  serve_cors_origins: [],
  serve_host: '0.0.0.0',
  serve_port: 7890,
  restart_required: ['serve_host', 'serve_port', 'serve_cors_origins'],
};

const CODERS_FIXTURE: CoderInfo[] = [
  { name: 'claude', context_limit: 200000, default_model: 'sonnet' },
  { name: 'opencode', context_limit: 128000, default_model: 'qwen3.6:latest' },
];

const CONSTANTS_FIXTURE: ConfigConstant[] = [
  { name: 'CONFIG_POLL_INTERVAL_SEC', value: '5', unit: 'seconds', doc: 'Config re-read cadence.', module: 'core/limits.py' },
  { name: 'FAILURE_WAIT_SEC', value: '(60, 300, 900)', unit: 'seconds', doc: 'Failure back-off.', module: 'core/retry_policy.py' },
];

function mockSettings() {
  vi.spyOn(api, 'getConfig').mockResolvedValue({ ...CONFIG_FIXTURE });
  vi.spyOn(api, 'getCoders').mockResolvedValue({ coders: CODERS_FIXTURE });
  vi.spyOn(api, 'getSupervisor').mockResolvedValue({
    pid: 123,
    started_at: null,
    running: true,
    max_concurrent: 3,
    active_count: 1,
    free_slots: 2,
    paused: false,
  } as never);
  vi.spyOn(api, 'getConfigConstants').mockResolvedValue({ constants: CONSTANTS_FIXTURE });
}

function wrapper(initialEntries: string[] = ['/settings']) {
  return function Wrapper({ children }: { children: ReactNode }) {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    return (
      <QueryClientProvider client={client}>
        <ToastProvider>
          <MemoryRouter initialEntries={initialEntries}>{children}</MemoryRouter>
        </ToastProvider>
      </QueryClientProvider>
    );
  };
}

function renderSettings() {
  return render(<SettingsPage />, { wrapper: wrapper() });
}

describe('settings field coverage', () => {
  it('maps every RuntimeConfig field into exactly one section', () => {
    // FIELD_DEFS is Record<SettingKey, ...> where SettingKey excludes only
    // the GET-only restart_required meta key, so tsc already fails when the
    // backend adds a field nobody grouped; this asserts the runtime shape.
    const sectionIds = new Set(SECTIONS.map(s => s.id));
    const seen = new Set<string>();
    for (const [key, def] of Object.entries(FIELD_DEFS)) {
      expect(sectionIds.has(def.section)).toBe(true);
      expect(seen.has(key)).toBe(false);
      seen.add(key);
    }
    for (const section of SECTIONS) {
      if (section.id === 'supervisor' || section.id === 'notifications' || section.id === 'constants') {
        expect(fieldsFor(section.id)).toHaveLength(0);
      } else {
        expect(fieldsFor(section.id).length).toBeGreaterThan(0);
      }
    }
  });

  it('renders every section with its fields', async () => {
    mockSettings();
    renderSettings();

    expect(await screen.findByRole('heading', { name: 'Settings' })).toBeInTheDocument();
    for (const section of SECTIONS) {
      expect(screen.getByRole('region', { name: section.title })).toBeInTheDocument();
    }
    for (const label of [
      /^Max concurrent/,
      /^Default coder/,
      /^Per-model context windows/,
      /^Stall action/,
      /^Post-merge command/,
      /^Triage interval/,
      /^Job approval gate/,
      /^Compaction enabled/,
      /^Retention/,
      /^Telegram chat ID/,
      /^Bind address/,
    ]) {
      // Anchored: help text of other labels may mention the same words.
      expect(screen.getByLabelText(label)).toBeInTheDocument();
    }
    expect(screen.getByRole('region', { name: 'Installed coders' })).toBeInTheDocument();
  });
});

describe('settings dropdowns and badges', () => {
  it('feeds coder/model dropdowns from useCoders()', async () => {
    mockSettings();
    renderSettings();

    const codersRegion = await screen.findByRole('region', { name: 'Coders and models' });
    const coderSelect = within(codersRegion).getByLabelText(/^Default coder/);
    const coderOptions = within(coderSelect as HTMLElement).getAllByRole('option');
    expect(coderOptions.map(o => o.getAttribute('value'))).toEqual(
      expect.arrayContaining(['claude', 'opencode']),
    );
    const modelSelect = within(codersRegion).getByLabelText(/^Default model/);
    const modelOptions = within(modelSelect as HTMLElement).getAllByRole('option');
    expect(modelOptions.map(o => o.getAttribute('value'))).toEqual(
      expect.arrayContaining(['sonnet', 'qwen3.6:latest']),
    );
    // Installed coders list shows context windows and default models.
    const installed = screen.getByRole('region', { name: 'Installed coders' });
    expect(within(installed).getByText('claude')).toBeInTheDocument();
    expect(within(installed).getByText(/qwen3.6:latest/)).toBeInTheDocument();
  });

  it('badges exactly the restart_required server fields', async () => {
    mockSettings();
    renderSettings();

    await screen.findByRole('heading', { name: 'Settings' });
    expect(screen.getAllByText('restart required')).toHaveLength(3);
    const server = screen.getByRole('region', { name: 'Server' });
    expect(within(server).getAllByText('restart required')).toHaveLength(3);
    const concurrency = screen.getByRole('region', { name: 'Concurrency' });
    expect(within(concurrency).queryByText('restart required')).not.toBeInTheDocument();
  });
});

describe('settings constants table', () => {
  it('renders tunables and filters by search', async () => {
    mockSettings();
    renderSettings();

    expect(await screen.findByText('CONFIG_POLL_INTERVAL_SEC')).toBeInTheDocument();
    expect(screen.getByText('FAILURE_WAIT_SEC')).toBeInTheDocument();
    expect(screen.getByText('core/retry_policy.py')).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText(/Search name/), { target: { value: 'retry' } });
    await waitFor(() => expect(screen.queryByText('CONFIG_POLL_INTERVAL_SEC')).not.toBeInTheDocument());
    expect(screen.getByText('FAILURE_WAIT_SEC')).toBeInTheDocument();
  });
});

describe('settings save', () => {
  it('posts only the changed fields of the section', async () => {
    mockSettings();
    const putSpy = vi.spyOn(api, 'putConfig').mockResolvedValue({ ...CONFIG_FIXTURE });
    renderSettings();

    const maxInput = await screen.findByLabelText(/Max concurrent/);
    fireEvent.change(maxInput, { target: { value: '9' } });
    const concurrency = screen.getByRole('region', { name: 'Concurrency' });
    fireEvent.click(within(concurrency).getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(putSpy).toHaveBeenCalledTimes(1));
    expect(putSpy).toHaveBeenCalledWith({ max_concurrent: '9' });
  });

  it('shows PUT validation errors next to the field', async () => {
    mockSettings();
    vi.spyOn(api, 'putConfig').mockRejectedValue(new Error('Invalid isolation mode'));
    renderSettings();

    const section = await screen.findByRole('region', { name: 'Isolation and merge' });
    const isolation = within(section).getByRole('combobox');
    fireEvent.change(isolation, { target: { value: 'none' } });
    fireEvent.click(within(section).getByRole('button', { name: 'Save' }));

    await waitFor(() =>
      expect(within(section).getByText('Invalid isolation mode')).toBeInTheDocument(),
    );
  });
});

describe('settings redirect', () => {
  it('redirects the legacy /config route to /settings', async () => {
    mockSettings();
    render(
      <Routes>
        <Route path="/config" element={<ConfigRedirect />} />
        <Route path="/settings" element={<div>settings marker</div>} />
      </Routes>,
      { wrapper: wrapper(['/config']) },
    );

    expect(await screen.findByText('settings marker')).toBeInTheDocument();
  });
});
