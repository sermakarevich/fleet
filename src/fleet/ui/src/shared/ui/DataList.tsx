// Shared list: table on desktop, cards on mobile (via useIsMobile).
// Rendered by every list page (workers, schedules, workflows,
// runs, inbox); per-feature cell renderers plug in as column `render`
// functions, and rows needing actions pass a custom `renderCard`.
// Replaces the per-feature Table/Row/Card shells.
import type { ReactNode } from 'react';
import { useIsMobile } from '../hooks/useIsMobile';
import * as R from '../styles/recipes';
import { useClickableProps } from './Clickable';
import { EmptyState } from './EmptyState';
import { LoadingState } from './LoadingState';

export interface DataColumn<T> {
  key: string;
  header: ReactNode;
  /**
   * Fixed column width (rem); omit for the fill column. Use `'auto'` for a
   * content-sized column (e.g. action buttons) that must never clip.
   */
  width?: string;
  render: (row: T) => ReactNode;
}

interface DataListProps<T> {
  columns: Array<DataColumn<T>>;
  rows: T[];
  rowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
  /** Mobile card; defaults to a card built from the columns. */
  renderCard?: (row: T) => ReactNode;
  /** Shown when rows is empty and not loading. */
  empty: ReactNode;
  loading?: boolean;
  loadingMessage?: string;
  /** Highlighted row key (drawer selection). */
  selectedKey?: string | null;
  /** Override for tests; defaults to useIsMobile(). */
  isMobile?: boolean;
}

// Desktop table row built from the column definitions. The row never
// shrinks below listMinWidth: on narrow windows the scroll wrapper takes
// over instead of squeezing (and clipping) fixed columns.
function DataRow<T>({
  columns,
  row,
  selected,
  onRowClick,
  minWidth,
}: {
  columns: Array<DataColumn<T>>;
  row: T;
  selected: boolean;
  onRowClick?: (row: T) => void;
  minWidth: string;
}) {
  const click = useClickableProps(onRowClick ? () => onRowClick(row) : () => {});
  return (
    <div style={R.merge(R.rowStyle(selected), { minWidth })} className="row-interactive" {...click}>
      {columns.map((col) => (
        <span key={col.key} style={R.dataCellStyle(col.width)}>
          {col.render(row)}
        </span>
      ))}
    </div>
  );
}

// Default mobile card: one label/value line per column.
function DefaultCard<T>({ columns, row }: { columns: Array<DataColumn<T>>; row: T }) {
  return (
    <>
      {columns.map((col) => (
        <div key={col.key} style={R.cardFieldStyle()}>
          <span style={R.cardFieldLabelStyle()}>{col.header}</span>
          <span style={R.cardTitleStyle()}>{col.render(row)}</span>
        </div>
      ))}
    </>
  );
}

export function DataList<T>({
  columns,
  rows,
  rowKey,
  onRowClick,
  renderCard,
  empty,
  loading = false,
  loadingMessage,
  selectedKey = null,
  isMobile: mobileOverride,
}: DataListProps<T>) {
  const autoMobile = useIsMobile();
  const isMobile = mobileOverride ?? autoMobile;
  // Shared floor for header + rows so fixed columns never squeeze; the
  // scroll wrapper takes over below this width.
  const minWidth = R.listMinWidth(columns);

  if (loading && rows.length === 0) {
    return (
      <div style={R.panelStyle()}>
        <LoadingState message={loadingMessage} />
      </div>
    );
  }

  return (
    <div style={R.panelStyle()}>
      <div style={R.listScrollStyle()}>
        {!isMobile && (
          <div style={R.merge(R.colHeaderStyle(), { minWidth })}>
            {columns.map((col) => (
              <span key={col.key} style={R.dataCellStyle(col.width)}>
                {col.header}
              </span>
            ))}
          </div>
        )}
        {rows.length === 0 ? (
          <EmptyState message={empty} />
        ) : isMobile ? (
          rows.map((row) => {
            const key = rowKey(row);
            const selected = selectedKey === key;
            const body = renderCard ? renderCard(row) : <DefaultCard columns={columns} row={row} />;
            if (!onRowClick) return <div key={key} style={R.cardStyle(selected)}>{body}</div>;
            return (
              <CardWrap key={key} row={row} selected={selected} onRowClick={onRowClick}>
                {body}
              </CardWrap>
            );
          })
        ) : (
          rows.map((row) => (
            <DataRow
              key={rowKey(row)}
              columns={columns}
              row={row}
              selected={selectedKey === rowKey(row)}
              onRowClick={onRowClick}
              minWidth={minWidth}
            />
          ))
        )}
      </div>
    </div>
  );
}

// Clickable mobile card wrapper (hooks cannot live in renderCard).
function CardWrap<T>({
  row,
  selected,
  onRowClick,
  children,
}: {
  row: T;
  selected: boolean;
  onRowClick: (row: T) => void;
  children: ReactNode;
}) {
  const click = useClickableProps(() => onRowClick(row));
  return (
    <div style={R.cardStyle(selected)} className="row-interactive" {...click}>
      {children}
    </div>
  );
}
