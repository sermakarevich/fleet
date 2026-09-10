// outlineOf: ## and ### headings with slug ids, fenced code ignored.
import { describe, expect, it } from 'vitest';
import { OUTLINE_ROOT_MARGIN, outlineOf } from './DocOutline';
import { slugifyHeading } from '../../shared/ui/Markdown';

describe('outlineOf', () => {
  it('collects ## and ### headings with matching ids', () => {
    const body = '# Title\n\n## Hello World!\n\ntext\n\n### Quick Start\n';
    expect(outlineOf(body)).toEqual([
      { depth: 2, text: 'Hello World!', id: slugifyHeading('Hello World!') },
      { depth: 3, text: 'Quick Start', id: slugifyHeading('Quick Start') },
    ]);
  });

  it('ignores headings inside fenced code blocks', () => {
    const body = '## Real\n\n```md\n## Fake\n### Also fake\n```\n\n## After\n';
    expect(outlineOf(body).map(i => i.text)).toEqual(['Real', 'After']);
  });

  it('ignores # and #### headings', () => {
    const body = '# Top\n\n#### Deep\n\n## Kept\n';
    expect(outlineOf(body).map(i => i.text)).toEqual(['Kept']);
  });
});

describe('OUTLINE_ROOT_MARGIN', () => {
  it('uses only px or % units, as IntersectionObserver requires', () => {
    for (const part of OUTLINE_ROOT_MARGIN.split(/\s+/)) {
      expect(part).toMatch(/^-?\d+(\.\d+)?(px|%)$/);
    }
  });
});
