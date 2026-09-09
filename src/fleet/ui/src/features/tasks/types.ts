/**
 * Props shared by the task row (desktop) and the task card (mobile).
 * One interface for one concept: both render the same task with the
 * same kill-flow callbacks. Called by TasksPage via TaskRow/TaskCard.
 */
import type { TaskSummary } from '../../shared/types';

export interface TaskItemProps {
  task: TaskSummary;
  confirmingId: string | null;
  stoppingIds: Set<string>;
  onKillClick: (id: string) => void;
  onKillConfirm: (id: string) => void;
  onKillCancel: () => void;
  onRowClick: (id: string) => void;
}
