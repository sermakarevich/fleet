/**
 * Named style recipes shared by every feature page.
 *
 * Built on the tokens in `./tokens` plus the status colors in
 * `../status`. Pages compose these instead of inlining `style={{...}}`
 * blobs; anything page-specific stays in that feature's own styles record.
 * Called by WorkersPage, ChatPage, NewWorkerPanel, LiveTab and
 * the table/chart components.
 */
import type { CSSProperties } from 'react';
import * as T from './tokens';
import { statusColor, statusLabel } from '../status';

// Combine style objects left to right, skipping falsy parts.
export function merge(...parts: Array<CSSProperties | false | null | undefined>): CSSProperties {
  return Object.assign({}, ...parts.filter(Boolean));
}

// Return the style when the condition holds, else nothing for merge().
export function when(cond: boolean, style: CSSProperties): CSSProperties | false {
  return cond ? style : false;
}

// Status chip: label plus a ready-to-use style for StatusChip.
export function chipLabel(status: string, stopping = false): string {
  if (stopping) return 'Stopping…';
  return statusLabel(status || '?');
}

// Status chip style; width varies by table (tasks 5rem, beads 6rem).
export function chipStyle(status: string, stopping = false, width = '5rem'): CSSProperties {
  if (stopping) return { ...T.badge, width, flexShrink: 0, background: T.colors.amberDeep, color: T.colors.white };
  const { bg, fg } = statusColor(status);
  return { ...T.badge, width, flexShrink: 0, background: bg, color: fg };
}

// Small inline status chip for dependency rows and table cells.
export function miniChipStyle(status: string): CSSProperties {
  const { bg, fg } = statusColor(status ?? '');
  return { flexShrink: 0, padding: '0.05rem 0.4rem', borderRadius: '0.25rem', fontSize: '0.7rem', fontWeight: 600, background: bg, color: fg };
}

// Page container; padding shrinks on mobile.
export function pageStyle(isMobile: boolean): CSSProperties {
  return { padding: isMobile ? '0.75rem' : '1rem 1.5rem', fontFamily: 'system-ui, sans-serif' };
}

// Inline loading / error message paragraph.
export function msgStyle(): CSSProperties {
  return { padding: '1rem', color: T.colors.textDim, fontFamily: 'system-ui, sans-serif' };
}

// Same message rendered as an error.
export function errorMsgStyle(): CSSProperties {
  return { ...msgStyle(), color: T.colors.danger };
}

// Top toolbar holding the heading, search box and filter buttons.
export function topBarStyle(): CSSProperties {
  return { display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '0.875rem', flexWrap: 'wrap' };
}

// Page heading with an inline count.
export function headingStyle(): CSSProperties {
  return { margin: 0, fontSize: '0.9375rem', fontWeight: 600, color: T.colors.textPrimary };
}

// Dim count shown next to the heading.
export function countStyle(): CSSProperties {
  return { fontWeight: 400, color: T.colors.textDim, fontSize: '0.875rem' };
}

// Search box; width varies by page.
export function searchInputStyle(width = '13rem'): CSSProperties {
  return {
    padding: '0.2rem 0.625rem', background: T.colors.bgDeep, border: `1px solid ${T.colors.border}`,
    borderRadius: '0.25rem', color: T.colors.textPrimary, fontSize: '0.8125rem',
    fontFamily: 'system-ui, sans-serif', outline: 'none', width,
  };
}

// Row of filter buttons.
export function filterRowStyle(): CSSProperties {
  return { display: 'flex', gap: '0.375rem', flexWrap: 'wrap' };
}

// One filter button, highlighted when active.
export function filterBtnStyle(active: boolean): CSSProperties {
  return {
    ...T.btnGhost, padding: '0.2rem 0.625rem', fontSize: '0.8125rem',
    color: active ? T.colors.white : T.colors.textDim, lineHeight: 1.4,
    ...(active ? { background: T.colors.accent, borderColor: T.colors.accent } : {}),
  };
}

// Table/list panel.
export function panelStyle(): CSSProperties {
  return { ...T.panel, overflow: 'hidden' };
}

