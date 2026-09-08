/**
 * Paginated bead list with column headers and row selection.
 * Called by BeadsPage; rows render via BeadRow/BeadCard.
 */
import type { Bead } from '../../shared/types';
import * as R from '../../shared/styles/recipes';
import { BeadCard, BeadRow } from './BeadRow';

interface Props {
  items: Bead[];
  totalPages: number;
  page: number;
  onPage: (p: number) => void;
  selectedId: string | null;
  onSelect: (id: string) => void;
  isMobile: boolean;
  emptyLabel?: string;
}

// Table of beads with headers, empty state and pagination.
export function BeadsTable({ items, totalPages, page, onPage, selectedId, onSelect, isMobile, emptyLabel = 'No beads.' }: Props) {
  return (
    <>
      <div style={R.panelStyle()}>
        {!isMobile && (
          <div style={R.colHeaderStyle()}>
            <span style={styles.cStatus}>Status</span>
            <span style={styles.cId}>ID</span>
            <span style={styles.cTitle}>Title</span>
            <span style={styles.cPrio}>Pri</span>
            <span style={styles.cAssignee}>Assignee</span>
            <span style={styles.cDeps}>Deps</span>
          </div>
        )}
        {items.length === 0 ? (
          <p style={R.emptyStyle()}>{emptyLabel}</p>
        ) : (
          items.map((bead) =>
            isMobile ? (
              <BeadCard key={bead.id} bead={bead} selected={selectedId === bead.id} onSelect={onSelect} />
            ) : (
              <BeadRow key={bead.id} bead={bead} selected={selectedId === bead.id} onSelect={onSelect} />
            ),
          )
        )}
      </div>

      {totalPages > 1 && (
        <div style={R.paginationStyle()}>
          <button style={R.pageBtnStyle(page === 0)} disabled={page === 0} onClick={() => onPage(Math.max(0, page - 1))}>
            ← Prev
          </button>
          <span style={R.pageInfoStyle()}>
            {page + 1} / {totalPages}
          </span>
          <button
            style={R.pageBtnStyle(page >= totalPages - 1)}
            disabled={page >= totalPages - 1}
            onClick={() => onPage(Math.min(totalPages - 1, page + 1))}
          >
            Next →
          </button>
        </div>
      )}
    </>
  );
}

const styles = {
  cStatus:   { width: '6rem', flexShrink: 0 } as React.CSSProperties,
  cId:       { width: '6rem', flexShrink: 0 } as React.CSSProperties,
  cTitle:    { flex: 1, minWidth: 0 } as React.CSSProperties,
  cPrio:     { width: '3rem', flexShrink: 0 } as React.CSSProperties,
  cAssignee: { width: '8rem', flexShrink: 0 } as React.CSSProperties,
  cDeps:     { width: '5rem', flexShrink: 0 } as React.CSSProperties,
};
