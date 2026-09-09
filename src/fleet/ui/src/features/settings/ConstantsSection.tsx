// Read-only table of code-level tunables from GET /api/config/constants
// (ADR 0009 Settings): searchable by name, doc or module. Rendered by
// SettingsPage as the constants section.
import { useState } from 'react';
import { useConfigConstants } from '../../shared/hooks/useApi';
import * as T from '../../shared/styles/tokens';
import { EmptyState } from '../../shared/ui/EmptyState';
import { LoadingState } from '../../shared/ui/LoadingState';
import { SettingText } from './fields';

export function ConstantsSection() {
  const { data, isLoading } = useConfigConstants();
  const [query, setQuery] = useState('');

  const rows = (data?.constants ?? []).filter(row => {
    const q = query.trim().toLowerCase();
    if (!q) return true;
    return (
      row.name.toLowerCase().includes(q) ||
      row.doc.toLowerCase().includes(q) ||
      row.module.toLowerCase().includes(q)
    );
  });

  return (
    <section id="settings-constants" style={styles.card} aria-label="Constants">
      <h3 style={styles.title}>Constants</h3>
      <p style={styles.blurb}>
        Read-only code tunables with docs. They are not editable here.
      </p>
      <div style={styles.search}>
        <SettingText value={query} placeholder="Search name, doc or module…" onChange={setQuery} />
      </div>
      {isLoading ? (
        <LoadingState />
      ) : rows.length === 0 ? (
        <EmptyState message={query ? 'No constants match that search.' : 'No constants reported.'} />
      ) : (
        <div style={styles.tableWrap}>
          <table style={styles.table}>
            <thead>
              <tr>
                <th style={styles.th}>Name</th>
                <th style={styles.th}>Value</th>
                <th style={styles.th}>Unit</th>
                <th style={styles.th}>Doc</th>
                <th style={styles.th}>Module</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(row => (
                <tr key={row.name}>
                  <td style={styles.name}>{row.name}</td>
                  <td style={styles.value}>{row.value}</td>
                  <td style={styles.dim}>{row.unit || '—'}</td>
                  <td style={styles.dim}>{row.doc}</td>
                  <td style={styles.dim}>{row.module}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

const styles = {
  card: {
    ...T.panel,
    padding: '1rem 1.25rem',
    scrollMarginTop: '3.5rem',
  } as React.CSSProperties,
  title: {
    margin: '0 0 0.25rem',
    fontSize: '0.9375rem',
    fontWeight: 600,
    color: T.colors.textPrimary,
  } as React.CSSProperties,
  blurb: {
    margin: '0 0 0.875rem',
    fontSize: '0.8125rem',
    color: T.colors.textMuted,
  } as React.CSSProperties,
  search: {
    marginBottom: '0.75rem',
    maxWidth: '24rem',
  } as React.CSSProperties,
  tableWrap: {
    overflowX: 'auto' as const,
  } as React.CSSProperties,
  table: {
    width: '100%',
    borderCollapse: 'collapse' as const,
    fontSize: '0.8125rem',
  } as React.CSSProperties,
  th: {
    textAlign: 'left' as const,
    color: T.colors.textMuted,
    fontWeight: 600,
    fontSize: '0.6875rem',
    textTransform: 'uppercase' as const,
    letterSpacing: '0.06em',
    padding: '0.375rem 0.5rem',
    borderBottom: `1px solid ${T.colors.borderSubtle}`,
    whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  name: {
    color: T.colors.textPrimary,
    fontFamily: 'monospace',
    padding: '0.375rem 0.5rem',
    whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  value: {
    color: T.colors.textSecondary,
    fontFamily: 'monospace',
    padding: '0.375rem 0.5rem',
    whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  dim: {
    color: T.colors.textDim,
    padding: '0.375rem 0.5rem',
  } as React.CSSProperties,
};
