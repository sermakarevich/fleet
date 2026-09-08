/**
 * Portal into the beads DB: browse beads, filter by status, read detail,
 * change status, unblock and remove assignees.
 * Composes BeadsFilters, BeadsTable and BeadDrawer; filter state lives
 * in useBeadFilters (synced to the URL). Called by App's /bd route.
 */
import { useState } from 'react';
import { useBeads } from '../../shared/hooks/useApi';
import { useIsMobile } from '../../shared/hooks/useIsMobile';
import * as R from '../../shared/styles/recipes';
import { useBeadFilters } from './useBeadFilters';
import { BeadsFilters } from './BeadsFilters';
import { BeadsTable } from './BeadsTable';
import { BeadDrawer } from './BeadDrawer';

// Beads browser: filters on top, table below, drawer on selection.
export function BeadsPage() {
  const { data: beads, isLoading, error } = useBeads();
  const isMobile = useIsMobile();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const filters = useBeadFilters(beads);

  if (isLoading) {
    return <p style={R.msgStyle()}>Loading…</p>;
  }
  if (error) {
    return <p style={R.errorMsgStyle()}>Error: {String(error)}</p>;
  }

  return (
    <div style={R.pageStyle(isMobile)}>
      <BeadsFilters
        searchQuery={filters.searchQuery}
        onSearchQuery={filters.setSearchQuery}
        statusFilter={filters.statusFilter}
        onStatusFilter={filters.setStatusFilter}
        total={filters.sorted.length}
        isMobile={isMobile}
      />
      <BeadsTable
        items={filters.pageItems}
        totalPages={filters.totalPages}
        page={filters.page}
        onPage={filters.setPage}
        selectedId={selectedId}
        onSelect={setSelectedId}
        isMobile={isMobile}
      />
      {selectedId && <BeadDrawer beadId={selectedId} onClose={() => setSelectedId(null)} />}
    </div>
  );
}
