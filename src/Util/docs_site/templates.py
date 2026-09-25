"""HTML templates for the documentation wiki (Meridian look and feel)."""

from __future__ import annotations

import difflib
import html
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

from .icons import ICONS, icon
from .markdown import RenderedDoc
from .site import DocsSite, Page, Topic, breadcrumb_for, humanize

STATIC_DIR = Path(__file__).parent / "static"
BRAND = "Magic Auth"
SITE_NAME = "Magic Auth docs"

# Palette result icons the client script can clone (topic/guide icons are added per site).
_PALETTE_ICONS = {"hash", "file-text", "corner-down-left"}

_THEME_BOOT = (
    "(function(){try{var s=localStorage.getItem('theme');"
    "var d=!s||s==='dark'||(s==='system'&&window.matchMedia('(prefers-color-scheme: dark)').matches);"
    "document.documentElement.setAttribute('data-theme',d?'dark':'light');}catch(e){}})();"
)

_FAVICON = (
    "data:image/svg+xml,"
    + quote(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
        '<rect width="32" height="32" rx="7" fill="#2f6fde"/>'
        '<g transform="translate(4 4)" fill="none" stroke="#fff" stroke-width="2.2" '
        f'stroke-linecap="round" stroke-linejoin="round">{ICONS["shield-check"]}</g></svg>'
    )
)


@lru_cache(maxsize=None)
def _asset(name: str) -> str:
    return (STATIC_DIR / name).read_text(encoding="utf-8")


def e(value: object) -> str:
    return html.escape(str(value), quote=True)


# --------------------------------------------------------------------------- #
# Shell
# --------------------------------------------------------------------------- #


def _sidebar(site: DocsSite, active: str | None, base_url: str, version: str) -> str:
    parts: list[str] = []
    for section in site.sections:
        items: list[str] = []
        for item in section.items:
            if isinstance(item, Topic):
                is_active = active is not None and any(page.path == active for page in item.pages)
                links = "".join(
                    f'<li><a class="nav-item" href="{e(base_url)}/{e(page.path)}"'
                    f'{" aria-current=" + chr(34) + "page" + chr(34) if page.path == active else ""}>'
                    f'<span class="nav-label">{e(page.label)}</span></a></li>'
                    for page in item.pages
                )
                badge = f'<span class="badge">{e(item.badge)}</span>' if item.badge else ""
                items.append(
                    f'<li><details class="nav-topic{" is-active" if is_active else ""}"{" open" if is_active else ""}>'
                    f'<summary class="nav-item">{icon(item.icon, 16)}'
                    f'<span class="nav-label">{e(item.title)}</span>{badge}'
                    f'{icon("chevron-right", 14, "icon nav-chevron")}</summary>'
                    f'<ul class="nav-sublist">{links}</ul></details></li>'
                )
            else:
                current = ' aria-current="page"' if item.path == active else ""
                items.append(
                    f'<li><a class="nav-item" href="{e(base_url)}/{e(item.path)}"{current}>'
                    f'{icon(item.icon, 16)}<span class="nav-label">{e(item.label)}</span></a></li>'
                )
        parts.append(
            f'<div class="nav-section"><h2 class="nav-heading">{e(section.title)}</h2>'
            f'<ul class="nav-list">{"".join(items)}</ul></div>'
        )

    theme = "".join(
        f'<button type="button" role="radio" aria-checked="false" data-theme-choice="{value}" '
        f'title="{label} theme" aria-label="{label} theme">{icon(glyph, 14)}</button>'
        for value, label, glyph in (("light", "Light", "sun"), ("dark", "Dark", "moon"), ("system", "System", "monitor"))
    )
    return (
        '<aside class="sidebar" id="docs-sidebar" aria-label="Documentation">'
        f'<a class="brand" href="{e(base_url)}" aria-label="{BRAND} documentation home">'
        f'<span class="brand-mark">{icon("shield-check", 16)}</span>'
        f'<span class="brand-text"><span class="brand-name">{BRAND}</span>'
        '<span class="brand-sub">API documentation</span></span>'
        f'<span class="brand-version" title="API version">v{e(version)}</span></a>'
        f'<nav class="nav" aria-label="Documentation pages">{"".join(parts)}</nav>'
        '<div class="sidebar-foot">'
        '<div class="foot-links">'
        f'<a class="foot-link" href="/docs">{icon("code", 14)}Swagger UI</a>'
        f'<a class="foot-link" href="/redoc">{icon("book-open", 14)}ReDoc</a></div>'
        f'<div class="theme-switch" role="radiogroup" aria-label="Color theme">{theme}</div>'
        "</div></aside>"
    )


