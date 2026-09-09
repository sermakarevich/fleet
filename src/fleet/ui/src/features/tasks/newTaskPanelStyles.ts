/**
 * Panel-specific styles for the new-task modal.
 * Generic field/input recipes live in shared/styles/recipes.ts;
 * this module keeps what only NewTaskPanel uses.
 * Called by NewTaskPanel.
 */
import * as T from '../../shared/styles/tokens';

export const styles = {
  panel: {
    ...T.panel, width: '100%', maxWidth: '36rem',
    maxHeight: 'calc(100vh - 8rem)', overflowY: 'auto', fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
  header: {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    padding: '1rem 1.25rem 0.75rem', borderBottom: `1px solid ${T.colors.borderSubtle}`,
  } as React.CSSProperties,
  heading: {
    margin: 0, fontSize: '0.9375rem', fontWeight: 600, color: T.colors.textPrimary,
  } as React.CSSProperties,
  closeBtn: {
    background: 'none', border: 'none', color: T.colors.textDim,
    cursor: 'pointer', fontSize: '1.25rem', lineHeight: 1, padding: '0 0.25rem',
  } as React.CSSProperties,
  form: {
    padding: '1rem 1.25rem', display: 'flex',
    flexDirection: 'column' as const, gap: '0.875rem',
  } as React.CSSProperties,
  label: {
    display: 'flex', flexDirection: 'column' as const, gap: '0.3rem',
    fontSize: '0.8125rem', color: T.colors.textSecondary,
  } as React.CSSProperties,
  grow: { flex: 1 } as React.CSSProperties,
  prio: { width: '6rem' } as React.CSSProperties,
  input: {
    background: T.colors.bgDeep, border: `1px solid ${T.colors.border}`, borderRadius: 4,
    color: T.colors.textPrimary, padding: '0.4rem 0.6rem', fontSize: '0.875rem',
    fontFamily: 'system-ui, sans-serif', outline: 'none',
  } as React.CSSProperties,
  inputError: {
    borderColor: T.colors.danger,
  } as React.CSSProperties,
  textarea: {
    fontFamily: 'monospace', resize: 'vertical' as const,
  } as React.CSSProperties,
  multiSelect: {
    fontFamily: 'monospace', padding: '0.25rem', fontSize: '0.8125rem',
    minHeight: '5rem', maxHeight: '8rem',
  } as React.CSSProperties,
  hint: {
    fontSize: '0.6875rem', color: T.colors.textDim,
  } as React.CSSProperties,
  row: {
    display: 'flex', gap: '0.75rem',
  } as React.CSSProperties,
  templateSection: {
    borderTop: `1px solid ${T.colors.borderSubtle}`, paddingTop: '0.75rem',
  } as React.CSSProperties,
  templateLabel: {
    margin: '0 0 0.5rem', fontSize: '0.75rem', color: T.colors.textDim,
    textTransform: 'uppercase' as const, letterSpacing: '0.05em',
  } as React.CSSProperties,
  templateList: {
    display: 'flex', flexWrap: 'wrap' as const, gap: '0.375rem',
  } as React.CSSProperties,
  templateBtn: {
    ...T.btnGhost, padding: '0.25rem 0.625rem',
    background: T.colors.borderSubtle, fontSize: '0.8125rem',
  } as React.CSSProperties,
  actions: {
    display: 'flex', justifyContent: 'flex-end', alignItems: 'center',
    gap: '0.75rem', paddingTop: '0.5rem', borderTop: `1px solid ${T.colors.borderSubtle}`,
  } as React.CSSProperties,
  errorMsg: {
    color: T.colors.danger, fontSize: '0.75rem', flex: 1,
  } as React.CSSProperties,
  cancelBtn: {
    ...T.btnGhost, padding: '0.4rem 0.875rem', fontSize: '0.875rem',
  } as React.CSSProperties,
  submitBtn: {
    ...T.btnPrimary,
  } as React.CSSProperties,
};