// Uppercase column header row.
export function colHeaderStyle(): CSSProperties {
  return {
    display: 'flex', alignItems: 'center', padding: '0.4rem 1rem',
    borderBottom: `1px solid ${T.colors.borderSubtle}`, fontSize: '0.75rem', fontWeight: 600,
    color: T.colors.textDim, textTransform: 'uppercase', letterSpacing: '0.05em', gap: '0.75rem',
  };
}

// Clickable data row, highlighted when selected.
export function rowStyle(selected: boolean): CSSProperties {
  return {
    display: 'flex', alignItems: 'center', padding: '0.5rem 1rem', gap: '0.75rem',
    borderBottom: `1px solid ${T.colors.borderSubtle}`, cursor: 'pointer',
    fontSize: '0.875rem', color: T.colors.textBody,
    ...(selected ? { background: T.colors.borderSubtle } : {}),
  };
}

// Monospace identifier cell (task id, bead id).
export function idCellStyle(width = '6rem'): CSSProperties {
  return {
    width, flexShrink: 0, fontFamily: 'monospace', color: T.colors.link, fontSize: '0.8125rem',
    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
  };
}

// Ellipsized title cell that takes the remaining row width.
export function titleCellStyle(): CSSProperties {
  return { flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' };
}

// Dim placeholder for missing values.
export function dimStyle(): CSSProperties {
  return { color: T.colors.textMuted };
}

// Monospace text (hashes, timestamps, ids).
export function monoStyle(): CSSProperties {
  return { fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace' };
}

// Muted secondary text.
export function mutedStyle(): CSSProperties {
  return { fontSize: '0.8125rem', color: T.colors.textSecondary };
}

// "No rows" placeholder.
export function emptyStyle(): CSSProperties {
  return { padding: '1.5rem 1rem', color: T.colors.textMuted, fontSize: '0.875rem', margin: 0, textAlign: 'center' };
}

// Pagination bar under a table.
export function paginationStyle(): CSSProperties {
  return { display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.75rem', padding: '0.625rem 0', marginTop: '0.5rem' };
}

// Pagination button, dimmed when disabled.
export function pageBtnStyle(disabled: boolean): CSSProperties {
  return { ...T.btnGhost, padding: '0.2rem 0.75rem', fontSize: '0.8125rem', ...(disabled ? { opacity: 0.35, cursor: 'default' } : {}) };
}

// "1 / 5" page indicator.
export function pageInfoStyle(): CSSProperties {
  return { fontSize: '0.8125rem', color: T.colors.textDim, minWidth: '4rem', textAlign: 'center' };
}

// Overlay behind modals and drawers.
export function overlayStyle(): CSSProperties {
  return { position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', display: 'flex', zIndex: 500 };
}

// Right-hand detail drawer shell.
export function drawerStyle(): CSSProperties {
  return {
    width: 'min(34rem, 100%)', height: '100%', background: T.colors.bgSurface,
    borderLeft: `1px solid ${T.colors.border}`, display: 'flex', flexDirection: 'column',
    boxShadow: '-0.5rem 0 1.5rem rgba(0,0,0,0.4)',
  };
}

// Form label stacking a caption over its control.
export function fieldLabelStyle(): CSSProperties {
  return { display: 'flex', flexDirection: 'column', gap: '0.3rem', fontSize: '0.8125rem', color: T.colors.textSecondary };
}

// Text input, select and textarea share one look.
export function inputStyle(): CSSProperties {
  return {
    background: T.colors.bgDeep, border: `1px solid ${T.colors.border}`, borderRadius: '0.25rem',
    color: T.colors.textPrimary, padding: '0.4rem 0.6rem', fontSize: '0.875rem',
    fontFamily: 'system-ui, sans-serif', outline: 'none',
  };
}

// Data cell inside a DataList desktop row: fixed width or flex fill.
export function dataCellStyle(width?: string): CSSProperties {
  return width
    ? { width, flexShrink: 0, minWidth: 0 }
    : { flex: 1, minWidth: 0 };
}

// Mobile card shell shared by every DataList card.
export function cardStyle(selected = false): CSSProperties {
  return {
    padding: '0.625rem 0.875rem', borderBottom: `1px solid ${T.colors.borderSubtle}`,
    cursor: 'pointer', display: 'flex', flexDirection: 'column',
    gap: '0.3rem', fontSize: '0.875rem', color: T.colors.textBody,
    ...(selected ? { background: T.colors.borderSubtle } : {}),
  };
}

// Top line of a card: status chip, id, actions.
export function cardHeadStyle(): CSSProperties {
  return { display: 'flex', alignItems: 'center', gap: '0.5rem' };
}

// Primary card title line, ellipsized.
export function cardTitleStyle(): CSSProperties {
  return { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' };
}

// Muted card metadata row(s).
export function cardMetaStyle(): CSSProperties {
  return { display: 'flex', gap: '0.625rem', flexWrap: 'wrap', alignItems: 'center' };
}

// One muted metadata span inside a card.
export function cardMetaTextStyle(): CSSProperties {
  return { fontSize: '0.75rem', color: T.colors.textSecondary };
}

// Monospace identifier inside a card head.
export function cardIdStyle(): CSSProperties {
  return {
    fontFamily: 'monospace', color: T.colors.link, fontSize: '0.8125rem', flex: 1, minWidth: 0,
    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
  };
}

// Label/value line of the default DataList card.
export function cardFieldStyle(): CSSProperties {
  return { display: 'flex', gap: '0.5rem', fontSize: '0.8125rem', minWidth: 0 };
}

// Dim field label inside the default DataList card.
export function cardFieldLabelStyle(): CSSProperties {
  return { color: T.colors.textDim, flexShrink: 0, minWidth: '4.5rem' };
}

// Red dot marking a filter button with waiting items.
export function alertDotStyle(): CSSProperties {
  return {
    display: 'inline-block', width: '0.4375rem', height: '0.4375rem',
    borderRadius: '50%', background: T.colors.danger, flexShrink: 0,
  };
}

// Inner layout of a filter button (label + optional dot/count).
export function filterBtnInnerStyle(): CSSProperties {
  return { display: 'inline-flex', alignItems: 'center', gap: '0.3rem' };
}

// Count badge inside a filter button.
export function filterCountStyle(): CSSProperties {
  return {
    display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
    padding: '0 0.375rem', borderRadius: '9999px', fontSize: '0.7rem',
    fontWeight: 700, background: T.colors.border, color: T.colors.textPrimary,
  };
}

// Inline confirm row ("<Verb>?" + Confirm/Cancel), used by Confirm.
export function confirmStyle(): CSSProperties {
  return { display: 'inline-flex', alignItems: 'center', gap: '0.375rem' };
}

// The "<Verb>?" label of an inline confirm.
export function confirmLabelStyle(): CSSProperties {
  return { fontSize: '0.8125rem', color: T.colors.textSecondary, whiteSpace: 'nowrap' };
}

// Danger-tinted confirm button (Confirm in a destructive Confirm).
export function confirmBtnStyle(): CSSProperties {
  return {
    padding: '0.2rem 0.5rem', background: T.colors.danger,
    border: `1px solid ${T.colors.danger}`, borderRadius: '0.25rem', color: T.colors.white,
    cursor: 'pointer', fontSize: '0.8125rem', fontFamily: 'system-ui, sans-serif',
    fontWeight: 600,
  };
}

// Alternating table row background for readability.
export function altRowStyle(index: number): CSSProperties {
  return { background: index % 2 === 0 ? 'transparent' : T.colors.bgElevated };
}

// Diff line background/text per change kind.
export const DIFF_LINE_STYLE: Record<'equal' | 'remove' | 'add', CSSProperties> = {
  equal: { background: 'transparent', color: T.colors.textDim },
  remove: { background: T.colors.diffRemoveBg, color: T.colors.diffRemoveFg },
  add: { background: T.colors.diffAddBg, color: T.colors.diffAddFg },
};
