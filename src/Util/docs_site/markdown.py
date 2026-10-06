"""Markdown to HTML for the documentation wiki.

A small, dependency-free renderer for the GitHub-flavoured Markdown subset the
usage docs use: ATX headings, fenced code, GFM tables, nested/ordered/task lists,
blockquotes with GitHub alerts (``> [!NOTE]``), thematic breaks, and inline code,
links, emphasis, strikethrough and autolinks. Raw HTML in the source is always
escaped, so a document can never inject markup into the page.

Besides HTML the renderer collects what the site needs around a page: the title
(first H1), a plain-text description (first paragraph), the heading outline for
the "On this page" rail, and per-section text/keywords for the search index.
"""

from __future__ import annotations

import html
import posixpath
import re
from dataclasses import dataclass, field

from .highlight import highlight, language_label, normalize_language
from .icons import icon

HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")

ALERTS = {
    # kind: (label, icon)
    "note": ("Note", "info"),
    "tip": ("Tip", "lightbulb"),
    "important": ("Important", "message-square-warning"),
    "warning": ("Warning", "triangle-alert"),
    "caution": ("Caution", "octagon-alert"),
}
# Legacy "> !marker text" callouts map onto the GitHub alert kinds.


def slugify(text: str) -> str:
    """Heading anchor slug.

    Kept byte-for-byte compatible with the link checker in
    ``tests/static/test_documentation_consistency.py`` so every documented
    ``file.md#anchor`` resolves to the id the page actually renders.
    """

    return re.sub(r"[^\w\s-]", "", text.lower()).strip().replace(" ", "-")


@dataclass
class Heading:
    level: int
    text: str
    slug: str


@dataclass
class Section:
    """A heading-delimited slice of a page, used by the search index."""

    title: str
    slug: str
    level: int
    text: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)


@dataclass
class RenderedDoc:
    html: str
    title: str | None
    title_slug: str | None
    description: str
    headings: list[Heading]
    sections: list[Section]
    word_count: int = 0

    @property
    def reading_minutes(self) -> int:
        return max(1, round(self.word_count / 220))


@dataclass
class LinkContext:
    """Where the document lives, so relative links can be classified."""

    doc_path: str = ""  # relative to the docs root, e.g. "USAGE/users/README.md"
    docs_prefix: str = "docs"  # the docs root relative to the repository root


# --------------------------------------------------------------------------- #
# Block grammar
# --------------------------------------------------------------------------- #

_FENCE_RE = re.compile(r"^( {0,3})(`{3,}|~{3,})[ \t]*([^\s`{]*)[^`]*$")
_ATX_RE = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")
_HR_RE = re.compile(r"^ {0,3}(?:(?:-[ \t]*){3,}|(?:\*[ \t]*){3,}|(?:_[ \t]*){3,})$")
_QUOTE_RE = re.compile(r"^ {0,3}>[ ]?(.*)$")
_LIST_RE = re.compile(r"^( *)([-*+]|\d{1,9}[.)])(?:([ \t]+)(.*))?$")
_TABLE_DELIM_RE = re.compile(r"^ {0,3}\|?[ \t]*:?-+:?[ \t]*(?:\|[ \t]*:?-+:?[ \t]*)*\|?[ \t]*$")
_ALERT_RE = re.compile(r"^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\][ \t]*(.*)$", re.IGNORECASE)
_TASK_RE = re.compile(r"^\[([ xX])\][ \t]+")


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _is_blank(line: str) -> bool:
    return not line.strip()


