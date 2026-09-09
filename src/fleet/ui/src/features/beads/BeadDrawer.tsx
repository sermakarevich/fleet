/**
 * Slide-over detail view for one bead: status, manage controls,
 * blocked reason, description, dependencies and comments.
 * Called by BeadsPage when a row is selected.
 */
import { useBead } from '../../shared/hooks/useApi';
import * as T from '../../shared/styles/tokens';
import * as R from '../../shared/styles/recipes';
import { Modal } from '../../shared/ui/Modal';
import { StatusChip } from '../../shared/ui/StatusChip';
import { BeadActions } from './BeadActions';

// Section heading inside the drawer.
function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h3 style={styles.sectionTitle}>{children}</h3>;
}

// Drawer showing the full detail of one bead.
export function BeadDrawer({ beadId, onClose }: { beadId: string; onClose: () => void }) {
  const { data: bead, isLoading, error } = useBead(beadId);
  const incompleteDeps = (bead?.dependencies ?? []).filter((d) => d.status !== 'closed');

  return (
    <Modal labelledBy="bead-drawer-title" onClose={onClose} placement="right" panelStyle={R.drawerStyle()}>
        <div style={styles.header}>
          <span id="bead-drawer-title" style={styles.id}>{beadId}</span>
          <button style={styles.closeBtn} onClick={onClose} title="Close" aria-label="Close">✕</button>
        </div>

        {isLoading && <p style={R.msgStyle()}>Loading…</p>}
        {error && <p style={R.errorMsgStyle()}>Error: {String(error)}</p>}

        {bead && (
          <div style={styles.body}>
            <h2 style={styles.title}>{bead.title}</h2>

            <div style={styles.metaRow}>
              <StatusChip status={bead.status} width="6rem" />
              {bead.priority != null && <span style={styles.metaPill}>priority {bead.priority}</span>}
              {bead.issue_type && <span style={styles.metaPill}>{bead.issue_type}</span>}
              <span style={styles.metaPill}>assignee: {bead.assignee ?? '—'}</span>
            </div>

            <BeadActions bead={bead} />

            {bead.status === 'blocked' && (
              <section style={styles.section}>
                <SectionTitle>Why blocked</SectionTitle>
                {bead.notes && <pre style={styles.notes}>{bead.notes}</pre>}
                {incompleteDeps.length > 0 && (
                  <div style={styles.depList}>
                    <span style={R.dimStyle()}>
                      Waiting on {incompleteDeps.length} open dependenc{incompleteDeps.length === 1 ? 'y' : 'ies'}:
                    </span>
                    {incompleteDeps.map((d) => (
                      <div key={d.id} style={styles.depItem}>
                        <span style={styles.depId}>{d.id}</span>
                        <span style={styles.depTitle} title={d.title ?? undefined}>{d.title ?? ''}</span>
                        <span style={R.miniChipStyle(d.status ?? '')}>{d.status ?? '?'}</span>
                      </div>
                    ))}
                  </div>
                )}
                {!bead.notes && incompleteDeps.length === 0 && (
                  <p style={R.dimStyle()}>No recorded reason — blocked manually. Use Unblock to reopen.</p>
                )}
              </section>
            )}

            <section style={styles.section}>
              <SectionTitle>Description</SectionTitle>
              {bead.description
                ? <pre style={styles.desc}>{bead.description}</pre>
                : <p style={R.dimStyle()}>No description.</p>}
            </section>

            <section style={styles.section}>
              <SectionTitle>Dependencies ({bead.dependencies.length})</SectionTitle>
              {bead.dependencies.length === 0
                ? <p style={R.dimStyle()}>None.</p>
                : bead.dependencies.map((d) => (
                  <div key={d.id} style={styles.depItem}>
                    <span style={styles.depId}>{d.id}</span>
                    <span style={styles.depTitle} title={d.title ?? undefined}>{d.title ?? ''}</span>
                    <span style={R.miniChipStyle(d.status ?? '')}>{d.status ?? '?'}</span>
                    {d.dependency_type && <span style={styles.depType}>{d.dependency_type}</span>}
                  </div>
                ))}
            </section>

            <section style={styles.section}>
              <SectionTitle>Comments ({bead.comments.length})</SectionTitle>
              {bead.comments.length === 0
                ? <p style={R.dimStyle()}>None.</p>
                : bead.comments.map((c, i) => (
                  <div key={c.id ?? i} style={styles.comment}>
                    <div style={styles.commentMeta}>
                      <span style={styles.commentAuthor}>{c.author ?? 'unknown'}</span>
                      {c.created_at && <span style={R.dimStyle()}>{c.created_at}</span>}
                    </div>
                    <div style={styles.commentText}>{c.text}</div>
                  </div>
                ))}
            </section>
          </div>
        )}
    </Modal>
  );
}

