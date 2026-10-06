"""Documentation site model: navigation, page metadata, search index, caching.

The wiki is built from ``docs/USAGE``. Root Markdown files are guides; every
sub-directory is a topic whose pages are ordered by role (overview, usage,
scenarios, ...). Curated metadata below gives topics a title, icon, section and
one-line summary; anything new on disk still appears (under "More") so a page
can never silently disappear from the navigation.

The whole model is rebuilt only when a Markdown file under ``docs/`` changes
(size or mtime), so requests normally reuse the cached render.
"""

from __future__ import annotations

import json
import posixpath
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path

from .markdown import Heading, LinkContext, RenderedDoc, Section, plain_text, render_markdown, split_table_row

USAGE_DIR = "USAGE"

# Guides at the root of docs/USAGE: file -> (nav label, icon, section, summary)
GUIDES: dict[str, tuple[str, str, str, str]] = {
    "README.md": (
        "Overview",
        "layout-grid",
        "Get started",
        "Suite map, access model, route inventory and the platform-wide contracts.",
    ),
    "getting-started.md": (
        "Getting started",
        "rocket",
        "Get started",
        "Configure and run the API, bootstrap the first root, and make a first authenticated call.",
    ),
    "authentication-usage-cases.md": (
        "Authentication",
        "lock-keyhole",
        "Get started",
        "Login, registration, sessions, refresh rotation, email flows and API-key validation.",
    ),
    "client-authentication-guide.md": (
        "Client integration",
        "plug",
        "Get started",
        "Build browser, mobile and server clients: cookies, bearer tokens, refresh and CORS.",
    ),
    "errors.md": (
        "Error reference",
        "circle-alert",
        "Get started",
        "Response envelopes, status codes, the error-code catalog and symptom-based fixes.",
    ),
    "admin-usage-cases.md": (
        "Administration",
        "gauge",
        "Operations",
        "Dashboard statistics, activity feed, system health, cache and bulk operations.",
    ),
}

# Topic directories: dir -> (title, icon, section, summary, badge)
TOPICS: dict[str, tuple[str, str, str, str, str | None]] = {
    "users": (
        "Users",
        "users",
        "Identity & access",
        "Profiles, lifecycle, user types, scoped administration and multi-email management.",
        None,
    ),
    "groups": (
        "Groups",
        "users-round",
        "Identity & access",
        "User groups, project groups, membership and the links that grant project access.",
        None,
    ),
    "projects": (
        "Projects",
        "folder-kanban",
        "Identity & access",
        "Project lifecycle, members, groups, activity and statistics.",
        None,
    ),
    "roles": (
        "Roles",
        "key-round",
        "Identity & access",
        "Global roles, permission groups, the permission catalog and project role catalogs.",
        None,
    ),
    "permissions": (
        "Permissions",
        "shield",
        "Identity & access",
        "Assigning permission groups and how effective permissions resolve.",
        None,
    ),
    "api-keys": (
        "API keys",
        "key",
        "Identity & access",
        "Split-token keys: self-service and admin lifecycle, validation and rotation.",
        None,
    ),
    "oauth": (
        "OAuth sign-in",
        "log-in",
        "Sign-in & billing",
        "Provider-agnostic sign-in: connections, project bindings, readiness and the admin API.",
        None,
    ),
    "patreon-link": (
        "Patreon link",
        "link-2",
        "Sign-in & billing",
        "Entitlement-only Patreon linking: proof, admin, S2S reads, webhooks and sync.",
        None,
    ),
    "stripe-billing": (
        "Stripe billing",
        "credit-card",
        "Sign-in & billing",
        "Billing groups, catalog, per-account credentials, S2S checkout and webhooks.",
        None,
    ),
    "email": (
        "Email",
        "mail",
        "Operations",
        "Templates, internal delivery, the outbox worker and the provider webhook.",
        None,
    ),
    "audit_logs": (
        "Audit logs",
        "scroll-text",
        "Operations",
        "API audit trail, activity, security events, email logs and export.",
        None,
    ),
}

