/**
 * One bead as a table row (desktop) or a card (mobile).
 * Called by BeadsTable; selection is owned by BeadsPage.
 */
import type { Bead } from '../../shared/types';
import * as T from '../../shared/styles/tokens';
import * as R from '../../shared/styles/recipes';
import { useClickableProps } from '../../shared/ui/Clickable';
import { StatusChip } from '../../shared/ui/StatusChip';

interface Props {
  bead: Bead;
  selected: boolean;
  onSelect: (id: string) => void;
}

// Dim placeholder for missing values.
function Dim({ children }: { children: React.ReactNode }) {
  return <span style={R.dimStyle()}>{children}</span>;
}

// Desktop table row for one bead.
export function BeadRow({ bead, selected, onSelect }: Props) {
  const depCount = bead.dependency_count ?? 0;
  const rowClick = useClickableProps(() => onSelect(bead.id));
  return (
    <div style={R.rowStyle(selected)} className="row-interactive" {...rowClick}>
      <StatusChip status={bead.status} width="6rem" />
      <span style={R.idCellStyle()}>{bead.id}</span>
      <span style={R.titleCellStyle()} title={bead.title}>{bead.title}</span>
      <span style={styles.prioCell}>
        {bead.priority != null ? bead.priority : <Dim>—</Dim>}
      </span>
      <span style={styles.assigneeCell} title={bead.assignee ?? undefined}>
        {bead.assignee ?? <Dim>—</Dim>}
      </span>
      <span style={styles.depsCell}>
        {depCount > 0 ? `${depCount} dep${depCount === 1 ? '' : 's'}` : <Dim>—</Dim>}
      </span>
    </div>
  );
}

// Mobile card for one bead.
export function BeadCard({ bead, selected, onSelect }: Props) {
  const depCount = bead.dependency_count ?? 0;
  const cardClick = useClickableProps(() => onSelect(bead.id));
  return (
    <div
      style={R.merge(styles.card, R.when(selected, styles.cardSelected))}
      className="row-interactive"
      {...cardClick}
    >
      <div style={styles.cardHead}>
        <StatusChip status={bead.status} width="6rem" />
        <span style={styles.cardId}>{bead.id}</span>
        {bead.assignee && <span style={styles.cardAssignee}>{bead.assignee}</span>}
      </div>
      <div style={styles.cardTitle} title={bead.title}>{bead.title}</div>
      <div style={styles.cardMeta}>
        {bead.priority != null && <span style={styles.cardMetaText}>pri {bead.priority}</span>}
        {depCount > 0 && <span style={styles.cardMetaText}>{depCount} dep{depCount === 1 ? '' : 's'}</span>}
      </div>
    </div>
  );
}

const styles = {
  prioCell: {
    width: '3rem', flexShrink: 0, fontSize: '0.8125rem',
    color: T.colors.textSecondary, textAlign: 'center' as const,
  } as React.CSSProperties,
  assigneeCell: {
    width: '8rem', flexShrink: 0, fontSize: '0.8125rem', color: T.colors.textSecondary,
    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  depsCell: {
    width: '5rem', flexShrink: 0, fontSize: '0.8125rem', color: T.colors.textSecondary,
  } as React.CSSProperties,
  card: {
    padding: '0.625rem 0.875rem', borderBottom: `1px solid ${T.colors.borderSubtle}`,
    cursor: 'pointer', display: 'flex', flexDirection: 'column' as const,
    gap: '0.3rem', fontSize: '0.875rem', color: T.colors.textBody,
  } as React.CSSProperties,
  cardSelected: {
    background: T.colors.borderSubtle,
  } as React.CSSProperties,
  cardHead: {
    display: 'flex', alignItems: 'center', gap: '0.5rem',
  } as React.CSSProperties,
  cardId: {
    fontFamily: 'monospace', color: T.colors.link, fontSize: '0.8125rem', flex: 1, minWidth: 0,
    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  cardAssignee: {
    fontSize: '0.75rem', color: T.colors.textSecondary, flexShrink: 0,
    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const, maxWidth: '7rem',
  } as React.CSSProperties,
  cardTitle: {
    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  cardMeta: {
    display: 'flex', gap: '0.625rem', flexWrap: 'wrap' as const,
  } as React.CSSProperties,
  cardMetaText: {
    fontSize: '0.75rem', color: T.colors.textSecondary,
  } as React.CSSProperties,
};
