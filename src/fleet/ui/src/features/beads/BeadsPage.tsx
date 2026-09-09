/**
 * Portal into the beads DB: browse beads, filter by status, read detail,
 * change status, unblock and remove assignees.
 * Composes FilterBar, DataList and BeadDrawer on the shared PageShell;
 * filter state lives in useBeadFilters (synced to the URL). Called by
 * App's /bd route.
 */
import { useState } from 'react';
import { useBeads } from '../../shared/hooks/useApi';
import { useIsMobile } from '../../shared/hooks/useIsMobile';
import * as R from '../../shared/styles/recipes';
import { DataList } from '../../shared/ui/DataList';
import { FilterBar } from '../../shared/ui/FilterBar';
import { LoadingState } from '../../shared/ui/LoadingState';
import { PageShell } from '../../shared/ui/PageShell';
import { useBeadFilters, BEAD_FILTERS } from './useBeadFilters';
import { BeadCard, beadColumns } from './beadColumns';
import { BeadDrawer } from './BeadDrawer';

// Beads browser: filters on top, list below, drawer on selection.
export function BeadsPage() {
  const { data: beads, isLoading, error } = useBeads();
  const isMobile = useIsMobile();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const filters = useBeadFilters(beads);

  if (error) {
    return <p style={R.errorMsgStyle()}>Error: {String(error)}</p>;
  }

  return (
    <PageShell title="beads" count={filters.sorted.length}>
      <div style={R.topBarStyle()}>
        <FilterBar
          searchQuery={filters.searchQuery}
          onSearchQuery={filters.setSearchQuery}
          searchPlaceholder="Search id, title, assignee…"
          searchWidth={isMobile ? '100%' : '15rem'}
          filters={BEAD_FILTERS}
          active={filters.statusFilter}
          onSelect={filters.setStatusFilter}
        />
      </div>
      {isLoading ? (
        <LoadingState />
      ) : (
        <>
          <DataList
            columns={beadColumns()}
            rows={filters.pageItems}
            rowKey={(bead) => bead.id}
            onRowClick={(bead) => setSelectedId(bead.id)}
            renderCard={(bead) => <BeadCard bead={bead} />}
            selectedKey={selectedId}
            empty="No beads."
          />
          {filters.totalPages > 1 && (
            <div style={R.paginationStyle()}>
              <button
                style={R.pageBtnStyle(filters.page === 0)}
                disabled={filters.page === 0}
                onClick={() => filters.setPage(Math.max(0, filters.page - 1))}
              >
                ← Prev
              </button>
              <span style={R.pageInfoStyle()}>
                {filters.page + 1} / {filters.totalPages}
              </span>
              <button
                style={R.pageBtnStyle(filters.page >= filters.totalPages - 1)}
                disabled={filters.page >= filters.totalPages - 1}
                onClick={() => filters.setPage(Math.min(filters.totalPages - 1, filters.page + 1))}
              >
                Next →
              </button>
            </div>
          )}
        </>
      )}
      {selectedId && <BeadDrawer beadId={selectedId} onClose={() => setSelectedId(null)} />}
    </PageShell>
  );
}