# Other docs/ directories surfaced in the wiki: dir -> (title, icon, section, summary, badge).
# Their pages are labelled from the file name and listed alphabetically.
ROOT_TOPICS: dict[str, tuple[str, str, str, str, str | None]] = {
    "RUNBOOKS": (
        "Runbooks",
        "wrench",
        "Operations",
        "Rollout, monitoring, incident response, rotation and rollback for the external integrations.",
        None,
    ),
}

SECTION_ORDER = ["Get started", "Identity & access", "Sign-in & billing", "Operations", "More"]

# Page roles inside a topic, in reading order. Unknown files sort between
# "usage" and "scenarios" (they are focused guides such as users/user-types.md).
PAGE_ROLES: dict[str, tuple[int, str]] = {
    "README": (0, "Overview"),
    "usage": (10, "Usage"),
    "scenarios": (30, "Scenarios"),
    "architecture": (40, "Architecture"),
    "request-flow": (50, "Request flow"),
    "reference": (60, "Reference"),
    "troubleshooting": (70, "Troubleshooting"),
}
EXTRA_PAGE_ORDER = 20


def humanize(name: str) -> str:
    """``email-management`` -> ``Email management`` (sentence case)."""

    words = name.replace("_", " ").replace("-", " ").split()
    if not words:
        return name
    acronyms = {"api": "API", "oauth": "OAuth", "sso": "SSO", "s2s": "S2S", "jwt": "JWT", "id": "ID"}
    words = [acronyms.get(word.lower(), word.lower()) for word in words]
    first = words[0]
    words[0] = first if first.isupper() or first in acronyms.values() else first.capitalize()
    return " ".join(words)


@dataclass
class Page:
    path: str  # relative to the docs root, e.g. "USAGE/users/reference.md"
    source: str  # relative to the repository root, e.g. "docs/USAGE/users/reference.md"
    label: str  # short sidebar label
    icon: str
    section: str
    summary: str
    doc: RenderedDoc
    topic: "Topic | None" = None

    @property
    def title(self) -> str:
        return self.doc.title or self.label

    @property
    def description(self) -> str:
        return self.summary or self.doc.description

    @property
    def headings(self) -> list[Heading]:
        return self.doc.headings


@dataclass
class Topic:
    key: str
    path: str  # "USAGE/users"
    title: str
    icon: str
    section: str
    summary: str
    badge: str | None
    pages: list[Page] = field(default_factory=list)

    @property
    def overview(self) -> Page | None:
        return self.pages[0] if self.pages else None


@dataclass
class NavSection:
    title: str
    items: list[Page | Topic] = field(default_factory=list)


@dataclass
class DocsSite:
    root: Path
    sections: list[NavSection]
    pages: dict[str, Page]  # by docs-relative path
    order: list[Page]  # reading order for previous/next
    signature: tuple
    common_tasks: list[tuple[str, str]] = field(default_factory=list)  # (task, docs-relative target)
    _index_cache: dict[str, bytes] = field(default_factory=dict, repr=False)

    @property
    def topics(self) -> list[Topic]:
        return [item for section in self.sections for item in section.items if isinstance(item, Topic)]

    @property
    def guides(self) -> list[Page]:
        return [item for section in self.sections for item in section.items if isinstance(item, Page)]

    def page(self, path: str) -> Page | None:
        return self.pages.get(path)

    def neighbours(self, page: Page) -> tuple[Page | None, Page | None]:
        try:
            index = self.order.index(page)
        except ValueError:
            return None, None
        previous = self.order[index - 1] if index > 0 else None
        following = self.order[index + 1] if index + 1 < len(self.order) else None
        return previous, following

    def search_index_json(self, base_url: str) -> bytes:
        """Serialized :meth:`search_index`, memoised per base URL."""

        cached = self._index_cache.get(base_url)
        if cached is None:
            cached = json.dumps(self.search_index(base_url), separators=(",", ":"), ensure_ascii=False).encode()
            self._index_cache[base_url] = cached
        return cached

    def search_index(self, base_url: str) -> dict:
        """Compact JSON-able search index: pages plus their H2/H3 sections."""

        pages = []
        sections = []
        for page_index, page in enumerate(self.order):
            crumb = page.section if page.topic is None else f"{page.topic.title} · {page.label}"
            pages.append(
                {
                    "t": page.title,
                    "u": f"{base_url}/{page.path}",
                    "c": crumb,
                    "d": page.description[:160],
                    "i": page.topic.icon if page.topic else page.icon,
                }
            )
            intro = page.doc.sections[0] if page.doc.sections and not page.doc.sections[0].slug else None
            if intro:
                pages[-1]["k"] = " ".join(intro.keywords[:20])
            for section in page.doc.sections:
                if not section.slug or section.level > 3:
                    continue
                sections.append(
                    {
                        "p": page_index,
                        "t": section.title,
                        "a": section.slug,
                        "x": _snippet(section),
                        "k": " ".join(_section_keywords(page.doc.sections, section)[:24]),
                    }
                )
        return {"pages": pages, "sections": sections}


