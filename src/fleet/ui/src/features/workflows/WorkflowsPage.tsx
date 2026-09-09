/**
 * Workflows browser: list of saved worker stage-graphs, YAML import with
 * replace-on-conflict, and the stage/step editor for new and existing
 * workflows. Composes DataList on the shared PageShell with
 * Definitions/Runs/Scheduled sub-tabs (Scheduled shows workflow-target
 * triggers via the shared TriggerTable); the edited id lives in the URL
 * so it is shareable. Called by App's /workflows, /workflows/new and
 * /workflows/:id routes.
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
import * as T from '../../shared/styles/tokens';
import * as R from '../../shared/styles/recipes';
import { DataList } from '../../shared/ui/DataList';
import { LoadingState } from '../../shared/ui/LoadingState';
import { PageShell } from '../../shared/ui/PageShell';
import type { Workflow } from '../../shared/types';
import { TriggerTable } from '../triggers/TriggerTable';
import { RunWorkflowModal } from './RunWorkflowModal';
import { WorkflowEditor } from './WorkflowEditor';
import { WorkflowCard, workflowColumns } from './workflowColumns';
import { RunCard, runColumns } from './runColumns';

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

const RUN_FILTERS = [
  { key: 'all', label: 'All' },
  { key: 'running', label: 'Running' },
  { key: 'attention', label: 'Attention' },
  { key: 'succeeded', label: 'Succeeded' },
  { key: 'cancelled', label: 'Cancelled' },
] as const;

type RunFilter = (typeof RUN_FILTERS)[number]['key'];

// Runs of every workflow: status filter, list, paging (limit 50).
function AllRunsView({ onOpen }: { onOpen: (runId: string) => void }) {
  const [status, setStatus] = useState<RunFilter>('all');
  const [offset, setOffset] = useState(0);
  const limit = 50;
  const { data, isLoading, error } = useAllWorkflowRuns(
    status === 'all' ? undefined : status,
    { limit, offset },
  );
  if (isLoading) return <LoadingState />;
  if (error) return <p style={R.errorMsgStyle()}>Error: {String(error)}</p>;
  const runs = data?.runs ?? [];
  const total = data?.total ?? 0;
  return (
    <div>
      <div style={R.filterRowStyle()}>
        {RUN_FILTERS.map(({ key, label }) => (
          <button
            key={key}
            style={R.filterBtnStyle(status === key)}
            onClick={() => { setStatus(key); setOffset(0); }}
          >
            {label}
          </button>
        ))}
      </div>
      <div style={styles.runsGap} />
      <DataList
        columns={runColumns()}
        rows={runs}
        rowKey={(run) => run.id}
        onRowClick={(run) => onOpen(run.id)}
        renderCard={(run) => <RunCard run={run} />}
        empty="No runs yet. Start a run from a workflow with the Run button."
      />
      <Pagination offset={offset} limit={limit} total={total} onPage={setOffset} />
    </div>
  );
}

// Runs of one workflow (/workflows/:id/runs): back link, list, paging.
function WorkflowRunsView({ workflowId, onOpen }: {
  workflowId: string; onOpen: (runId: string) => void;
}) {
  const { data: workflow } = useWorkflow(workflowId);
  const [offset, setOffset] = useState(0);
  const limit = 50;
  const { data, isLoading, error } = useWorkflowRuns(workflowId, { limit, offset });
  if (isLoading) return <LoadingState />;
  if (error) return <p style={R.errorMsgStyle()}>Error: {String(error)}</p>;
  const runs = data?.runs ?? [];
  const total = data?.total ?? 0;
  return (
    <div>
      <p style={styles.backLine}>
        <Link to="/workflows?tab=runs">← All runs</Link>
        {' · '}
        {workflow?.name ?? workflowId} <span style={R.countStyle()}>({total})</span>
      </p>
      <DataList
        columns={runColumns()}
        rows={runs}
        rowKey={(run) => run.id}
        onRowClick={(run) => onOpen(run.id)}
        renderCard={(run) => <RunCard run={run} />}
        empty="No runs yet. Start a run from a workflow with the Run button."
      />
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

// Workflows page: heading, import/export entry points, list or editor.
export function WorkflowsPage() {
  const { data: workflows, isLoading, error } = useWorkflows();
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
  // Workflow waiting for its run form (declared inputs need values first).
  const [runTarget, setRunTarget] = useState<Workflow | null>(null);
  const [searchParams, setSearchParams] = useSearchParams();
  // Sub-tab from ?tab= (canonical, ADR 0009); ?view= is the legacy alias
  // from before the Scheduled sub-tab existed.
  const tabParam = searchParams.get('tab') ?? searchParams.get('view');
  const view = tabParam === 'runs' ? 'runs' : tabParam === 'scheduled' ? 'scheduled' : 'definitions';

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

  // Run immediately when the workflow declares no inputs; otherwise
  // open the run form so the operator can supply the input values.
  function onRun(id: string) {
    const target = items.find((w) => w.id === id);
    if (target && (target.inputs ?? []).length > 0) {
      setRunTarget(target);
      return;
    }
    runWorkflow.mutate({ id });
  }

  function onDelete(id: string) {
    deleteWorkflow.mutate(id);
  }

  function onSaved(saved: Workflow) {
    navigate(`/workflows/${saved.id}`);
  }

  // Runs of one workflow live under /workflows/:id/runs.
  if (runsOfId) {
    return (
      <PageShell title="Runs">
        <WorkflowRunsView
          workflowId={runsOfId}
          onOpen={(runId) => navigate(`/workflow-runs/${runId}`)}
        />
      </PageShell>
    );
  }

  function setView(next: 'definitions' | 'runs' | 'scheduled') {
    setSearchParams(next === 'definitions' ? {} : { tab: next });
  }

  const cb = {
    onEdit: (id: string) => navigate(`/workflows/${id}`),
    onRun,
    onDelete,
    runningId: runWorkflow.isPending ? (runWorkflow.variables?.id ?? null) : null,
  };

  return (
    <PageShell
      title={view === 'runs' ? 'Runs' : view === 'scheduled' ? 'Scheduled' : 'Workflows'}
      count={view === 'definitions' ? items.length : undefined}
      tabs={[
        { id: 'definitions', label: 'Definitions' },
        { id: 'runs', label: 'Runs' },
        { id: 'scheduled', label: 'Scheduled' },
      ]}
      activeTab={view}
      onTabChange={(id) => setView(id as 'definitions' | 'runs' | 'scheduled')}
      actions={
        view === 'scheduled' ? undefined : (
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
        )
      }
    >
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
      {runTarget && (
        <RunWorkflowModal
          workflow={runTarget}
          onClose={() => setRunTarget(null)}
          onStarted={(runId) => navigate(`/workflow-runs/${runId}`)}
        />
      )}
      {isNew || editingId ? (
        <WorkflowEditor
          workflowId={editingId}
          onClose={() => navigate('/workflows')}
          onSaved={onSaved}
        />
      ) : view === 'scheduled' ? (
        <TriggerTable target="workflow" />
      ) : view === 'runs' ? (
        <AllRunsView
          onOpen={(runId) => navigate(`/workflow-runs/${runId}`)}
        />
      ) : isLoading ? (
        <LoadingState />
      ) : error ? (
        <p style={R.errorMsgStyle()}>Error: {String(error)}</p>
      ) : (
        <DataList
          columns={workflowColumns(cb)}
          rows={items}
          rowKey={(workflow) => workflow.id}
          onRowClick={(workflow) => navigate(`/workflows/${workflow.id}`)}
          renderCard={(workflow) => <WorkflowCard workflow={workflow} cb={cb} />}
          empty="No workflows yet. Arrange workers into stages and save them as a workflow, or import a YAML file."
        />
      )}
    </PageShell>
  );
}

const styles = {
  runsGap: { height: '0.75rem' } as React.CSSProperties,
  backLine: {
    fontSize: '0.875rem', color: T.colors.textSecondary, margin: '0 0 0.75rem',
  } as React.CSSProperties,
  topActions: {
    display: 'inline-flex', gap: '0.5rem', alignItems: 'center',
  } as React.CSSProperties,
  hiddenInput: { display: 'none' } as React.CSSProperties,
  conflictBar: {
    padding: '0.5rem 1rem', margin: '0 0 0.875rem',
    background: T.colors.warningBg, color: T.colors.warningFg,
    borderRadius: '0.375rem', fontSize: '0.875rem', fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
};