def _breadcrumbs(crumbs: list[tuple[str, str | None]], base_url: str) -> str:
    items = [f'<li><a href="{e(base_url)}">Docs</a></li>']
    for index, (label, target) in enumerate(crumbs):
        is_last = index == len(crumbs) - 1
        if is_last:
            items.append(f'<li><span aria-current="page">{e(label)}</span></li>')
        elif target:
            items.append(f'<li><a href="{e(base_url)}/{e(target)}">{e(label)}</a></li>')
        else:
            items.append(f'<li class="crumb-section"><span>{e(label)}</span></li>')
    return f'<nav class="crumbs" aria-label="Breadcrumb"><ol>{"".join(items)}</ol></nav>'


def _palette_icons(site: DocsSite) -> str:
    names = set(_PALETTE_ICONS)
    names.update(topic.icon for topic in site.topics)
    names.update(page.icon for page in site.guides)
    return "".join(f'<template data-icon="{e(name)}">{icon(name, 15)}</template>' for name in sorted(names))


def _shell(
    *,
    site: DocsSite,
    title: str,
    description: str,
    main: str,
    base_url: str,
    version: str,
    active: str | None = None,
    crumbs: list[tuple[str, str | None]] | None = None,
) -> str:
    page_title = f"{title} · {SITE_NAME}" if title != SITE_NAME else SITE_NAME
    crumb_html = _breadcrumbs(crumbs, base_url) if crumbs else '<div class="crumbs"></div>'
    return f"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(page_title)}</title>
