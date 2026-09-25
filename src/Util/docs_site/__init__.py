"""Documentation wiki served at ``/documentation``.

Renders ``docs/`` (primarily ``docs/USAGE``) as a navigable, searchable site with
the admin console's Meridian look and feel, and keeps every page available as raw
Markdown (``?format=raw``) for LLMs and tooling.

Public entry points used by ``src/main.py``:

- :func:`serve` — resolve a docs path to HTML, raw Markdown, a redirect or a 404;
- :func:`render_home_page` — the landing page;
- :func:`search_index` — the JSON index behind the ⌘K search palette;
- :func:`markdown_index` — the raw Markdown listing of every page.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import templates
from .markdown import Heading, LinkContext, RenderedDoc, render_markdown, slugify
from .site import DocsSite, get_site, humanize, render_file

DEFAULT_DOCS_ROOT = Path(__file__).resolve().parents[3] / "docs"

__all__ = [
    "DEFAULT_DOCS_ROOT",
    "DocsResponse",
    "DocsSite",
    "Heading",
    "LinkContext",
    "RenderedDoc",
    "get_site",
    "markdown_index",
    "render_home_page",
    "render_markdown",
    "search_index",
    "serve",
    "slugify",
]


@dataclass
class DocsResponse:
    """Transport-neutral result of :func:`serve`.

    ``kind`` is one of ``html``, ``markdown``, ``text`` or ``redirect`` (``body``
    is then the target URL). ``status`` is the HTTP status to send.
    """

    kind: str
    body: str
    status: int = 200


def _resolve(root: Path, relative: str) -> Path | None:
    """Resolve ``relative`` under ``root``; ``None`` if it escapes the docs tree."""

    if "\x00" in relative:
        return None
    root = root.resolve()
    try:
        target = (root / relative.lstrip("/")).resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    if target != root and not target.is_relative_to(root):
        return None
    return target


def render_home_page(root: Path, *, base_url: str, version: str) -> str:
    return templates.render_home(get_site(root), base_url=base_url, version=version)


def search_index(root: Path, *, base_url: str) -> bytes:
    """UTF-8 JSON search index (pages plus their H2/H3 sections)."""

    return get_site(root).search_index_json(base_url)


def markdown_index(root: Path, *, base_url: str) -> str:
    """Raw Markdown listing of every page, grouped like the navigation."""

    site = get_site(root)
    lines = [
        f"# {templates.BRAND} API documentation",
        "",
        "Every page below is Markdown. Links point at the raw source (`?format=raw`); drop the query",
        "string for the rendered page. Interactive API references: [Swagger UI](/docs),",
        "[ReDoc](/redoc), [OpenAPI schema](/openapi.json).",
    ]
    for section in site.sections:
        lines += ["", f"## {section.title}", ""]
        for item in section.items:
            if hasattr(item, "pages"):
                lines.append(f"### {item.title}")
                lines.append("")
                if item.summary:
                    lines += [item.summary, ""]
                for page in item.pages:
                    lines.append(f"- [{page.title}]({base_url}/{page.path}?format=raw)")
                lines.append("")
            else:
                summary = f" — {item.description}" if item.description else ""
                lines.append(f"- [{item.title}]({base_url}/{item.path}?format=raw){summary}")
    return "\n".join(lines).rstrip() + "\n"


def _directory_entries(root: Path, target: Path) -> list[tuple[str, str]]:
    entries = []
    for file in sorted(target.glob("*.md"), key=lambda p: (p.stem.lower() != "readme", p.name)):
        relative = file.relative_to(root.resolve()).as_posix()
        label = "Overview" if file.stem.lower() == "readme" else humanize(file.stem)
        entries.append((relative, label))
    return entries


def serve(root: Path, path: str, *, base_url: str, version: str, raw: bool = False) -> DocsResponse:
    """Resolve ``path`` (relative to the docs root) into a response."""

    site = get_site(root)
    relative = path.strip("/")
    target = _resolve(root, relative)

    if target is None or not target.exists():
        if raw:
            return DocsResponse("text", f"Documentation not found: {relative}\n", 404)
        return DocsResponse(
            "html",
            templates.render_not_found(site, relative, base_url=base_url, version=version),
            404,
        )

    relative = target.relative_to(root.resolve()).as_posix() if target != root.resolve() else ""

    if target.is_dir():
        entries = _directory_entries(root, target)
        if raw:
            listing = [f"# {relative or 'docs'}", "", "## Files", ""]
            listing += [f"- [{label}]({base_url}/{path_}?format=raw)" for path_, label in entries]
            return DocsResponse("markdown", "\n".join(listing) + "\n")
        if not relative:
            return DocsResponse("redirect", base_url, 307)
        if (target / "README.md").is_file():
            return DocsResponse("redirect", f"{base_url}/{relative}/README.md", 307)
        return DocsResponse(
            "html",
            templates.render_directory(site, relative, entries, base_url=base_url, version=version),
        )

    if target.suffix.lower() != ".md":
        return DocsResponse("text", target.read_text(encoding="utf-8", errors="replace"))

    if raw:
        return DocsResponse("markdown", target.read_text(encoding="utf-8"))

    page = site.page(relative)
    doc = page.doc if page else render_file(root.resolve(), relative)
    source = page.source if page else f"{root.resolve().name}/{relative}"
    return DocsResponse(
        "html",
        templates.render_doc(site, relative, doc, base_url=base_url, version=version, source=source),
    )
