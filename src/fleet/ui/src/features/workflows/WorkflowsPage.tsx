/**
 * Workflows browser: list of saved worker stage-graphs, YAML import with
 * replace-on-conflict, and the stage/step editor for new and existing
 * workflows. Called by App's /workflows, /workflows/new and
 * /workflows/:id routes; the edited id lives in the URL so it is shareable.
 */
import { useRef, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import { ApiError } from '../../shared/api';
import {
  useDeleteWorkflow,
  useImportWorkflow,
  useRunWorkflow,
  useWorkflows,
} from '../../shared/hooks/useApi';
import { useIsMobile } from '../../shared/hooks/useIsMobile';
import * as T from '../../shared/styles/tokens';
import * as R from '../../shared/styles/recipes';
import type { Workflow } from '../../shared/types';
import { WorkflowEditor } from './WorkflowEditor';
import { WorkflowsTable } from './WorkflowsTable';

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
  const editingId = isNew ? null : (selectedId ?? null);

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

  return (
    <div style={R.pageStyle(isMobile)}>
      <div style={R.topBarStyle()}>
        <h2 style={R.headingStyle()}>
          Workflows <span style={R.countStyle()}>({items.length})</span>
        </h2>
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
