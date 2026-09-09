import type { CSSProperties } from 'react';
import * as T from '../../shared/styles/tokens';

/** Shared look for every analytics section so the page reads as one dashboard. */

export const panel: CSSProperties = {
  ...T.panel,
  padding: '0.75rem 1rem',
  minWidth: 0,
};

export const panelTitle: CSSProperties = {
  fontSize: '0.6875rem',
  fontWeight: 600,
  textTransform: 'uppercase',
  letterSpacing: '0.05em',
  color: T.colors.textMuted,
  marginBottom: '0.5rem',
  display: 'flex',
  alignItems: 'baseline',
  justifyContent: 'space-between',
  gap: '0.5rem',
};

export const panelTitleAside: CSSProperties = {
  fontWeight: 400,
  textTransform: 'none',
  letterSpacing: 'normal',
  color: T.colors.textDim,
};

export const panelEmpty: CSSProperties = {
  fontSize: '0.8125rem',
  color: T.colors.textDim,
  padding: '1.5rem 0',
  textAlign: 'center',
  margin: 0,
};

/** Chart series colors, CVD-validated against the dark panel surface. */
export const seriesColors = {
  // status trio for task outcomes
  success: T.colors.tickGreen,
  failed: T.colors.redBrick,
  blocked: T.colors.amberGold,
  // categorical pair + third slot for token series
  output: T.colors.chartBlue,
  input: T.colors.ember,
  cache: T.colors.teal,
} as const;

export const chartAxisTick = { fill: T.colors.textDim, fontSize: 11 };

export const chartGridStroke = T.colors.borderSubtle;

export const chartTooltipProps = {
  contentStyle: {
    background: T.colors.bgSurface,
    border: `1px solid ${T.colors.border}`,
    borderRadius: 6,
    fontSize: 12,
  },
  labelStyle: { color: T.colors.textPrimary },
  itemStyle: { color: T.colors.textSecondary, padding: '0 0.125rem' },
  cursor: { fill: 'rgba(255,255,255,0.05)' },
} as const;
