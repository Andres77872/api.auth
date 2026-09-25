"""Compatibility facade for the documentation wiki.

The renderer lives in :mod:`src.Util.docs_site`. This module keeps the historical
``DocumentationRenderer`` entry points used by tests and scripts.
"""

from __future__ import annotations

from pathlib import Path

from src.Util.docs_site import DEFAULT_DOCS_ROOT, get_site, templates
from src.Util.docs_site.markdown import Heading, LinkContext, render_markdown, slugify


class DocumentationRenderer:
    """Render Markdown with the wiki's parser and page chrome."""

    @staticmethod
    def _slugify(text: str) -> str:
        return slugify(text)

    @classmethod
    def render_markdown(cls, content: str, doc_path: str = "") -> tuple[str, list[Heading]]:
        """Return ``(html, headings)`` for a Markdown string."""

        doc = render_markdown(content, LinkContext(doc_path=doc_path))
        return doc.html, doc.headings

    @classmethod
    def render_page(
        cls,
        content: str,
        title: str,
        path: str = "",
        base_url: str = "/documentation",
        version: str = "",
        docs_root: Path = DEFAULT_DOCS_ROOT,
    ) -> str:
        """Render ``content`` as a full wiki page (navigation from ``docs_root``)."""

        site = get_site(docs_root)
        relative = path.removeprefix(f"{docs_root.name}/")
        doc = render_markdown(content, LinkContext(doc_path=relative, docs_prefix=docs_root.name))
        if not doc.title:
            doc.title = title
        return templates.render_doc(
            site,
            relative,
            doc,
            base_url=base_url,
            version=version,
            source=path or relative,
        )
