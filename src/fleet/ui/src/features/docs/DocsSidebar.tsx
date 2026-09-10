// Docs section nav: manifest sections in order, pages as NavLinks.
// ADR detail pages (adr-00NN) stay collapsed until the reader opens the
// Decisions section; the filter input hides non-matching titles.
import { useState } from 'react';
import type { CSSProperties } from 'react';
import { NavLink } from 'react-router-dom';
import * as T from '../../shared/styles/tokens';
import * as R from '../../shared/styles/recipes';
import type { DocPage } from './docsLoader';

interface Props {
  pages: DocPage[];
  activeSlug: string;
}

function sectionsOf(pages: DocPage[]): string[] {
  const out: string[] = [];
  for (const p of pages) if (!out.includes(p.section)) out.push(p.section);
  return out;
}

function visiblePages(pages: DocPage[], section: string, activeSlug: string, filter: string): DocPage[] {
  return pages.filter(p => {
    if (p.section !== section) return false;
    if (/^adr-\d/.test(p.slug) && !activeSlug.startsWith('adr')) return false;
    return p.title.toLowerCase().includes(filter);
  });
}

export function DocsSidebar({ pages, activeSlug }: Props) {
  const [filterText, setFilterText] = useState('');
  const filter = filterText.toLowerCase();
  return (
    <nav aria-label="Docs sections" style={styles.sidebar}>
      <input
        aria-label="Filter pages"
        placeholder="Filter pages…"
        value={filterText}
        onChange={e => setFilterText(e.target.value)}
        style={R.searchInputStyle('100%')}
      />
      {sectionsOf(pages).map(section => {
        const items = visiblePages(pages, section, activeSlug, filter);
        if (items.length === 0) return null;
        return (
          <div key={section}>
            <div style={styles.sectionLabel}>{section}</div>
            {items.map(p => (
              <NavLink key={p.slug} to={`/docs/${p.slug}`} style={linkStyle}>
                {p.title}
              </NavLink>
            ))}
          </div>
        );
      })}
    </nav>
  );
}

// Active page mirrors the nav-bar idiom: bright text, semibold, accent edge.
function linkStyle({ isActive }: { isActive: boolean }): CSSProperties {
  return {
    display: 'block',
    padding: '0.25rem 0.625rem',
    textDecoration: 'none',
    fontSize: '0.8125rem',
    color: isActive ? T.colors.textPrimary : T.colors.textSecondary,
    fontWeight: isActive ? 600 : 400,
    borderLeft: isActive
      ? `2px solid ${T.colors.accent}`
      : `2px solid transparent`,
  };
}

const styles: Record<string, CSSProperties> = {
  sidebar: {
    width: '14rem',
    flexShrink: 0,
    position: 'sticky',
    top: 0,
    alignSelf: 'flex-start',
    maxHeight: '100vh',
    overflowY: 'auto',
    display: 'flex',
    flexDirection: 'column',
    gap: '0.75rem',
  },
  sectionLabel: {
    fontSize: '0.75rem',
    fontWeight: 600,
    letterSpacing: '0.04em',
    textTransform: 'uppercase',
    color: T.colors.textDim,
    padding: '0 0.625rem',
    marginBottom: '0.25rem',
  },
};
