/**
 * Workflows browser: list of saved worker stage-graphs, YAML import with
 * replace-on-conflict, and the stage/step editor for new and existing
 * workflows. Called by App's /workflows, /workflows/new and
 * /workflows/:id routes; the edited id lives in the URL so it is shareable.
 */
import { useRef, useState } from 'react';
import { Link, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { ApiError } from '../../shared/api';
import {
  useAllWorkflowRuns,
  useDeleteWorkflow,
  useImportWorkflow,
  useRunWorkflow,
  useWorkflow,
  useWorkflowRuns,
  useWorkflows,
} from '../../shared/hooks/useApi';
import { useIsMobile } from '../../shared/hooks/useIsMobile';
import * as T from '../../shared/styles/tokens';
import * as R from '../../shared/styles/recipes';
import type { Workflow } from '../../shared/types';
import { WorkflowEditor } from './WorkflowEditor';
import { WorkflowsTable } from './WorkflowsTable';
import { RunsTable } from './RunsTable';

// Pending import that hit a name clash, waiting on replace confirmation.
interface ImportConflict {
  yaml: string;
  message: string;
}

// `name:` line of a workflow YAML document (for replace-by-name lookup).
function parseWorkflowName(yaml: string): string | null {
  const match = yaml.match(/^name:\s*["']?(.+?)["']?\s*$/m);
  return match?.[1]?.trim() || null;
}

// Runs of every workflow: status filter, table, paging (limit 50).
function AllRunsView({ isMobile, onOpen }: { isMobile: boolean; onOpen: (runId: string) => void }) {
  const [status, setStatus] = useState('all');
  const [offset, setOffset] = useState(0);
  const limit = 50;
  const { data, isLoading, error } = useAllWorkflowRuns(
    status === 'all' ? undefined : status,
    { limit, offset },
  );
  if (isLoading) return <p style={R.msgStyle()}>Loading…</p>;
  if (error) return <p style={R.errorMsgStyle()}>Error: {String(error)}</p>;
  const runs = data?.runs ?? [];
  const total = data?.total ?? 0;
  return (
    <div>
      <div style={R.filterRowStyle()}>
        {['all', 'running', 'attention', 'succeeded', 'cancelled'].map((key) => (
          <button
            key={key}
            style={R.filterBtnStyle(status === key)}
            onClick={() => { setStatus(key); setOffset(0); }}
          >
            {key === 'all' ? 'All' : key[0].toUpperCase() + key.slice(1)}
          </button>
        ))}
      </div>
      <div style={styles.runsGap} />
      <RunsTable runs={runs} onOpen={onOpen} isMobile={isMobile} />
      <Pagination offset={offset} limit={limit} total={total} onPage={setOffset} />
    </div>
  );
}

// Runs of one workflow (/workflows/:id/runs): back link, table, paging.
function WorkflowRunsView({ workflowId, isMobile, onOpen }: {
  workflowId: string; isMobile: boolean; onOpen: (runId: string) => void;
}) {
  const { data: workflow } = useWorkflow(workflowId);
  const [offset, setOffset] = useState(0);
  const limit = 50;
  const { data, isLoading, error } = useWorkflowRuns(workflowId, { limit, offset });
  if (isLoading) return <p style={R.msgStyle()}>Loading…</p>;
  if (error) return <p style={R.errorMsgStyle()}>Error: {String(error)}</p>;
  const runs = data?.runs ?? [];
  const total = data?.total ?? 0;
  return (
    <div>
      <p style={styles.backLine}>
        <Link to="/workflows?view=runs">← All runs</Link>
        {' · '}
        {workflow?.name ?? workflowId} <span style={R.countStyle()}>({total})</span>
      </p>
      <RunsTable runs={runs} onOpen={onOpen} isMobile={isMobile} />
      <Pagination offset={offset} limit={limit} total={total} onPage={setOffset} />
    </div>
  );
}

// Prev/Next pager shared by both runs views.
function Pagination({ offset, limit, total, onPage }: {
  offset: number; limit: number; total: number; onPage: (offset: number) => void;
}) {
  if (total <= limit) return null;
  const page = Math.floor(offset / limit) + 1;
  const pages = Math.max(1, Math.ceil(total / limit));
  return (
    <div style={R.paginationStyle()}>
      <button style={R.pageBtnStyle(offset === 0)} disabled={offset === 0} onClick={() => onPage(Math.max(0, offset - limit))}>
        ← Prev
      </button>
      <span style={R.pageInfoStyle()}>{page} / {pages}</span>
      <button
        style={R.pageBtnStyle(offset + limit >= total)}
        disabled={offset + limit >= total}
        onClick={() => onPage(offset + limit)}
      >
        Next →
      </button>
    </div>
  );
}

// Workflows page: heading, import/export entry points, table or editor.
export function WorkflowsPage() {
  const { data: workflows, isLoading, error } = useWorkflows();
  const isMobile = useIsMobile();
  const navigate = useNavigate();
  const location = useLocation();
  const { id: selectedId } = useParams();
  const fileRef = useRef<HTMLInputElement>(null);
  const importWorkflow = useImportWorkflow();
  const runWorkflow = useRunWorkflow();
  const deleteWorkflow = useDeleteWorkflow();
  const [conflict, setConflict] = useState<ImportConflict | null>(null);

  const items = workflows ?? [];
  const isNew = location.pathname.endsWith('/new');
  const runsOfId = location.pathname.endsWith('/runs') ? (selectedId ?? null) : null;
  const editingId = isNew || runsOfId ? null : (selectedId ?? null);
  const [searchParams, setSearchParams] = useSearchParams();
  const view = searchParams.get('view') === 'runs' ? 'runs' : 'definitions';

  async function importYaml(yaml: string, replace_id?: string) {
    try {
      const saved = await importWorkflow.mutateAsync({ yaml, replace_id });
      setConflict(null);
      navigate(`/workflows/${saved.id}`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409 && !replace_id) {
        setConflict({ yaml, message: err.message });
      }
      // Other failures already toast via the mutation.
    }
  }

  function onImportFile(file: File) {
    const reader = new FileReader();
    reader.onload = () => {
      const text = typeof reader.result === 'string' ? reader.result : '';
      if (text) void importYaml(text);
    };
    reader.readAsText(file);
  }

  // Retry the conflicted import against the existing same-named workflow.
  function replaceExisting() {
    if (!conflict) return;
    const name = parseWorkflowName(conflict.yaml);
    const existing = name ? items.find((w) => w.name === name) : undefined;
    if (!existing) return;
    void importYaml(conflict.yaml, existing.id);
  }

  function onRun(id: string) {
    runWorkflow.mutate(id);
  }

  function onDelete(id: string) {
    deleteWorkflow.mutate(id);
  }

  function onSaved(saved: Workflow) {
    navigate(`/workflows/${saved.id}`);
  }

  if (isLoading) {
    return <p style={R.msgStyle()}>Loading…</p>;
  }
  if (error) {
    return <p style={R.errorMsgStyle()}>Error: {String(error)}</p>;
  }

  // Runs of one workflow live under /workflows/:id/runs.
  if (runsOfId) {
    return (
      <div style={R.pageStyle(isMobile)}>
        <div style={R.topBarStyle()}>
          <h2 style={R.headingStyle()}>Runs</h2>
        </div>
        <WorkflowRunsView
          workflowId={runsOfId}
          isMobile={isMobile}
          onOpen={(runId) => navigate(`/workflow-runs/${runId}`)}
        />
      </div>
    );
  }

  function setView(next: 'definitions' | 'runs') {
    setSearchParams(next === 'runs' ? { view: 'runs' } : {});
  }

  return (
    <div style={R.pageStyle(isMobile)}>
      <div style={R.topBarStyle()}>
        <h2 style={R.headingStyle()}>
          {view === 'runs' ? 'Runs' : <>Workflows <span style={R.countStyle()}>({items.length})</span></>}
        </h2>
        <span style={R.filterRowStyle()}>
          <button style={R.filterBtnStyle(view === 'definitions')} onClick={() => setView('definitions')}>
            Definitions
          </button>
          <button style={R.filterBtnStyle(view === 'runs')} onClick={() => setView('runs')}>
            Runs
          </button>
        </span>
        <span style={styles.topActions}>
          <input
            ref={fileRef}
            type="file"
            accept=".yaml,.yml"
            style={styles.hiddenInput}
            aria-label="Import workflow YAML file"
            onChange={(e) => {
              const file = e.target.files?.[0];
              e.target.value = '';
              if (file) onImportFile(file);
            }}
          />
          <button style={T.btnGhost} onClick={() => fileRef.current?.click()}>
            Import YAML
          </button>
          <button style={T.btnPrimary} onClick={() => navigate('/workflows/new')}>
            + New workflow
          </button>
        </span>
      </div>
      {conflict && (
        <p style={styles.conflictBar}>
          {conflict.message}{' '}
          <button style={T.btnGhost} onClick={replaceExisting}>
            Replace existing
          </button>{' '}
          <button style={T.btnGhost} onClick={() => setConflict(null)}>
            Keep both
          </button>
        </p>
      )}
      {isNew || editingId ? (
        <WorkflowEditor
          workflowId={editingId}
          onClose={() => navigate('/workflows')}
          onSaved={onSaved}
        />
      ) : view === 'runs' ? (
        <AllRunsView
          isMobile={isMobile}
          onOpen={(runId) => navigate(`/workflow-runs/${runId}`)}
        />
      ) : (
        <WorkflowsTable
          items={items}
          onEdit={(id) => navigate(`/workflows/${id}`)}
          onRun={onRun}
          onDelete={onDelete}
          runningId={runWorkflow.isPending ? (runWorkflow.variables ?? null) : null}
          isMobile={isMobile}
        />
      )}
    </div>
  );
}

const styles = {
  runsGap: { height: '0.75rem' } as React.CSSProperties,
  backLine: {
    fontSize: '0.875rem', color: T.colors.textSecondary, margin: '0 0 0.75rem',
  } as React.CSSProperties,
  topActions: {
    marginLeft: 'auto', display: 'inline-flex', gap: '0.5rem', alignItems: 'center',
  } as React.CSSProperties,
  hiddenInput: { display: 'none' } as React.CSSProperties,
  conflictBar: {
    padding: '0.5rem 1rem', margin: '0 0 0.875rem',
    background: T.colors.warningBg, color: T.colors.warningFg,
    borderRadius: 6, fontSize: '0.875rem', fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
};
