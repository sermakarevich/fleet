"""Docs-guide contracts: manifest coverage, link resolution, README length."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUIDE = ROOT / "docs" / "guide"
ADR = ROOT / "docs" / "adr"
MANIFEST = GUIDE / "manifest.json"
README = ROOT / "README.md"

LINK_RE = re.compile(r"\]\(([^)#\s][^)]*?\.md(?:#[^)]*)?)\)")
SLUG_RE = re.compile(r"^[a-z0-9-]+$")


def _pages():
    return json.loads(MANIFEST.read_text())["pages"]


def test_manifest_pages_exist_and_slugs_valid():
    pages = _pages()
    slugs = [p["slug"] for p in pages]
    assert len(slugs) == len(set(slugs)), "duplicate slugs in manifest"
    for page in pages:
        assert SLUG_RE.match(page["slug"]), f"bad slug: {page['slug']}"
        assert (ROOT / page["file"]).is_file(), f"missing file: {page['file']}"


def test_every_guide_and_adr_page_in_manifest():
    files = {p["file"] for p in _pages()}
    for md in sorted(GUIDE.glob("*.md")):
        assert f"docs/guide/{md.name}" in files, f"guide page missing: {md.name}"
    for md in sorted(ADR.glob("*.md")):
        assert f"docs/adr/{md.name}" in files, f"adr page missing: {md.name}"


def _md_link_targets(path: Path) -> list[str]:
    targets = []
    for match in LINK_RE.finditer(path.read_text()):
        target = match.group(1)
        if target.startswith(("http", "mailto:")):
            continue
        targets.append(target.split("#")[0])
    return targets


def test_md_links_resolve():
    pages = [README, *sorted(GUIDE.glob("*.md"))]
    for page in pages:
        for target in _md_link_targets(page):
            resolved = (page.parent / target).resolve()
            assert resolved.is_file(), f"{page.name}: link target missing: {target}"


def test_readme_short():
    assert len(README.read_text().splitlines()) <= 120
