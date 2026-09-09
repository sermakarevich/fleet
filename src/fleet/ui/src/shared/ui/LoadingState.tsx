// Shared loading placeholder: one look for every page.
// Rendered by DataList while loading and by pages awaiting queries.
import * as R from '../styles/recipes';

export function LoadingState({ message = 'Loading…' }: { message?: string }) {
  return <p style={R.msgStyle()}>{message}</p>;
}
