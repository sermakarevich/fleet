// Bundled docs loader: manifest order + raw markdown via Vite `?raw`.
// Six levels up from features/docs reaches the repo root (src/fleet/ui
// is nested under src/). No backend route; pages ship inside the bundle.
import manifest from '../../../../../../docs/guide/manifest.json';

const files = import.meta.glob(
  '../../../../../../docs/**/*.md',
  { query: '?raw', import: 'default', eager: true },
) as Record<string, string>;

export interface DocPage {
  slug: string;
  title: string;
  section: string;
  file: string;
  body: string;
}

interface ManifestEntry {
  slug: string;
  title: string;
  section: string;
  file: string;
}

// Pages in manifest order; throws when a manifest file is not bundled.
export function loadDocs(): DocPage[] {
  return (manifest.pages as ManifestEntry[]).map(entry => {
    const suffix = entry.file.replace(/^docs\//, '');
    const key = Object.keys(files).find(k => k.endsWith(suffix));
    if (key == null) throw new Error(`docs: no bundled markdown for ${entry.file}`);
    return { ...entry, body: files[key] };
  });
}

let cached: DocPage[] | null = null;

// Find one page by slug (memoized; the bundle never changes at runtime).
export function findDoc(slug: string): DocPage | undefined {
  if (cached == null) cached = loadDocs();
  return cached.find(p => p.slug === slug);
}