const styles = {
  header: {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    padding: '0.625rem 1rem', borderBottom: `1px solid ${T.colors.borderSubtle}`, flexShrink: 0,
  } as React.CSSProperties,
  id: {
    fontFamily: 'monospace', color: T.colors.link, fontSize: '0.875rem', fontWeight: 600,
  } as React.CSSProperties,
  closeBtn: {
    background: 'transparent', border: 'none', color: T.colors.textSecondary,
    cursor: 'pointer', fontSize: '1rem', lineHeight: 1, padding: '0.25rem',
  } as React.CSSProperties,
  body: {
    padding: '1rem', overflowY: 'auto' as const, flex: 1,
  } as React.CSSProperties,
  title: {
    margin: '0 0 0.75rem', fontSize: '1rem', fontWeight: 600, color: T.colors.textBright, lineHeight: 1.4,
  } as React.CSSProperties,
  metaRow: {
    display: 'flex', alignItems: 'center', gap: '0.5rem',
    flexWrap: 'wrap' as const, marginBottom: '0.875rem',
  } as React.CSSProperties,
  metaPill: {
    padding: '0.15rem 0.5rem', background: T.colors.borderSubtle,
    border: `1px solid ${T.colors.border}`, borderRadius: 4,
    color: T.colors.textSecondary, fontSize: '0.75rem',
  } as React.CSSProperties,
  section: {
    marginBottom: '1.25rem',
  } as React.CSSProperties,
  sectionTitle: {
    margin: '0 0 0.5rem', fontSize: '0.75rem', fontWeight: 600, color: T.colors.textDim,
    textTransform: 'uppercase' as const, letterSpacing: '0.05em',
  } as React.CSSProperties,
  notes: {
    margin: '0 0 0.5rem', padding: '0.625rem 0.75rem', background: T.colors.noteBg,
    border: '1px solid #78491a', borderRadius: 6, color: T.colors.noteFg,
    fontSize: '0.8125rem', fontFamily: 'ui-monospace, monospace',
    whiteSpace: 'pre-wrap' as const, wordBreak: 'break-word' as const,
  } as React.CSSProperties,
  depList: {
    display: 'flex', flexDirection: 'column' as const, gap: '0.375rem',
  } as React.CSSProperties,
  desc: {
    margin: 0, padding: '0.625rem 0.75rem', background: T.colors.bgElevated,
    border: `1px solid ${T.colors.border}`, borderRadius: 6, color: T.colors.textBody,
    fontSize: '0.8125rem', fontFamily: 'ui-monospace, monospace',
    whiteSpace: 'pre-wrap' as const, wordBreak: 'break-word' as const, lineHeight: 1.5,
  } as React.CSSProperties,
  depItem: {
    display: 'flex', alignItems: 'center', gap: '0.5rem', padding: '0.375rem 0.5rem',
    borderBottom: `1px solid ${T.colors.borderSubtle}`, fontSize: '0.8125rem',
  } as React.CSSProperties,
  depId: {
    fontFamily: 'monospace', color: T.colors.link, flexShrink: 0,
  } as React.CSSProperties,
  depTitle: {
    flex: 1, minWidth: 0, color: T.colors.textBody, overflow: 'hidden',
    textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  depType: {
    flexShrink: 0, color: T.colors.textMuted, fontSize: '0.7rem', fontFamily: 'monospace',
  } as React.CSSProperties,
  comment: {
    padding: '0.5rem 0', borderBottom: `1px solid ${T.colors.borderSubtle}`,
  } as React.CSSProperties,
  commentMeta: {
    display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.25rem', fontSize: '0.75rem',
  } as React.CSSProperties,
  commentAuthor: {
    color: T.colors.textSecondary, fontWeight: 600,
  } as React.CSSProperties,
  commentText: {
    color: T.colors.textBody, fontSize: '0.8125rem',
    whiteSpace: 'pre-wrap' as const, wordBreak: 'break-word' as const, lineHeight: 1.5,
  } as React.CSSProperties,
};
