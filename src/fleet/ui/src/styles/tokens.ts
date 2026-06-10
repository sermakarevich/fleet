import type { CSSProperties } from 'react';

export const colors = {
  bgDeep:        '#09090b',
  bgSurface:     '#18181b',
  bgElevated:    '#1c1c20',
  borderSubtle:  '#27272a',
  border:        '#3f3f46',
  accent:        '#3b82f6',
  textPrimary:   '#e4e4e7',
  textSecondary: '#a1a1aa',
  textDim:       '#71717a',
  textMuted:     '#52525b',
  danger:        '#ef4444',
} as const;

export const panel: CSSProperties = {
  background: colors.bgElevated,
  border: `1px solid ${colors.border}`,
  borderRadius: 8,
};

export const badge: CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  padding: '0.15rem 0.5rem',
  borderRadius: 4,
  fontSize: '0.75rem',
  fontWeight: 600,
  boxSizing: 'border-box',
};

export const btnPrimary: CSSProperties = {
  padding: '0.4rem 0.875rem',
  background: colors.accent,
  border: `1px solid ${colors.accent}`,
  borderRadius: 4,
  color: '#fff',
  cursor: 'pointer',
  fontSize: '0.875rem',
  fontWeight: 500,
  fontFamily: 'system-ui, sans-serif',
};

export const btnGhost: CSSProperties = {
  background: 'transparent',
  border: `1px solid ${colors.border}`,
  borderRadius: 4,
  color: colors.textSecondary,
  cursor: 'pointer',
  fontFamily: 'system-ui, sans-serif',
};

export const btnDanger: CSSProperties = {
  background: 'transparent',
  border: `1px solid ${colors.danger}`,
  borderRadius: 4,
  color: colors.danger,
  cursor: 'pointer',
  fontFamily: 'system-ui, sans-serif',
};