class _Renderer:
    def __init__(self, ctx: LinkContext):
        self.ctx = ctx
        self.inline = InlineRenderer(ctx)
        self.headings: list[Heading] = []
        self.sections: list[Section] = [Section(title="", slug="", level=1)]
        self.slug_counts: dict[str, int] = {}
        self.title: str | None = None
        self.title_slug: str | None = None
        self.description = ""
        self._first_paragraph_pending = True

    # -- helpers ------------------------------------------------------------ #

    def _collect_text(self, raw: str) -> None:
        plain = plain_text(raw)
        if plain:
            self.sections[-1].text.append(plain)
        for code in re.findall(r"(`+)(.+?)\1", raw):
            value = code[1].strip()
            if 2 <= len(value) <= 80 and value not in self.sections[-1].keywords:
                self.sections[-1].keywords.append(value)

    def _starts_block(self, lines: list[str], index: int) -> bool:
        line = lines[index]
        if _FENCE_RE.match(line) or _ATX_RE.match(line) or _HR_RE.match(line):
            return True
        if _QUOTE_RE.match(line):
            return True
        if self._is_table_start(lines, index):
            return True
        match = _LIST_RE.match(line)
        if match and match.group(3) is not None and match.group(4).strip():
            return True
        return False

    @staticmethod
    def _is_table_start(lines: list[str], index: int) -> bool:
        if index + 1 >= len(lines):
            return False
        header, delimiter = lines[index], lines[index + 1]
        return (
            "|" in header
            and "|" in delimiter
            and "-" in delimiter
            and bool(_TABLE_DELIM_RE.match(delimiter))
        )

    # -- block dispatcher --------------------------------------------------- #

    def render(self, lines: list[str], tight: bool = False) -> str:
        out: list[str] = []
        index = 0
        total = len(lines)
        while index < total:
            line = lines[index]
            if _is_blank(line):
                index += 1
                continue
            fence = _FENCE_RE.match(line)
            if fence:
                index = self._fence(lines, index, fence, out)
                continue
            atx = _ATX_RE.match(line)
            if atx:
                self._heading(len(atx.group(1)), atx.group(2) or "", out)
                index += 1
                continue
            if _HR_RE.match(line):
                out.append("<hr>")
                index += 1
                continue
            if _QUOTE_RE.match(line):
                index = self._blockquote(lines, index, out)
                continue
            if self._is_table_start(lines, index):
                index = self._table(lines, index, out)
                continue
            item = _LIST_RE.match(line)
            if item and item.group(3) is not None:
                index = self._list(lines, index, out)
                continue
            index = self._paragraph(lines, index, out, tight)
        return "\n".join(out)

    # -- leaf blocks -------------------------------------------------------- #

    def _fence(self, lines: list[str], index: int, match: re.Match[str], out: list[str]) -> int:
        indent = len(match.group(1))
        marker = match.group(2)
        lang = normalize_language(match.group(3))
        body: list[str] = []
        index += 1
        closing = re.compile(r"^ {0,3}" + re.escape(marker[0]) + "{" + str(len(marker)) + r",}[ \t]*$")
        while index < len(lines) and not closing.match(lines[index]):
            raw = lines[index]
            strip = min(indent, _indent_of(raw))
            body.append(raw[strip:])
            index += 1
        index += 1  # skip the closing fence (or run off the end)
        code = "\n".join(body)
        out.append(self._code_block(code, lang))
        if lang not in ("text", ""):
            self.sections[-1].text.append(code[:400])
        return index

    @staticmethod
    def _code_block(code: str, lang: str) -> str:
        label = language_label(lang or "text")
        highlighted = highlight(code, lang)
        return (
            f'<div class="code-block" data-lang="{html.escape(lang or "text")}">'
            f'<div class="code-head"><span class="code-lang">{html.escape(label)}</span>'
            f'<button type="button" class="code-copy" data-copy-code aria-label="Copy code">'
            f'{icon("copy", 14)}<span>Copy</span></button></div>'
            f'<pre tabindex="0"><code class="language-{html.escape(lang or "text")}">{highlighted}</code></pre>'
            "</div>"
        )

    def _heading(self, level: int, raw: str, out: list[str]) -> None:
        raw = raw.strip()
        base = slugify(raw) or "section"
        count = self.slug_counts.get(base, 0)
        self.slug_counts[base] = count + 1
        slug = base if count == 0 else f"{base}-{count}"
        text = plain_text(raw)
        inner = self.inline.render(raw)

        if level == 1 and self.title is None:
            self.title = text
            self.title_slug = slug
            self.sections[0] = Section(title=text, slug="", level=1)
            return  # the page header renders the title

        if level >= 2:
            self.headings.append(Heading(level=level, text=text, slug=slug))
            self.sections.append(Section(title=text, slug=slug, level=level))
        anchor = (
            f'<a class="anchor" href="#{slug}" aria-label="Link to {html.escape(text)}">'
            f'{icon("link", 14)}</a>'
        )
        out.append(f'<h{level} id="{slug}">{inner}{anchor}</h{level}>')

    def _paragraph(self, lines: list[str], index: int, out: list[str], tight: bool) -> int:
        buffer = [lines[index]]
        index += 1
        while index < len(lines):
            line = lines[index]
            if _is_blank(line) or self._starts_block(lines, index):
                break
            buffer.append(line)
            index += 1
        raw = "\n".join(part.strip() if i else part.lstrip() for i, part in enumerate(buffer))
        raw = raw.rstrip()
        self._collect_text(raw)
        if self._first_paragraph_pending and self.title is not None and not self.headings:
            self.description = plain_text(raw)
            self._first_paragraph_pending = False
        rendered = self.inline.render(raw)
        out.append(rendered if tight else f"<p>{rendered}</p>")
        return index

    # -- container blocks --------------------------------------------------- #

    def _blockquote(self, lines: list[str], index: int, out: list[str]) -> int:
        body: list[str] = []
        previous_was_text = False
        while index < len(lines):
            line = lines[index]
            match = _QUOTE_RE.match(line)
            if match:
                content = match.group(1)
                body.append(content)
                previous_was_text = bool(content.strip())
                index += 1
                continue
            # Lazy continuation: a plain text line directly after quoted text.
            if previous_was_text and not _is_blank(line) and not self._starts_block(lines, index):
                body.append(line)
                index += 1
                continue
            break

        kind = None
        first = next((i for i, text in enumerate(body) if text.strip()), None)
        if first is not None:
            head = body[first].strip()
            alert = _ALERT_RE.match(head)
            if alert:
                kind = alert.group(1).lower()
                rest = alert.group(2)
                body = body[:first] + ([rest] if rest else []) + body[first + 1:]


        inner = self.render(body)
        if kind:
            label, glyph = ALERTS[kind]
            out.append(
                f'<div class="callout callout-{kind}" role="note">'
                f'<div class="callout-title">{icon(glyph, 16)}<span>{label}</span></div>'
                f'<div class="callout-body">{inner}</div></div>'
            )
        else:
            out.append(f"<blockquote>{inner}</blockquote>")
        return index

    def _list(self, lines: list[str], index: int, out: list[str]) -> int:
        first = _LIST_RE.match(lines[index])
        assert first is not None
        base_indent = len(first.group(1))
        ordered = first.group(2)[0].isdigit()
        bullet_char = None if ordered else first.group(2)
        start = int(first.group(2)[:-1]) if ordered else 1

        items: list[list[str]] = []
        loose = False
        while index < len(lines):
            match = _LIST_RE.match(lines[index])
            if not match or match.group(3) is None or len(match.group(1)) != base_indent:
                break
            is_ordered = match.group(2)[0].isdigit()
            if is_ordered != ordered or (not ordered and match.group(2) != bullet_char):
                break
            spacing = len(match.group(3).expandtabs(4))
            content_indent = base_indent + len(match.group(2)) + (spacing if spacing <= 4 else 1)
            item_lines = [match.group(4) or ""]
            index += 1
            pending_blank = 0
            while index < len(lines):
                line = lines[index]
                if _is_blank(line):
                    pending_blank += 1
                    index += 1
                    continue
                indent = _indent_of(line)
                nested_marker = _LIST_RE.match(line)
                belongs = indent >= content_indent or (
                    nested_marker is not None
                    and nested_marker.group(3) is not None
                    and indent > base_indent
                )
                if belongs:
                    if pending_blank:
                        # Blocks separated by a blank line make the list loose.
                        item_lines.extend([""] * pending_blank)
                        loose = True
                        pending_blank = 0
                    item_lines.append(line[min(indent, content_indent):])
                    index += 1
                    continue
                if pending_blank == 0 and not self._starts_block(lines, index):
                    item_lines.append(line.strip())  # lazy paragraph continuation
                    index += 1
                    continue
                break
            items.append(item_lines)
            if pending_blank:
                next_item = index < len(lines) and _LIST_RE.match(lines[index])
                if (
                    next_item
                    and next_item.group(3) is not None
                    and len(next_item.group(1)) == base_indent
                ):
                    loose = True
                else:
                    break

        tag = "ol" if ordered else "ul"
        attrs = f' start="{start}"' if ordered and start != 1 else ""
        rendered_items: list[str] = []
        has_tasks = False
        for item_lines in items:
            checkbox = ""
            task = _TASK_RE.match(item_lines[0]) if item_lines else None
            if task:
                has_tasks = True
                checked = " checked" if task.group(1).lower() == "x" else ""
                checkbox = f'<input type="checkbox" disabled{checked} aria-hidden="true">'
                item_lines = [item_lines[0][task.end():]] + item_lines[1:]
            inner = self.render(item_lines, tight=not loose)
            css = ' class="task"' if task else ""
            rendered_items.append(f"<li{css}>{checkbox}{inner}</li>")
        css = ' class="task-list"' if has_tasks else ""
        out.append(f"<{tag}{attrs}{css}>" + "".join(rendered_items) + f"</{tag}>")
        return index

    def _table(self, lines: list[str], index: int, out: list[str]) -> int:
        header = split_table_row(lines[index])
        aligns = []
        for cell in split_table_row(lines[index + 1]):
            cell = cell.strip()
            if cell.startswith(":") and cell.endswith(":"):
                aligns.append("center")
            elif cell.endswith(":"):
                aligns.append("right")
            elif cell.startswith(":"):
                aligns.append("left")
            else:
                aligns.append("")
        index += 2
        rows: list[list[str]] = []
        while index < len(lines):
            line = lines[index]
            if _is_blank(line) or "|" not in line:
                break
            if _FENCE_RE.match(line) or _ATX_RE.match(line) or _QUOTE_RE.match(line):
                break
            rows.append(split_table_row(line))
            index += 1

        width = len(header)

        def cell_html(tag: str, raw: str, column: int) -> str:
            align = aligns[column] if column < len(aligns) else ""
            style = f' style="text-align:{align}"' if align else ""
            return f"<{tag}{style}>{self._cell(raw)}</{tag}>"

        head_html = "".join(cell_html("th", cell, i) for i, cell in enumerate(header))
        body_html = []
        for row in rows:
            row = (row + [""] * width)[:width]
            self._collect_text(" · ".join(cell for cell in row if cell))
            body_html.append("<tr>" + "".join(cell_html("td", cell, i) for i, cell in enumerate(row)) + "</tr>")
        out.append(
            '<div class="table-wrap" tabindex="0"><table>'
            f"<thead><tr>{head_html}</tr></thead>"
            f"<tbody>{''.join(body_html)}</tbody></table></div>"
        )
        return index

    def _cell(self, raw: str) -> str:
        stripped = raw.strip()
        methods = re.split(r"\s*[,/]\s*|\s+", stripped.replace("`", "")) if stripped else []
        if methods and all(method.upper() in HTTP_METHODS and method.isupper() for method in methods):
            return " ".join(method_badge(method) for method in methods)
        return self.inline.render(stripped)


