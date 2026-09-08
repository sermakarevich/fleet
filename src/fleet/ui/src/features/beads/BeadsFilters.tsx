/**
 * Search box plus status filter buttons for the beads page.
 * Called by BeadsPage; state lives in useBeadFilters.
 */
import * as R from '../../shared/styles/recipes';
import { BEAD_FILTERS, type BeadStatusFilter } from './useBeadFilters';

interface Props {
  searchQuery: string;
  onSearchQuery: (q: string) => void;
  statusFilter: BeadStatusFilter;
  onStatusFilter: (s: BeadStatusFilter) => void;
  total: number;
  isMobile: boolean;
}

// Heading, search input and status filter row.
export function BeadsFilters({ searchQuery, onSearchQuery, statusFilter, onStatusFilter, total, isMobile }: Props) {
  return (
    <div style={R.topBarStyle()}>
      <h1 style={R.headingStyle()}>
        beads <span style={R.countStyle()}>({total})</span>
      </h1>
      <input
        type="search"
        style={R.searchInputStyle(isMobile ? '100%' : '15rem')}
        placeholder="Search id, title, assignee…"
        value={searchQuery}
        onChange={(e) => onSearchQuery(e.target.value)}
      />
      <div style={R.filterRowStyle()}>
        {BEAD_FILTERS.map(({ key, label }) => (
          <button key={key} style={R.filterBtnStyle(statusFilter === key)} onClick={() => onStatusFilter(key)}>
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}
