import type { CSSProperties } from 'react';

export const colors = {
  bgDeep:        '#09090b',
  bgDeeper:      '#0f0f12',
  bgWarm:        '#1c1917',
  bgSurface:     '#18181b',
  bgElevated:    '#1c1c20',
  borderSubtle:  '#27272a',
  border:        '#3f3f46',
  accent:        '#3b82f6',
  textPrimary:   '#e4e4e7',
  textBody:      '#d4d4d8',
  textBright:    '#f4f4f5',
  textSecondary: '#a1a1aa',
  textDim:       '#71717a',
  textMuted:     '#52525b',
  white:         '#fff',
  danger:        '#ef4444',
  dangerWash:    '#ef444410',
  success:       '#22c55e',
  warningBg:     '#854d0e',
  warningFg:     '#fef08a',
  // Links and informational blues.
  link:          '#60a5fa',
  linkLight:     '#93c5fd',
  info:          '#2563eb',
  infoDark:      '#1d4ed8',
  chartBlue:     '#3987e5',
  // Ambers, yellows and oranges (warnings, blocked states, notes).
  amber:         '#f59e0b',
  amberLight:    '#fbbf24',
  amberGold:     '#fab219',
  yellow:        '#eab308',
  amberDark:     '#d97706',
  amberDeep:     '#92400e',
  noteBg:        '#2a1d05',
  noteBgAlt:     '#2a2310',
  noteFg:        '#fcd9a0',
  orange:        '#fb923c',
  clay:          '#ec835a',
  clayWash:      '#ec835a22',
  ember:         '#d95926',
  // Greens (success, charts, diff additions).
  green:         '#16a34a',
  greenDark:     '#14532d',
  diffAddBg:     '#0f2e18',
  diffAddFg:     '#4ade80',
  mintPale:      '#bbf7d0',
  tickGreen:     '#0ca30c',
  teal:          '#199e70',
  // Reds (failures, diff removals).
  redDark:       '#dc2626',
  redBrick:      '#d03b3b',
  redDeep:       '#991b1b',
  maroon:        '#7f1d1d',
  diffRemoveBg:  '#3f1010',
  diffRemoveFg:  '#f87171',
  roseLight:     '#fca5a5',
  // Violets and purples (event kinds, job pills).
  violet:        '#8b5cf6',
  purple:        '#a855f7',
  purpleDark:    '#7c3aed',
  lavender:      '#a78bfa',
  lavenderPale:  '#ede9fe',
  periwinkle:    '#818cf8',
  indigo:        '#6366f1',
  // Slates and grays.
  slateLight:    '#94a3b8',
  grayLight:     '#9ca3af',
  gray:          '#6b7280',
  slateDark:     '#374151',
  stone:         '#a8a29e',
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