def split_table_row(line: str) -> list[str]:
    """Split a GFM table row on unescaped pipes outside code spans."""

    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|") and not text.endswith("\\|"):
        text = text[:-1]
    cells: list[str] = []
    current: list[str] = []
    index = 0
    code_run = 0
    while index < len(text):
        char = text[index]
        if char == "\\" and index + 1 < len(text) and text[index + 1] == "|":
            current.append("|")
            index += 2
            continue
        if char == "`":
            rest = text[index:]
            run = len(rest) - len(rest.lstrip("`"))
            if code_run == 0:
                # Only open a code span if a matching closing run exists.
                closing = text.find("`" * run, index + run)
                if closing != -1:
                    code_run = run
            elif run == code_run:
                code_run = 0
            current.append("`" * run)
            index += run
            continue
        if char == "|" and code_run == 0:
            cells.append("".join(current).strip())
            current = []
            index += 1
            continue
        current.append(char)
        index += 1
    cells.append("".join(current).strip())
    return cells


def method_badge(method: str) -> str:
    method = method.upper()
    return f'<span class="method method-{method.lower()}">{method}</span>'


# --------------------------------------------------------------------------- #
# Inline grammar
# --------------------------------------------------------------------------- #

_CODE_SPAN_RE = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)", re.DOTALL)
_AUTOLINK_RE = re.compile(r"<(https?://[^\s<>]+|mailto:[^\s<>]+)>")
_ESCAPE_RE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|~<>])")
_LINK_RE = re.compile(
    r"(!?)\[((?:[^\[\]]|\[[^\[\]]*\])*)\]\(\s*<?([^()\s<>]*(?:\([^()\s]*\)[^()\s<>]*)*)>?(?:\s+\"([^\"]*)\")?\s*\)"
)
_BARE_URL_RE = re.compile(r"(?<![\w/=\"'>])(https?://[^\s<>()\x00]+[^\s<>()\x00.,;:!?'\"])")
_STRONG_RE = re.compile(r"(?<!\*)\*\*(?=\S)(.+?)(?<=\S)\*\*(?!\*)|(?<![\w_])__(?=\S)(.+?)(?<=\S)__(?![\w_])", re.DOTALL)
_EM_RE = re.compile(r"(?<![\*\w])\*(?=[^\s*])(.+?)(?<=[^\s*])\*(?![\*\w])|(?<![\w_])_(?=[^\s_])(.+?)(?<=[^\s_])_(?![\w_])", re.DOTALL)
_STRIKE_RE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~", re.DOTALL)
_ENDPOINT_RE = re.compile(r"^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(/\S*)$")
_PLACEHOLDER_RE = re.compile(r"\x00(\d+)\x00")


