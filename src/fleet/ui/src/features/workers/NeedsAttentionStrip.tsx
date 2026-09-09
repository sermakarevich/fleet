// Needs-attention strip above the workers Runs list: four compact tiles
// for blocked workers, failures in the last 24h, rate-limit events in the
// last 24h and pending inbox questions. Blocked comes from the live task
// list; the rest read useAnalyticsSummary(days=1) and useChatQuestions.
// Rendered by WorkersPage; hidden on narrow screens (<480px).
import { useNavigate } from 'react-router-dom';
import { useAnalyticsSummary, useChatQuestions } from '../../shared/hooks/useApi';
import { useIsMobile } from '../../shared/hooks/useIsMobile';
import * as T from '../../shared/styles/tokens';
import type { TaskSummary } from '../../shared/types';

interface NeedsAttentionStripProps {
  /** Live task list; blocked tiles count status === 'blocked'. */
  tasks: TaskSummary[];
  /** Jump the Runs tab to the blocked filter. */
  onSelectBlocked: () => void;
  /** Jump the Runs tab to the failed filter. */
  onSelectFailed: () => void;
}

// One compact tile: a coloured count plus a label; clickable tiles are
// real buttons, display-only tiles are plain divs.
function Tile({
  label,
  count,
  color,
  title,
  onClick,
}: {
  label: string;
  count: number;
  color: string;
  title: string;
  onClick?: () => void;
}) {
  const body = (
    <>
      <span style={{ ...styles.count, color }}>{count}</span>
      <span style={styles.label}>{label}</span>
    </>
  );
  if (!onClick) {
    return (
      <div style={styles.tile} title={title}>
        {body}
      </div>
    );
  }
  return (
    <button
      type="button"
      style={styles.tileButton}
      title={title}
      onClick={onClick}
      aria-label={`${label}: ${count}`}
    >
      {body}
    </button>
  );
}

// Four attention counts; null on narrow screens where the Runs list
// already fills the viewport.
export function NeedsAttentionStrip({ tasks, onSelectBlocked, onSelectFailed }: NeedsAttentionStripProps) {
  const navigate = useNavigate();
  const isNarrow = useIsMobile(480);
  const { data: summary } = useAnalyticsSummary(1);
  const { data: chat } = useChatQuestions();

  if (isNarrow) return null;

  const blocked = tasks.filter((t) => t.status === 'blocked').length;
  const failed24h = (summary?.errors_recent ?? []).filter((e) => e.outcome === 'failed').length;
  const rateLimited24h = summary?.rate_limits.length
    ?? summary?.kpis.rate_limited_tasks
    ?? 0;
  const pendingQuestions = chat?.pending.length ?? 0;

  return (
    <div style={styles.strip} aria-label="Needs attention">
      <Tile
        label="blocked"
        count={blocked}
        color={T.colors.amber}
        title="Blocked workers — filter the list"
        onClick={onSelectBlocked}
      />
      <Tile
        label="failed 24h"
        count={failed24h}
        color={T.colors.danger}
        title="Failures in the last 24 hours — filter the list"
        onClick={onSelectFailed}
      />
      <Tile
        label="rate-limited 24h"
        count={rateLimited24h}
        color={T.colors.warningFg}
        title="Rate-limit events in the last 24 hours"
      />
      <Tile
        label="pending questions"
        count={pendingQuestions}
        color={T.colors.link}
        title="Unanswered inbox questions — open chat"
        onClick={() => navigate('/chat')}
      />
    </div>
  );
}

const styles = {
  strip: {
    display: 'flex',
    gap: '0.5rem',
    flexWrap: 'wrap' as const,
    marginBottom: '0.75rem',
  } as React.CSSProperties,
  tile: {
    display: 'inline-flex',
    alignItems: 'baseline',
    gap: '0.375rem',
    padding: '0.3rem 0.625rem',
    background: T.colors.bgSurface,
    border: `1px solid ${T.colors.borderSubtle}`,
    borderRadius: '0.375rem',
    fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
  tileButton: {
    display: 'inline-flex',
    alignItems: 'baseline',
    gap: '0.375rem',
    padding: '0.3rem 0.625rem',
    background: T.colors.bgSurface,
    border: `1px solid ${T.colors.borderSubtle}`,
    borderRadius: '0.375rem',
    fontFamily: 'system-ui, sans-serif',
    cursor: 'pointer',
  } as React.CSSProperties,
  count: {
    fontSize: '1rem',
    fontWeight: 700,
    lineHeight: 1,
  } as React.CSSProperties,
  label: {
    fontSize: '0.75rem',
    color: T.colors.textSecondary,
  } as React.CSSProperties,
};