def _snippet(section: Section, limit: int = 120) -> str:
    text = " ".join(section.text)
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut + "…"


def _section_keywords(all_sections: list[Section], section: Section) -> list[str]:
    """Keywords of an H2/H3 including its deeper H4+ children."""

    keywords = list(section.keywords)
    start = all_sections.index(section)
    for child in all_sections[start + 1:]:
        if child.slug and child.level <= section.level:
            break
        if child.level > 3:
            keywords.extend(k for k in child.keywords if k not in keywords)
    return keywords


# --------------------------------------------------------------------------- #
# Building
# --------------------------------------------------------------------------- #


def _signature(root: Path) -> tuple:
    entries = []
    for path in sorted(root.rglob("*.md")):
        try:
            stat = path.stat()
        except OSError:
            continue
        entries.append((str(path.relative_to(root)), stat.st_mtime_ns, stat.st_size))
    return tuple(entries)


def render_file(root: Path, relative: str) -> RenderedDoc:
    text = (root / relative).read_text(encoding="utf-8")
    return render_markdown(text, LinkContext(doc_path=relative, docs_prefix=root.name))


def _common_tasks(root: Path) -> list[tuple[str, str]]:
    """Rows of the "Common tasks" table in docs/USAGE/README.md (task -> linked guide)."""

    index = root / USAGE_DIR / "README.md"
    if not index.is_file():
        return []
    text = index.read_text(encoding="utf-8")
    match = re.search(r"^##\s+Common tasks\s*$(.*?)(?=^##\s|\Z)", text, re.MULTILINE | re.DOTALL | re.IGNORECASE)
    if not match:
        return []
    tasks = []
    for line in match.group(1).splitlines():
        if not line.lstrip().startswith("|") or re.match(r"^\s*\|?\s*:?-{3,}", line):
            continue
        cells = split_table_row(line)
        link = re.search(r"\[[^\]]+\]\(([^)\s]+)\)", " ".join(cells[1:]))
        if len(cells) < 2 or not link or link.group(1).startswith(("http://", "https://", "/")):
            continue
        target = posixpath.normpath(posixpath.join(USAGE_DIR, link.group(1)))
        tasks.append((plain_text(cells[0]), target))
    return tasks


def _page_role(stem: str) -> tuple[int, str]:
    return PAGE_ROLES.get(stem, (EXTRA_PAGE_ORDER, humanize(stem)))


