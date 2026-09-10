// One doc page rendered as prose: GFM markdown, internal .md links via
// react-router, slugified heading ids so #anchors work, token colours.
import { useEffect, isValidElement } from 'react';
import type { CSSProperties, ReactNode } from 'react';
import { Link, useLocation } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import type { Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import * as T from '../../shared/styles/tokens';
import type { DocPage } from './docsLoader';
import { resolveDocHref } from './docLinks';

interface Props {
  page: DocPage;
  pages: DocPage[];
}

// Lowercase, spaces to dashes, keep [a-z0-9-] for heading anchor ids.
export function slugifyHeading(text: string): string {
  return text.toLowerCase().replace(/\s+/g, '-').replace(/[^a-z0-9-]/g, '');
}

function textOf(node: ReactNode): string {
  if (node == null || typeof node === 'boolean') return '';
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(textOf).join('');
  if (isValidElement(node)) {
    const props = node.props as { children?: ReactNode };
    return textOf(props.children);
  }
  return '';
}

function heading(Tag: 'h1' | 'h2' | 'h3' | 'h4') {
  return function Heading({ children }: { children?: ReactNode }) {
    return (
      <Tag id={slugifyHeading(textOf(children))} style={styles[Tag]}>
        {children}
      </Tag>
    );
  };
}

export function DocArticle({ page, pages }: Props) {
  const { hash } = useLocation();

  useEffect(() => {
    if (hash === '') return;
    document.getElementById(hash.slice(1))?.scrollIntoView();
  }, [hash, page.slug]);

  const components: Components = {
    a({ href, children }) {
      const to = resolveDocHref(href ?? '', page.file, pages);
      if (to.startsWith('/docs/')) return <Link to={to}>{children}</Link>;
      return (
        <a href={href} target="_blank" rel="noreferrer" style={styles.link}>
          {children}
        </a>
      );
    },
    h1: heading('h1'),
    h2: heading('h2'),
    h3: heading('h3'),
    h4: heading('h4'),
    pre({ children }) {
      return <pre style={styles.pre}>{children}</pre>;
    },
    code({ children }) {
      return <code style={styles.code}>{children}</code>;
    },
    table({ children }) {
      return (
        <div style={styles.tableWrap}>
          <table style={styles.table}>{children}</table>
        </div>
      );
    },
  };

  return (
    <article style={styles.article}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {page.body}
      </ReactMarkdown>
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
  h1: { fontSize: '1.125rem', fontWeight: 600, color: T.colors.textPrimary },
  h2: { fontSize: '1rem', fontWeight: 600, color: T.colors.textPrimary },
  h3: { fontSize: '0.9375rem', fontWeight: 600, color: T.colors.textPrimary },
  h4: { fontSize: '0.875rem', fontWeight: 600, color: T.colors.textPrimary },
  link: { color: T.colors.link },
  pre: {
    overflowX: 'auto',
    background: T.colors.bgSurface,
    border: `1px solid ${T.colors.borderSubtle}`,
    borderRadius: '0.25rem',
    padding: '0.75rem 1rem',
  },
  code: {
    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
    fontSize: '0.8125rem',
    color: T.colors.textBright,
  },
  tableWrap: { overflowX: 'auto' },
  table: { borderCollapse: 'collapse', width: '100%' },
};
