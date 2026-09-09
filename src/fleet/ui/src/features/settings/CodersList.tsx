// Installed-coders list for the settings page: name, context window
// and default model per coder from useCoders(). Rendered by SettingsPage
// right after the coders-models section.
import type { CoderInfo } from '../../shared/types';
import { formatKiloTokens } from '../../shared/format';
import * as T from '../../shared/styles/tokens';
import { EmptyState } from '../../shared/ui/EmptyState';

export function CodersList({ coders }: { coders: CoderInfo[] }) {
  return (
    <section style={styles.card} aria-label="Installed coders">
      <h3 style={styles.title}>Installed coders</h3>
      {coders.length === 0 ? (
        <EmptyState message="No coders registered." />
      ) : (
        <ul style={styles.list}>
          {coders.map(c => (
            <li key={c.name} style={styles.item}>
              <strong>{c.name}</strong>
              <span style={styles.meta}>
                {formatKiloTokens(c.context_limit)} ctx — {c.default_model}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

const styles = {
  card: {
    ...T.panel,
    padding: '1rem 1.25rem',
  } as React.CSSProperties,
  title: {
    margin: '0 0 0.75rem',
    fontSize: '0.9375rem',
    fontWeight: 600,
    color: T.colors.textPrimary,
  } as React.CSSProperties,
  list: {
    margin: 0,
    padding: 0,
    listStyle: 'none',
    display: 'flex',
    flexDirection: 'column' as const,
    gap: '0.375rem',
  } as React.CSSProperties,
  item: {
    padding: '0.3rem 0.6rem',
    background: T.colors.bgDeep,
    border: `1px solid ${T.colors.borderSubtle}`,
    borderRadius: '0.25rem',
    color: T.colors.textSecondary,
    fontSize: '0.8125rem',
    fontFamily: 'monospace',
  } as React.CSSProperties,
  meta: {
    color: T.colors.textDim,
    marginLeft: '0.5rem',
  } as React.CSSProperties,
};
