// Render tests for the shared DataList: desktop table, mobile cards
// (explicit and default), row click, empty and loading states.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { DataList, type DataColumn } from './DataList';

afterEach(cleanup);

interface Item {
  id: string;
  title: string;
}

const ROWS: Item[] = [
  { id: 'a', title: 'Alpha' },
  { id: 'b', title: 'Beta' },
];

const COLUMNS: Array<DataColumn<Item>> = [
  { key: 'id', header: 'ID', width: '6rem', render: (row) => row.id },
  { key: 'title', header: 'Title', render: (row) => row.title },
];

function renderList(override: Partial<Parameters<typeof DataList<Item>>[0]> = {}) {
  return render(
    <DataList
      columns={COLUMNS}
      rows={ROWS}
      rowKey={(row) => row.id}
      empty="Nothing here."
      isMobile={false}
      {...override}
    />,
  );
}

describe('DataList', () => {
  it('renders a desktop table with headers and rows', () => {
    renderList();
    expect(screen.getByText('ID')).toBeInTheDocument();
    expect(screen.getByText('Title')).toBeInTheDocument();
    expect(screen.getByText('Alpha')).toBeInTheDocument();
    expect(screen.getByText('Beta')).toBeInTheDocument();
  });

  it('notifies row clicks', () => {
    const onRowClick = vi.fn();
    renderList({ onRowClick });
    fireEvent.click(screen.getByText('Alpha'));
    expect(onRowClick).toHaveBeenCalledWith(ROWS[0]);
  });

  it('renders mobile cards with a custom renderCard', () => {
    renderList({ isMobile: true, renderCard: (row) => <span>card:{row.title}</span> });
    expect(screen.getByText('card:Alpha')).toBeInTheDocument();
    expect(screen.getByText('card:Beta')).toBeInTheDocument();
  });

  it('falls back to a default card built from the columns', () => {
    renderList({ isMobile: true });
    expect(screen.getAllByText('Alpha')).toHaveLength(1);
    expect(screen.getAllByText('Title')).toHaveLength(2);
  });

  it('renders the empty state when there are no rows', () => {
    renderList({ rows: [] });
    expect(screen.getByText('Nothing here.')).toBeInTheDocument();
  });

  it('renders the loading state instead of rows', () => {
    renderList({ rows: [], loading: true });
    expect(screen.getByText('Loading…')).toBeInTheDocument();
    expect(screen.queryByText('Nothing here.')).not.toBeInTheDocument();
  });

  it('clips fixed-width cells with overflow hidden', () => {
    const longStr = 'x'.repeat(300);
    const cols: Array<DataColumn<Item>> = [
      { key: 'id', header: 'ID', width: '6rem', render: (row) => row.id },
      { key: 'title', header: 'Title', width: '8rem', render: () => longStr },
    ];
    render(
      <DataList
        columns={cols}
        rows={[{ id: 'a', title: 'Alpha' }]}
        rowKey={(row) => row.id}
        empty="Nothing here."
        isMobile={false}
      />,
    );
    const cell = screen.getByText(longStr);
    // The text renders directly inside the fixed-width cell wrapper, so
    // the wrapper itself carries the clipping style.
    expect(cell.style.overflow).toBe('hidden');
    expect(cell.style.width).toBe('8rem');
  });

  it('sizes content columns to their content without clipping', () => {
    const cols: Array<DataColumn<Item>> = [
      { key: 'id', header: 'ID', width: '6rem', render: (row) => row.id },
      { key: 'actions', header: '', width: 'auto', render: () => <span>action-buttons</span> },
    ];
    render(
      <DataList
        columns={cols}
        rows={[{ id: 'a', title: 'Alpha' }]}
        rowKey={(row) => row.id}
        empty="Nothing here."
        isMobile={false}
      />,
    );
    const cell = screen.getByText('action-buttons').parentElement;
    expect(cell?.style.flex).toBe('0 0 auto');
    expect(cell?.style.overflow).not.toBe('hidden');
  });

  it('scrolls header and rows together inside the panel', () => {
    const { container } = renderList();
    const panel = container.firstElementChild as HTMLElement;
    const scroller = panel.firstElementChild as HTMLElement;
    // The panel keeps its rounded corners; the inner wrapper scrolls.
    expect(panel.style.overflow).toBe('hidden');
    expect(scroller.style.overflowX).toBe('auto');
    // Header and rows share one min width so columns stay aligned and
    // fixed columns never squeeze into clipping.
    const header = scroller.firstElementChild as HTMLElement;
    expect(header.style.minWidth).not.toBe('');
    const row = scroller.children[1] as HTMLElement;
    expect(row.style.minWidth).toBe(header.style.minWidth);
  });
});