class InlineRenderer:
    def __init__(self, ctx: LinkContext):
        self.ctx = ctx

    def render(self, text: str) -> str:
        stash: list[str] = []

        def keep(fragment: str) -> str:
            stash.append(fragment)
            return f"\x00{len(stash) - 1}\x00"

        def code_span(match: re.Match[str]) -> str:
            content = match.group(2).replace("\n", " ")
            if content.startswith(" ") and content.endswith(" ") and content.strip():
                content = content[1:-1]
            endpoint = _ENDPOINT_RE.match(content)
            if endpoint:
                method, path = endpoint.groups()
                return keep(
                    f'<code class="endpoint">{method_badge(method)}'
                    f'<span class="endpoint-path">{html.escape(path)}</span></code>'
                )
            return keep(f"<code>{html.escape(content)}</code>")

        text = _CODE_SPAN_RE.sub(code_span, text)
        text = _AUTOLINK_RE.sub(lambda m: keep(self._anchor(m.group(1), html.escape(m.group(1)))), text)
        text = _ESCAPE_RE.sub(lambda m: keep(html.escape(m.group(1))), text)

        def link(match: re.Match[str]) -> str:
            is_image, label, target, title = match.groups()
            if is_image:
                alt = html.escape(plain_text(label))
                src = html.escape(target)
                return keep(f'<img src="{src}" alt="{alt}" loading="lazy">')
            opening, closing = self._link_tags(target, title)
            return keep(opening) + label + keep(closing)

        # Links may nest emphasis/code placeholders; iterate for [a [b](x)](y) safety.
        previous = None
        while previous != text:
            previous = text
            text = _LINK_RE.sub(link, text)

        text = html.escape(text, quote=False)
        text = _BARE_URL_RE.sub(lambda m: keep(self._anchor(html.unescape(m.group(1)), m.group(1))), text)
        text = _STRONG_RE.sub(lambda m: f"<strong>{m.group(1) or m.group(2)}</strong>", text)
        text = _EM_RE.sub(lambda m: f"<em>{m.group(1) or m.group(2)}</em>", text)
        text = _STRIKE_RE.sub(r"<del>\1</del>", text)
        text = re.sub(r"(?: {2,}|\\)\n", "<br>\n", text)

        while _PLACEHOLDER_RE.search(text):
            text = _PLACEHOLDER_RE.sub(lambda m: stash[int(m.group(1))], text)
        return text

    # -- links ---------------------------------------------------------------- #

    def _anchor(self, href: str, label_html: str) -> str:
        opening, closing = self._link_tags(href, None)
        return f"{opening}{label_html}{closing}"

    def _link_tags(self, target: str, title: str | None) -> tuple[str, str]:
        title_attr = f' title="{html.escape(title)}"' if title else ""
        kind, href = self.classify_link(target)
        if kind == "external":
            return (
                f'<a class="ext" href="{html.escape(href)}"{title_attr} target="_blank" rel="noopener noreferrer">',
                f'{icon("external-link", 12)}</a>',
            )
        if kind == "blocked":
            return "<span>", "</span>"
        if kind == "repo":
            # Source files outside docs/ are not served by the wiki; show the
            # repository path instead of a dead link.
            return (
                f'<span class="repo-ref" title="Repository file: {html.escape(href)}">',
                "</span>",
            )
        return f'<a href="{html.escape(href)}"{title_attr}>', "</a>"

    def classify_link(self, target: str) -> tuple[str, str]:
        if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.IGNORECASE):
            if target.lower().startswith(("http://", "https://")):
                return "external", target
            if target.lower().startswith(("mailto:", "tel:")):
                return "internal", target
            return "blocked", ""  # javascript:, data:, vbscript:, ...
        if target.startswith(("/", "#", "?")) or not self.ctx.doc_path:
            return "internal", target
        path_part = target.split("#", 1)[0].split("?", 1)[0]
        if not path_part:
            return "internal", target
        doc_dir = posixpath.dirname(self.ctx.doc_path)
        repo_path = posixpath.normpath(posixpath.join(self.ctx.docs_prefix, doc_dir, path_part))
        if repo_path == self.ctx.docs_prefix or repo_path.startswith(self.ctx.docs_prefix + "/"):
            return "internal", target
        return "repo", repo_path


