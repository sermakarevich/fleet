// Shared filter bar: search input plus status filter buttons with
// optional alert dots and counts. Rendered by every list page; state
// lives in useUrlFilters (or a feature hook built on it) so filters
// stay in the URL. Alert dots reuse the tasks-page idiom.
import * as R from '../styles/recipes';

export interface FilterOption<T extends string> {
  key: T;
  label: string;
  /** Items waiting under this filter; shows a red dot when > 0. */
  alertCount?: number;
  /** Total rendered as a count badge next to the label. */
  count?: number;
}

interface FilterBarProps<T extends string> {
  searchQuery: string;
  onSearchQuery: (q: string) => void;
  searchPlaceholder?: string;
  searchWidth?: string;
  filters: Array<FilterOption<T>>;
  active: T;
  onSelect: (key: T) => void;
}

export function FilterBar<T extends string>({
  searchQuery,
  onSearchQuery,
  searchPlaceholder = 'Search…',
  searchWidth = '13rem',
  filters,
  active,
  onSelect,
}: FilterBarProps<T>) {
  return (
    <>
      <input
        type="search"
        style={R.searchInputStyle(searchWidth)}
        placeholder={searchPlaceholder}
        value={searchQuery}
        onChange={(e) => onSearchQuery(e.target.value)}
      />
      <div style={R.filterRowStyle()}>
        {filters.map(({ key, label, alertCount, count }) => (
          <button key={key} style={R.filterBtnStyle(active === key)} onClick={() => onSelect(key)}>
            <span style={R.filterBtnInnerStyle()}>
              {label}
              {count != null && <span style={R.filterCountStyle()}>{count}</span>}
              {(alertCount ?? 0) > 0 && <span style={R.alertDotStyle()} />}
            </span>
          </button>
        ))}
      </div>
    </>
  );
}
