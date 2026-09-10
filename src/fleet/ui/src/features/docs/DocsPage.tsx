// Docs route: sidebar + article + outline in a wide flex layout.
// Unknown slugs get the shared EmptyState; on mobile the sidebar becomes
// a select dropdown above the article and the outline hides.
import { useEffect, useMemo } from 'react';
import type { CSSProperties } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useIsMobile } from '../../shared/hooks/useIsMobile';
import * as R from '../../shared/styles/recipes';
import { EmptyState } from '../../shared/ui/EmptyState';
import { DocArticle } from './DocArticle';
import { DocOutline } from './DocOutline';
import { DocPager } from './DocPager';
import { DocsSidebar } from './DocsSidebar';
import { loadDocs } from './docsLoader';

export function DocsPage() {
  const { slug } = useParams();
  const active = slug ?? 'overview';
  const isMobile = useIsMobile();
  const navigate = useNavigate();
  const pages = useMemo(loadDocs, []);
  const page = pages.find(p => p.slug === active);

  useEffect(() => {
    const prev = document.title;
    if (page != null) document.title = `${page.title} · fleet docs`;
    return () => {
      document.title = prev;
    };
  }, [page]);

  if (page == null) {
    return (
      <div style={R.pageStyle(isMobile)}>
        <EmptyState
          message={
            <>
              No page called {active}. <Link to="/docs">← Back to Docs</Link>
            </>
          }
        />
      </div>
    );
  }

  return (
    <div style={R.pageStyle(isMobile)}>
      {isMobile && (
        <select
          aria-label="Docs page"
          value={active}
          onChange={e => navigate(`/docs/${e.target.value}`)}
          style={styles.select}
        >
          {pages.map(p => (
            <option key={p.slug} value={p.slug}>
              {p.title}
            </option>
          ))}
        </select>
      )}
      <div style={styles.layout}>
        {!isMobile && <DocsSidebar pages={pages} activeSlug={active} />}
        <div style={styles.articleCol}>
          <h1 style={R.headingStyle()}>{page.title}</h1>
          <DocArticle page={page} pages={pages} />
          <DocPager pages={pages} slug={active} />
        </div>
        {!isMobile && <DocOutline body={page.body} />}
      </div>
    </div>
  );
}

const styles: Record<string, CSSProperties> = {
  layout: { display: 'flex', gap: '2rem', alignItems: 'flex-start' },
  articleCol: { flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: '0.75rem' },
  select: { ...R.searchInputStyle('100%'), marginBottom: '0.75rem' },
};