<meta name="description" content="{e(description[:300])}">
<meta name="color-scheme" content="dark light">
<script>{_THEME_BOOT}</script>
<link rel="icon" href="{_FAVICON}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Geist:wght@400;450;500;600;700&amp;family=Geist+Mono:wght@400;500;600&amp;display=swap">
<style>{_asset("docs.css")}</style>
</head>
<body data-docs-base="{e(base_url)}">
<a class="skip-link" href="#main">Skip to content</a>
<div class="app">
{_sidebar(site, active, base_url, version)}
<div class="scrim" data-scrim hidden></div>
<div class="main-col">
<header class="topbar">
<button type="button" class="icon-btn menu-btn" data-menu aria-controls="docs-sidebar" aria-expanded="false" aria-label="Open navigation">{icon("menu", 18)}</button>
{crumb_html}
<div class="topbar-actions">
<button type="button" class="search-trigger" data-search-open aria-label="Search documentation" aria-keyshortcuts="Control+K Meta+K /">{icon("search", 15)}<span>Search docs…</span><kbd data-shortcut>Ctrl K</kbd></button>
<a class="icon-btn api-link" href="/docs" title="Swagger UI (interactive API reference)" aria-label="Swagger UI">{icon("square-terminal", 18)}</a>
</div>
</header>
<main id="main" tabindex="-1">
{main}
</main>
</div>
</div>
<div class="palette" data-palette hidden>
<div class="palette-dialog" role="dialog" aria-modal="true" aria-label="Search documentation">
<div class="palette-input-row">{icon("search", 17)}
<input class="palette-input" data-palette-input type="search" placeholder="Search pages, endpoints, fields, error codes…" autocomplete="off" spellcheck="false" role="combobox" aria-expanded="true" aria-controls="palette-results" aria-autocomplete="list">
<kbd>esc</kbd></div>
<div class="palette-results" id="palette-results" data-palette-results role="listbox" aria-label="Search results"></div>
<div class="palette-foot"><span><kbd>↑</kbd><kbd>↓</kbd> to move</span><span><kbd>↵</kbd> to open</span><span><kbd>esc</kbd> to close</span></div>
</div>
</div>
<div class="toast" data-toast role="status" aria-live="polite">{icon("circle-check", 15)}<span data-toast-text></span></div>
{_palette_icons(site)}
<script>{_asset("docs.js")}</script>
</body>
</html>"""


# --------------------------------------------------------------------------- #
# Document pages
# --------------------------------------------------------------------------- #


def _toc_list(doc: RenderedDoc) -> str:
    entries = [heading for heading in doc.headings if heading.level in (2, 3)]
    if len(entries) < 2:
        return ""
    return "".join(
        f'<li class="toc-l{heading.level}"><a href="#{e(heading.slug)}">{e(heading.text)}</a></li>'
        for heading in entries
    )


def _pager(site: DocsSite, page: Page, base_url: str) -> str:
    previous, following = site.neighbours(page)
    if not previous and not following:
        return ""

    def card(target: Page, direction: str) -> str:
        where = target.topic.title if target.topic else target.section
        label = target.label if target.topic else target.title
        if direction == "prev":
            head = f'{icon("arrow-left", 13)}Previous'
            css = "pager-prev"
        else:
            head = f'Next{icon("arrow-right", 13)}'
            css = "pager-next"
        return (
            f'<a class="{css}" href="{e(base_url)}/{e(target.path)}" rel="{"prev" if direction == "prev" else "next"}">'
            f'<span class="pager-dir">{head}</span>'
            f'<span class="pager-title">{e(label)}</span><span class="pager-topic">{e(where)}</span></a>'
        )

    parts = []
    if previous:
        parts.append(card(previous, "prev"))
    if following:
        parts.append(card(following, "next"))
    return f'<nav class="pager" aria-label="Previous and next page">{"".join(parts)}</nav>'


def render_doc(
    site: DocsSite,
    relative: str,
    doc: RenderedDoc,
    *,
    base_url: str,
    version: str,
    source: str,
) -> str:
    page = site.page(relative)
    title = doc.title or (page.label if page else Path(relative).stem)
    raw_url = f"{base_url}/{relative}?format=raw"

    # Header: eyebrow, icon chip + title, topic tabs, meta and actions.
    if page and page.topic:
        topic = page.topic
        overview = topic.overview
        eyebrow = (
            f'<span>{e(page.section)}</span><span class="eyebrow-sep">/</span>'
            f'<a href="{e(base_url)}/{e(overview.path if overview else page.path)}">{e(topic.title)}</a>'
        )
        chip_icon = topic.icon
        tabs = "".join(
            f'<li><a href="{e(base_url)}/{e(sibling.path)}"'
            f'{" aria-current=" + chr(34) + "page" + chr(34) if sibling is page else ""}>{e(sibling.label)}</a></li>'
            for sibling in topic.pages
        )
        tabs_html = f'<ul class="topic-tabs" aria-label="{e(topic.title)} pages">{tabs}</ul>' if len(topic.pages) > 1 else ""
    elif page:
        eyebrow = f"<span>{e(page.section)}</span>"
        chip_icon = page.icon
        tabs_html = ""
    else:
        folder = str(Path(relative).parent).replace("/", " / ")
        eyebrow = f"<span>{e(folder)}</span>"
        chip_icon = "file-text"
        tabs_html = ""

    toc_items = _toc_list(doc)
    sections = len([h for h in doc.headings if h.level == 2])
    meta = (
        f'<div class="doc-meta">'
        f'<span class="meta-item">{icon("book-open", 14)}{doc.reading_minutes} min read</span>'
        + (f'<span class="meta-item">{icon("list", 14)}{sections} sections</span>' if sections else "")
        + '<span class="spacer"></span>'
        f'<button type="button" class="btn btn-ghost" data-copy-markdown="{e(raw_url)}" '
        f'title="Copy this page as Markdown (for LLMs and notes)" aria-label="Copy this page as Markdown">'
        f'{icon("clipboard-copy", 14)}<span class="btn-label">Copy Markdown</span></button>'
        f'<a class="btn btn-ghost" href="{e(raw_url)}" title="Raw Markdown source" aria-label="View raw Markdown">'
        f'{icon("file-code", 14)}<span class="btn-label">Markdown</span></a>'
        "</div>"
    )

    header = (
        '<header class="doc-header">'
        f'<p class="eyebrow">{eyebrow}</p>'
        f'<div class="title-row"><span class="title-chip">{icon(chip_icon, 20)}</span>'
        f'<h1 class="doc-title" id="{e(doc.title_slug or "top")}">{e(title)}</h1></div>'
        f"{meta}{tabs_html}</header>"
    )
    inline_toc = (
        f'<details class="toc-inline"><summary>{icon("list-tree", 15)}On this page'
        f'{icon("chevron-right", 14, "icon nav-chevron")}</summary><ul class="toc-list">{toc_items}</ul></details>'
        if toc_items
        else ""
    )
    footer = (
        '<footer class="doc-footer">'
        f"<span>Source: <code>{e(source)}</code></span>"
        f'<span><a href="{e(raw_url)}">View Markdown</a> · <a href="/docs">Swagger UI</a> · <a href="/redoc">ReDoc</a></span>'
        "</footer>"
    )
    article = (
        f"<article>{header}{inline_toc}"
        f'<div class="prose">{doc.html}</div>'
        f'{_pager(site, page, base_url) if page else ""}{footer}</article>'
    )
    rail = (
        f'<aside class="toc" aria-label="On this page"><p class="toc-title">{icon("list-tree", 14)}On this page</p>'
        f'<ul class="toc-list">{toc_items}</ul>'
        f'<div class="toc-foot"><button type="button" data-back-to-top>{icon("arrow-up", 13)}Back to top</button>'
        f'<a href="{e(raw_url)}">{icon("file-code", 13)}View Markdown</a></div></aside>'
        if toc_items
        else ""
    )
    layout = "page" if toc_items else "page no-toc"
    main = f'<div class="{layout}">{article}{rail}</div>'

    return _shell(
        site=site,
        title=title,
        description=(page.description if page else doc.description) or title,
        main=main,
        base_url=base_url,
        version=version,
        active=relative if page else None,
        crumbs=breadcrumb_for(site, relative),
    )


# --------------------------------------------------------------------------- #
# Home, directory and not-found pages
# --------------------------------------------------------------------------- #


def _topic_card(topic: Topic, base_url: str) -> str:
    overview = topic.overview
    href = f"{base_url}/{overview.path}" if overview else f"{base_url}/{topic.path}"
    badge = f'<span class="badge">{e(topic.badge)}</span>' if topic.badge else ""
    chips = "".join(f'<span class="chip">{e(page.label)}</span>' for page in topic.pages[1:5])
    more = len(topic.pages) - 5
    if more > 0:
        chips += f'<span class="chip">+{more}</span>'
    return (
        f'<a class="card" href="{e(href)}">'
        f'<div class="card-head"><span class="card-icon">{icon(topic.icon, 17)}</span>'
        f'<span class="card-title">{e(topic.title)}</span>{badge}</div>'
        f'<p class="card-text">{e(topic.summary)}</p>'
        f'<div class="card-foot">{chips}</div></a>'
    )


def _guide_card(page: Page, base_url: str) -> str:
    return (
        f'<a class="card" href="{e(base_url)}/{e(page.path)}">'
        f'<div class="card-head"><span class="card-icon">{icon(page.icon, 17)}</span>'
        f'<span class="card-title">{e(page.label)}</span></div>'
        f'<p class="card-text">{e(page.description)}</p></a>'
    )


def render_home(site: DocsSite, *, base_url: str, version: str) -> str:
    start = next((section for section in site.sections if section.title == "Get started"), None)
    first_guide = next(
        (page for page in site.guides if page.path.endswith("getting-started.md")),
        site.order[0] if site.order else None,
    )
    topic_count = len(site.topics)
    page_count = len(site.order)

    sections_html = []
    if start:
        cards = "".join(_guide_card(item, base_url) for item in start.items if isinstance(item, Page))
        sections_html.append(
            '<section class="home-section" aria-labelledby="home-start">'
            '<div class="home-section-head"><h2 id="home-start">Start here</h2>'
            "<p>Set up, authenticate, and learn the contracts every client relies on.</p></div>"
            f'<div class="card-grid">{cards}</div></section>'
        )
    if site.common_tasks:
        rows = []
        for task, target in site.common_tasks:
            page = site.page(target.split("#", 1)[0])
            where = (f"{page.topic.title} · {page.label}" if page and page.topic else page.title) if page else target
            rows.append(
                f'<a class="task-link" href="{e(base_url)}/{e(target)}">'
                f'<span class="task-body"><span class="task-title">{e(task)}</span>'
                f'<span class="task-where">{e(where)}</span></span>{icon("arrow-right", 15)}</a>'
            )
        sections_html.append(
            '<section class="home-section" aria-labelledby="home-tasks">'
            '<div class="home-section-head"><h2 id="home-tasks">Common tasks</h2>'
            "<p>Jump straight to the guide for the job at hand.</p></div>"
            f'<div class="task-grid">{"".join(rows)}</div></section>'
        )
    for index, section in enumerate(site.sections):
        if section is start:
            continue
        cards = "".join(
            _topic_card(item, base_url) if isinstance(item, Topic) else _guide_card(item, base_url)
            for item in section.items
        )
        sections_html.append(
            f'<section class="home-section" aria-labelledby="home-s{index}">'
            f'<div class="home-section-head"><h2 id="home-s{index}">{e(section.title)}</h2></div>'
            f'<div class="card-grid">{cards}</div></section>'
        )

    explorers = [
        ("/docs", "code", "Swagger UI", "/docs"),
        ("/redoc", "book-open", "ReDoc", "/redoc"),
        ("/openapi.json", "braces", "OpenAPI schema", "/openapi.json"),
        (f"{base_url}?format=raw", "file-code", "Markdown index for LLMs and tooling", f"{base_url}?format=raw"),
    ]
    explorer_html = "".join(
        f'<li><a href="{e(href)}">{icon(glyph, 16)}<span class="link-title">{e(label)}</span>'
        f'<span class="link-path">{e(path)}</span>{icon("arrow-right", 14)}</a></li>'
        for href, glyph, label, path in explorers
    )
    sections_html.append(
        '<section class="home-section" aria-labelledby="home-api">'
        '<div class="home-section-head"><h2 id="home-api">API explorers</h2>'
        "<p>Every page is also available as raw Markdown with <code>?format=raw</code>.</p></div>"
        f'<ul class="link-list">{explorer_html}</ul></section>'
    )

    cta = (
        f'<a class="btn btn-primary" href="{e(base_url)}/{e(first_guide.path)}">Get started{icon("arrow-right", 15)}</a>'
        if first_guide
        else ""
    )
    main = (
        '<div class="home">'
        '<section class="hero">'
        '<p class="eyebrow">API documentation</p>'
        f"<h1>{BRAND} API documentation</h1>"
        '<p class="hero-lead">Guides, contracts and references for the group-based, multi-project '
        "authentication service: sessions, access control, OAuth sign-in, API keys, transactional "
        "email and billing.</p>"
        f'<div class="hero-actions">{cta}'
        f'<button type="button" class="btn btn-secondary" data-search-open>{icon("search", 15)}Search the docs'
        '<kbd data-shortcut>Ctrl K</kbd></button></div>'
        f'<div class="hero-stats"><span>API <strong>v{e(version)}</strong></span>'
        f"<span><strong>{topic_count}</strong> topics</span><span><strong>{page_count}</strong> pages</span></div>"
        "</section>"
        f'{"".join(sections_html)}</div>'
    )
    return _shell(
        site=site,
        title=SITE_NAME,
        description=f"{BRAND} API documentation: guides, contracts and references.",
        main=main,
        base_url=base_url,
        version=version,
    )


def render_directory(
    site: DocsSite,
    relative: str,
    entries: list[tuple[str, str]],
    *,
    base_url: str,
    version: str,
) -> str:
    """List Markdown files of a directory that has no README.md."""

    items = "".join(
        f'<li><a href="{e(base_url)}/{e(path)}">{icon("file-text", 16)}<span class="link-title">{e(label)}</span>'
        f'<span class="link-path">{e(Path(path).name)}</span>{icon("arrow-right", 14)}</a></li>'
        for path, label in entries
    )
    title = humanize(Path(relative).name or relative)
    main = (
        '<div class="page no-toc"><article><header class="doc-header">'
        f'<p class="eyebrow"><span>{e(relative)}</span></p>'
        f'<div class="title-row"><span class="title-chip">{icon("folder", 20)}</span>'
        f'<h1 class="doc-title">{e(title)}</h1></div></header>'
        f'<ul class="link-list">{items or "<li><span class=link-title>No documents</span></li>"}</ul>'
        "</article></div>"
    )
    return _shell(
        site=site,
        title=title,
        description=f"Documents in {relative}",
        main=main,
        base_url=base_url,
        version=version,
        crumbs=breadcrumb_for(site, relative),
    )


def render_not_found(site: DocsSite, relative: str, *, base_url: str, version: str) -> str:
    candidates = {page.path: page for page in site.order}
    names = difflib.get_close_matches(relative, list(candidates), n=4, cutoff=0.4)
    if not names:
        needle = Path(relative).stem.replace("-", " ").lower()
        names = [page.path for page in site.order if needle and needle in page.title.lower()][:4]
    suggestions = "".join(
        f'<li><a href="{e(base_url)}/{e(path)}">{icon("file-text", 16)}<span class="link-title">{e(candidates[path].title)}</span>'
        f'<span class="link-path">{e(path)}</span>{icon("arrow-right", 14)}</a></li>'
        for path in names
    )
    suggestions_html = (
        f'<div class="home-section"><div class="home-section-head"><h2>Did you mean</h2></div>'
        f'<ul class="link-list">{suggestions}</ul></div>'
        if suggestions
        else ""
    )
    main = (
        '<div class="page no-toc"><article>'
        '<div class="empty-state">'
        f'<span class="card-icon">{icon("compass", 22)}</span>'
        "<h1>Page not found</h1>"
        f"<p>There is no document at <code>{e(relative)}</code>. It may have moved; search the docs or start from the overview.</p>"
        f'<div class="hero-actions"><a class="btn btn-primary" href="{e(base_url)}">Docs home</a>'
        f'<button type="button" class="btn btn-secondary" data-search-open>{icon("search", 15)}Search</button></div>'
        f"</div>{suggestions_html}</article></div>"
    )
    return _shell(
        site=site,
        title="Page not found",
        description="The requested documentation page does not exist.",
        main=main,
        base_url=base_url,
        version=version,
        crumbs=[("Not found", None)],
    )
