// One doc page rendered as prose: shared Markdown plus anchor scrolling.
// Internal .md links resolve to /docs routes via resolveDocHref.
import { useEffect } from 'react';
import type { CSSProperties } from 'react';
import { useLocation } from 'react-router-dom';
import * as T from '../../shared/styles/tokens';
import { Markdown, slugifyHeading } from '../../shared/ui/Markdown';
import type { DocPage } from './docsLoader';
import { resolveDocHref } from './docLinks';

export { slugifyHeading };

interface Props {
  page: DocPage;
  pages: DocPage[];
}

export function DocArticle({ page, pages }: Props) {
  const { hash } = useLocation();

  useEffect(() => {
    if (hash === '') return;
    document.getElementById(hash.slice(1))?.scrollIntoView();
  }, [hash, page.slug]);

  return (
    <article style={styles.article}>
      <Markdown
        source={page.body}
        resolveHref={href => resolveDocHref(href, page.file, pages)}
      />
    </article>
  );
}

const styles: Record<string, CSSProperties> = {
  article: {
    flex: 1,
    minWidth: 0,
    maxWidth: '46rem',
    lineHeight: 1.6,
    color: T.colors.textBody,
    fontFamily: 'system-ui, sans-serif',
    fontSize: '0.875rem',
  },
};