# --------------------------------------------------------------------------- #
# Plain text
# --------------------------------------------------------------------------- #


def plain_text(text: str) -> str:
    """Strip inline Markdown to readable plain text (titles, search, meta)."""

    text = _CODE_SPAN_RE.sub(lambda m: m.group(2).strip(), text)
    text = re.sub(r"!?\[((?:[^\[\]]|\[[^\[\]]*\])*)\]\([^)]*\)", r"\1", text)
    text = _AUTOLINK_RE.sub(r"\1", text)
    text = re.sub(r"(\*\*|__|~~)(?=\S)(.+?)(?<=\S)\1", r"\2", text)
    text = re.sub(r"(?<![\*\w])\*(?=\S)(.+?)(?<=\S)\*(?![\*\w])", r"\1", text)
    text = re.sub(r"(?<![\w_])_(?=\S)(.+?)(?<=\S)_(?![\w_])", r"\1", text)
    text = _ESCAPE_RE.sub(r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def render_markdown(content: str, ctx: LinkContext | None = None) -> RenderedDoc:
    """Render a Markdown document to HTML plus its outline and search data."""

    renderer = _Renderer(ctx or LinkContext())
    lines = content.replace("\r\n", "\n").replace("\r", "\n").expandtabs(4).split("\n")
    body = renderer.render(lines)
    sections = [section for section in renderer.sections if section.title or section.text]
    words = sum(len(" ".join(section.text).split()) for section in renderer.sections)
    return RenderedDoc(
        html=body,
        title=renderer.title,
        title_slug=renderer.title_slug,
        description=renderer.description,
        headings=renderer.headings,
        sections=sections,
        word_count=words,
    )