def build_site(root: Path) -> DocsSite:
    usage = root / USAGE_DIR
    sections = {title: NavSection(title) for title in SECTION_ORDER}
    pages: dict[str, Page] = {}
    source_prefix = root.name

    def make_page(relative: str, label: str, icon_name: str, section: str, summary: str) -> Page:
        page = Page(
            path=relative,
            source=f"{source_prefix}/{relative}",
            label=label,
            icon=icon_name,
            section=section,
            summary=summary,
            doc=render_file(root, relative),
        )
        pages[relative] = page
        return page

    if usage.is_dir():
        guide_files = sorted(p.name for p in usage.glob("*.md"))
        known = [name for name in GUIDES if name in guide_files]
        unknown = [name for name in guide_files if name not in GUIDES]
        for name in known + unknown:
            label, icon_name, section, summary = GUIDES.get(
                name, (humanize(Path(name).stem), "file-text", "More", "")
            )
            page = make_page(f"{USAGE_DIR}/{name}", label, icon_name, section, summary)
            if name not in GUIDES:
                page.label = page.doc.title or page.label
            sections[section].items.append(page)

        topic_dirs = sorted(p.name for p in usage.iterdir() if p.is_dir() and any(p.glob("*.md")))
        ordered_dirs = [name for name in TOPICS if name in topic_dirs]
        ordered_dirs += [name for name in topic_dirs if name not in TOPICS]
        for name in ordered_dirs:
            title, icon_name, section, summary, badge = TOPICS.get(
                name, (humanize(name), "folder", "More", "", None)
            )
            topic = Topic(
                key=name,
                path=f"{USAGE_DIR}/{name}",
                title=title,
                icon=icon_name,
                section=section,
                summary=summary,
                badge=badge,
            )
            files = sorted(
                (p for p in (usage / name).glob("*.md")),
                key=lambda p: (_page_role(p.stem)[0], p.stem),
            )
            for file in files:
                _, label = _page_role(file.stem)
                page = make_page(f"{USAGE_DIR}/{name}/{file.name}", label, "file-text", section, "")
                page.topic = topic
                topic.pages.append(page)
            if not topic.summary and topic.overview:
                topic.summary = topic.overview.doc.description
            sections[section].items.append(topic)

    for name, (title, icon_name, section, summary, badge) in ROOT_TOPICS.items():
        directory = root / name
        files = sorted(directory.glob("*.md")) if directory.is_dir() else []
        if not files:
            continue
        topic = Topic(key=name.lower(), path=name, title=title, icon=icon_name, section=section,
                      summary=summary, badge=badge)
        for file in sorted(files, key=lambda p: (p.stem.lower() != "readme", p.stem)):
            label = "Overview" if file.stem.lower() == "readme" else humanize(file.stem)
            page = make_page(f"{name}/{file.name}", label, "file-text", section, "")
            page.topic = topic
            topic.pages.append(page)
        sections[section].items.append(topic)

    ordered_sections = [section for section in sections.values() if section.items]
    order: list[Page] = []
    for section in ordered_sections:
        for item in section.items:
            order.extend(item.pages if isinstance(item, Topic) else [item])

    return DocsSite(
        root=root,
        sections=ordered_sections,
        pages=pages,
        order=order,
        signature=_signature(root),
        common_tasks=_common_tasks(root),
    )


_cache: dict[Path, DocsSite] = {}
_lock = threading.Lock()


def get_site(root: Path) -> DocsSite:
    """Return the cached site for ``root``, rebuilding it when docs change."""

    root = root.resolve()
    signature = _signature(root)
    cached = _cache.get(root)
    if cached is not None and cached.signature == signature:
        return cached
    with _lock:
        cached = _cache.get(root)
        if cached is None or cached.signature != signature:
            cached = build_site(root)
            _cache[root] = cached
    return cached


def breadcrumb_for(site: DocsSite, relative: str) -> list[tuple[str, str | None]]:
    """(label, docs-relative path or None) pairs for a page outside the nav too."""

    page = site.page(relative)
    if page and page.topic:
        overview = page.topic.overview
        crumbs = [(page.section, None), (page.topic.title, overview.path if overview and overview is not page else None)]
        if overview is not page:
            crumbs.append((page.label, None))
        return crumbs
    if page:
        return [(page.section, None), (page.label, None)]
    parts = relative.split("/")
    crumbs = []
    for index, part in enumerate(parts[:-1]):
        crumbs.append((humanize(part), posixpath.join(*parts[: index + 1])))
    crumbs.append((humanize(Path(parts[-1]).stem), None))
    return crumbs
