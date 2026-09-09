// Per-bead cell renderers for the shared DataList: desktop column
// definitions plus the mobile card body. Rendered by BeadsPage via
// DataList (selection highlight comes from DataList's selectedKey).
import type { Bead } from '../../shared/types';
import * as R from '../../shared/styles/recipes';
import { StatusChip } from '../../shared/ui/StatusChip';
import type { DataColumn } from '../../shared/ui/DataList';

// Dim placeholder for missing values.
function Dim({ children }: { children: React.ReactNode }) {
  return <span style={R.dimStyle()}>{children}</span>;
}

function depLabel(bead: Bead): string {
  const depCount = bead.dependency_count ?? 0;
  return depCount > 0 ? `${depCount} dep${depCount === 1 ? '' : 's'}` : '—';
}

// Desktop columns for the beads DataList.
export function beadColumns(): Array<DataColumn<Bead>> {
  return [
    {
      key: 'status', header: 'Status', width: '6rem',
      render: (bead) => <StatusChip status={bead.status} width="6rem" />,
    },
    {
      key: 'id', header: 'ID', width: '6rem',
      render: (bead) => <span style={R.idCellStyle()}>{bead.id}</span>,
    },
    {
      key: 'title', header: 'Title',
      render: (bead) => <span style={R.titleCellStyle()} title={bead.title}>{bead.title}</span>,
    },
    {
      key: 'pri', header: 'Pri', width: '3rem',
      render: (bead) => (
        <span style={R.merge(R.mutedStyle(), { textAlign: 'center' })}>
          {bead.priority != null ? bead.priority : <Dim>—</Dim>}
        </span>
      ),
    },
    {
      key: 'assignee', header: 'Assignee', width: '8rem',
      render: (bead) => (
        <span style={R.cardFieldStyle()}>
          <span style={R.cardTitleStyle()} title={bead.assignee ?? undefined}>
            {bead.assignee ?? <Dim>—</Dim>}
          </span>
        </span>
      ),
    },
    {
      key: 'deps', header: 'Deps', width: '5rem',
      render: (bead) => <span style={R.mutedStyle()}>{depLabel(bead)}</span>,
    },
  ];
}

// Mobile card body for one bead (DataList wraps it in the card shell).
export function BeadCard({ bead }: { bead: Bead }) {
  const depCount = bead.dependency_count ?? 0;
  return (
    <>
      <div style={R.cardHeadStyle()}>
        <StatusChip status={bead.status} width="6rem" />
        <span style={R.cardIdStyle()}>{bead.id}</span>
        {bead.assignee && <span style={R.cardMetaTextStyle()}>{bead.assignee}</span>}
      </div>
      <div style={R.cardTitleStyle()} title={bead.title}>{bead.title}</div>
      <div style={R.cardMetaStyle()}>
        {bead.priority != null && <span style={R.cardMetaTextStyle()}>pri {bead.priority}</span>}
        {depCount > 0 && (
          <span style={R.cardMetaTextStyle()}>{depCount} dep{depCount === 1 ? '' : 's'}</span>
        )}
      </div>
    </>
  );
}
