/**
 * The one status chip used by every table and card.
 * Called by TaskCard, worker columns and anywhere else a status needs
 * a colored label.
 */
import { chipLabel, chipStyle } from '../styles/recipes';

interface Props {
  status: string;
  stopping?: boolean;
  width?: string;
}

// Colored label for a task/bead status.
export function StatusChip({ status, stopping = false, width = '5rem' }: Props) {
  return <span style={chipStyle(status, stopping, width)}>{chipLabel(status, stopping)}</span>;
}
