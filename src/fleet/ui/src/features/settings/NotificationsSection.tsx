// Browser-notification toggles for the settings page: local browser
// state only, never sent to the server. Rendered by SettingsPage as the
// notifications section.
import { useNativeNotifications } from '../../shared/hooks/useNativeNotifications';
import * as T from '../../shared/styles/tokens';

export function NotificationsSection() {
  const { permissions, setPermission } = useNativeNotifications();

  return (
    <section id="settings-notifications" style={styles.card} aria-label="Browser notifications">
      <h3 style={styles.title}>Browser notifications</h3>
      <p style={styles.blurb}>Local toggles; stored in this browser only (requires permission).</p>
      <div style={styles.row}>
        <label style={styles.label}>
          <input
            type="checkbox"
            checked={permissions.ask_human}
            onChange={e => setPermission('ask_human', e.target.checked)}
            style={styles.checkbox}
          />
          Inbox questions
        </label>
      </div>
      <div style={styles.row}>
        <label style={styles.label}>
          <input
            type="checkbox"
            checked={permissions.completed}
            onChange={e => setPermission('completed', e.target.checked)}
            style={styles.checkbox}
          />
          Task completions
        </label>
      </div>
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
  row: {
    marginBottom: '0.5rem',
  } as React.CSSProperties,
  label: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.5rem',
    color: T.colors.textSecondary,
    fontSize: '0.875rem',
    cursor: 'pointer',
  } as React.CSSProperties,
  checkbox: {
    accentColor: T.colors.accent,
    cursor: 'pointer',
  } as React.CSSProperties,
};
