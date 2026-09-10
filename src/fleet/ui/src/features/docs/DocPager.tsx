// Prev/next walk under the Docs article, in manifest order. The collapsed
// adr-00NN detail pages are skipped unless the reader is on an ADR page,
// mirroring the sidebar collapse.
import type { CSSProperties } from 'react';
import { Link } from 'react-router-dom';
import * as T from '../../shared/styles/tokens';
import type { DocPage } from './docsLoader';

interface Props {
  pages: DocPage[];
  slug: string;
}

function isAdrDetail(slug: string): boolean {
  return /^adr-\d/.test(slug);
}

// Neighbours of slug in walk order (full manifest for ADR pages,
// ADR details skipped otherwise); missing when off either end.
export function pagerOf(pages: DocPage[], slug: string): { prev?: DocPage; next?: DocPage } {
  const seq = isAdrDetail(slug) ? pages : pages.filter(p => !isAdrDetail(p.slug));
  const i = seq.findIndex(p => p.slug === slug);
  if (i < 0) return {};
  return { prev: seq[i - 1], next: seq[i + 1] };
}

export function DocPager({ pages, slug }: Props) {
  const { prev, next } = pagerOf(pages, slug);
  if (prev == null && next == null) return null;
  return (
    <nav aria-label="Docs pages" style={styles.pager}>
      {prev != null ? (
        <Link to={`/docs/${prev.slug}`} style={styles.link}>
          ← Previous: {prev.title}
        </Link>
      ) : (
        <span />
      )}
      {next != null ? (
        <Link to={`/docs/${next.slug}`} style={styles.link}>
          Next: {next.title} →
        </Link>
      ) : (
        <span />
      )}
    </nav>
  );
}

const styles: Record<string, CSSProperties> = {
  pager: {
    display: 'flex',
    justifyContent: 'space-between',
    gap: '1rem',
    borderTop: `1px solid ${T.colors.borderSubtle}`,
    marginTop: '1rem',
    paddingTop: '0.75rem',
  },
  link: { color: T.colors.link, fontSize: '0.8125rem', textDecoration: 'none' },
};
