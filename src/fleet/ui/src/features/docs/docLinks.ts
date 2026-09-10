// Pure resolver: markdown hrefs inside a doc page become /docs routes.
// External URLs, mailto: and bare #anchors pass through; relative paths
// ending in .md resolve against the current file's directory and match
// pages[].file; anything else (images, src/ paths) passes through.
import type { DocPage } from './docsLoader';

export function resolveDocHref(href: string, currentFile: string, pages: DocPage[]): string {
  if (isExternal(href)) return href;
  const { path, anchor } = splitAnchor(href);
  if (!path.endsWith('.md')) return href;
  const target = joinPosix(dirOf(currentFile), path);
  const page = pages.find(p => p.file === target);
  if (page == null) return href;
  return `/docs/${page.slug}${anchor}`;
}

function isExternal(href: string): boolean {
  return (
    href.startsWith('http://') ||
    href.startsWith('https://') ||
    href.startsWith('mailto:') ||
    href.startsWith('#')
  );
}

function splitAnchor(href: string): { path: string; anchor: string } {
  const i = href.indexOf('#');
  if (i < 0) return { path: href, anchor: '' };
  return { path: href.slice(0, i), anchor: href.slice(i) };
}

function dirOf(file: string): string {
  const i = file.lastIndexOf('/');
  return i < 0 ? '' : file.slice(0, i);
}

// Join base dir + relative path, folding ./ and ../ segments.
function joinPosix(base: string, rel: string): string {
  const out: string[] = base === '' ? [] : base.split('/');
  for (const seg of rel.split('/')) {
    if (seg === '' || seg === '.') continue;
    else if (seg === '..') out.pop();
    else out.push(seg);
  }
  return out.join('/');
}
