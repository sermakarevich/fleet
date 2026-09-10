// Attention footer below the workers Runs list: one slim sticky bar with
// blocked, rate-limited (24h) and pending inbox question counts plus a
// right-aligned "Showing N of M workers". Blocked comes from the live task
// list; the rest read useAnalyticsSummary(days=1) and useChatQuestions.
import { useNavigate } from 'react-router-dom';
import { useAnalyticsSummary, useChatQuestions } from '../../shared/hooks/useApi';
import { useIsMobile } from '../../shared/hooks/useIsMobile';
import * as T from '../../shared/styles/tokens';
import type { TaskSummary } from '../../shared/types';

interface AttentionFooterProps {
  /** Live task list; blocked counts status === 'blocked'. */
  tasks: TaskSummary[];
  /** Jump the Runs tab to the blocked filter. */
  onSelectBlocked: () => void;
  /** Rows on the current page. */
  shown: number;
  /** Tasks matching the current filter. */
  total: number;
}

// One footer item: a StatusDot-style dot + semibold tabular count + label.
// Zero counts render calm (textDim + border dot); positive counts light up
// in the semantic colour. Clickable items are buttons, display-only items
// are plain spans.
function Item({
  label,
  count,
  activeColor,
  title,
  onClick,
}: {
  label: string;
  count: number;
  activeColor: string;
  title: string;
  onClick?: () => void;
}) {
  const active = count > 0;
  const color = active ? activeColor : T.colors.textDim;
  const body = (
    <>
      <span style={{ ...styles.dot, background: active ? activeColor : T.colors.border }} />
      <span style={{ ...styles.count, color }}>{count}</span>
      <span>{label}</span>
    </>
  );
  if (!onClick) return <span style={{ ...styles.item, color }} title={title}>{body}</span>;
  return (
    <button type="button" style={{ ...styles.item, ...styles.button, color }} title={title}
      onClick={onClick} aria-label={`${label}: ${count}`}>{body}</button>
  );
}

// Slim sticky status line; null on narrow screens where the Runs list
// already fills the viewport.
export function AttentionFooter({ tasks, onSelectBlocked, shown, total }: AttentionFooterProps) {
  const navigate = useNavigate();
  const isNarrow = useIsMobile(480);
  const { data: summary } = useAnalyticsSummary(1);
  const { data: chat } = useChatQuestions();

  if (isNarrow) return null;

  const blocked = tasks.filter((t) => t.status === 'blocked').length;
  const rateLimited24h = summary?.rate_limits.length
    ?? summary?.kpis.rate_limited_tasks
    ?? 0;
  const pendingQuestions = chat?.pending.length ?? 0;

  return (
    <div style={styles.footer} aria-label="Needs attention">
      <Item label="blocked" count={blocked} activeColor={T.colors.amber} title="Blocked workers — filter the list" onClick={onSelectBlocked} />
      <Item label="rate-limited · 24h" count={rateLimited24h} activeColor={T.colors.warningFg} title="Rate-limit events in the last 24 hours" />
      <Item label="questions" count={pendingQuestions} activeColor={T.colors.link} title="Unanswered inbox questions — open inbox" onClick={() => navigate('/inbox')} />
      <span style={styles.showing}>Showing {shown} of {total} workers</span>
    </div>
  );
}

const styles = {
  footer: {
    position: 'sticky' as const,
    bottom: 0,
    display: 'flex',
    alignItems: 'center',
    gap: '1.25rem',
    marginTop: 'auto',
    padding: '0.375rem 0.75rem',
    background: T.colors.bgSurface,
    borderTop: `1px solid ${T.colors.borderSubtle}`,
    fontSize: '0.75rem',
    fontFamily: 'system-ui, sans-serif',
    color: T.colors.textDim,
  } as React.CSSProperties,
  item: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: '0.375rem',
    padding: 0,
    fontSize: 'inherit',
    fontFamily: 'inherit',
  } as React.CSSProperties,
  button: { background: 'transparent', border: 'none', cursor: 'pointer' } as React.CSSProperties,
  dot: { width: '0.4375rem', height: '0.4375rem', borderRadius: '50%', flexShrink: 0 } as React.CSSProperties,
  count: { fontWeight: 600, fontVariantNumeric: 'tabular-nums' as const } as React.CSSProperties,
  showing: { marginLeft: 'auto', color: T.colors.textDim } as React.CSSProperties,
};
