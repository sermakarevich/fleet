// Right column of the Docs page: "On this page" outline of the ## and
// ### headings in the current article. Hidden on mobile and on short
// pages (< 3 headings). One IntersectionObserver tracks the last heading
// scrolled past and highlights it.
import { useEffect, useMemo, useState } from 'react';
import type { CSSProperties } from 'react';
import { useIsMobile } from '../../shared/hooks/useIsMobile';
import * as T from '../../shared/styles/tokens';
import { slugifyHeading } from '../../shared/ui/Markdown';

// IntersectionObserver accepts only px or % here (not rem), so this is the one
// place in the UI that uses pixels on purpose. -64px ≈ the 4rem nav height.
export const OUTLINE_ROOT_MARGIN = '-64px 0px -70% 0px';

export interface OutlineItem {
  depth: 2 | 3;
  text: string;
  id: string;
}

// Headings in the body, skipping fenced code blocks; ids reuse the same
// slugify as the rendered heading anchors so outline links always land.
export function outlineOf(body: string): OutlineItem[] {
  const out: OutlineItem[] = [];
  let fenced = false;
  for (const line of body.split('\n')) {
    if (line.trimStart().startsWith('```')) {
      fenced = !fenced;
      continue;
    }
    if (fenced) continue;
    const match = line.match(/^(#{2,3})\s+(.+?)\s*#*\s*$/);
    if (match == null) continue;
    const text = match[2].trim();
    if (text === '') continue;
    out.push({ depth: match[1].length === 3 ? 3 : 2, text, id: slugifyHeading(text) });
  }
  return out;
}

// Observe the rendered headings; the active one is the last observed id
// that has scrolled past (or into) the viewport top band.
function useActiveHeading(ids: string[]): string | null {
  const [activeId, setActiveId] = useState<string | null>(null);
  useEffect(() => {
    if (ids.length === 0 || typeof IntersectionObserver === 'undefined') return;
    const seen = (entries: IntersectionObserverEntry[]) => {
      for (const entry of entries) {
        if (entry.isIntersecting) setActiveId(entry.target.id);
      }
    };
    let observer: IntersectionObserver;
    try {
      observer = new IntersectionObserver(seen, { rootMargin: OUTLINE_ROOT_MARGIN });
    } catch {
      return; // outline highlighting is optional; never take the page down
    }
    for (const id of ids) {
      const el = document.getElementById(id);
      if (el != null) observer.observe(el);
    }
    return () => observer.disconnect();
  }, [ids]);
  return activeId;
}

export function DocOutline({ body }: { body: string }) {
  const items = useMemo(() => outlineOf(body), [body]);
  const ids = useMemo(() => items.map(i => i.id), [items]);
  const isMobile = useIsMobile();
  const activeId = useActiveHeading(ids);
  if (isMobile || items.length < 3) return null;
  return (
    <nav aria-label="On this page" style={styles.col}>
      <div style={styles.label}>On this page</div>
      {items.map(item => (
        <a
          key={item.id}
          href={`#${item.id}`}
          style={{
            ...styles.link,
            color: item.id === activeId ? T.colors.textPrimary : T.colors.textDim,
            paddingLeft: item.depth === 3 ? '0.75rem' : 0,
          }}
        >
          {item.text}
        </a>
      ))}
    </nav>
  );
}

const styles: Record<string, CSSProperties> = {
  col: {
    width: '12rem',
    flexShrink: 0,
    position: 'sticky',
    top: 0,
    alignSelf: 'flex-start',
    maxHeight: '100vh',
    overflowY: 'auto',
    display: 'flex',
    flexDirection: 'column',
    gap: '0.375rem',
  },
  label: {
    fontSize: '0.75rem',
    fontWeight: 600,
    letterSpacing: '0.04em',
    textTransform: 'uppercase',
    color: T.colors.textDim,
    marginBottom: '0.25rem',
  },
  link: {
    display: 'block',
    fontSize: '0.8125rem',
    textDecoration: 'none',
    lineHeight: 1.4,
  },
};
