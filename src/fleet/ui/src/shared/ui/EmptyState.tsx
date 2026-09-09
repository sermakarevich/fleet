// Shared empty-list placeholder: one look for every page.
// Rendered by DataList when a list has no rows; pages pass their own
// message ("No tasks match this filter.", "No schedules yet. …").
import * as R from '../styles/recipes';

export function EmptyState({ message }: { message: React.ReactNode }) {
  return <p style={R.emptyStyle()}>{message}</p>;
}
