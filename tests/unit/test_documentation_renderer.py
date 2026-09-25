"""Unit tests for the documentation wiki (src/Util/docs_site).

Covers the Markdown renderer (blocks, inline, callouts, tables, lists, code),
HTML safety, the site model (navigation, ordering, search index, cache
invalidation) and path resolution for the /documentation routes.
"""

import json
import os
import re

import pytest

from src.Util import docs_site
from src.Util.docs_site.highlight import highlight
from src.Util.docs_site.markdown import LinkContext, render_markdown, slugify, split_table_row
from src.Util.documentation_renderer import DocumentationRenderer


def html_of(markdown: str, doc_path: str = "") -> str:
    return render_markdown(markdown, LinkContext(doc_path=doc_path)).html


class TestHeadings:
    def test_first_h1_becomes_the_title_and_is_not_repeated_in_the_body(self):
        doc = render_markdown("# Users reference\n\nIntro paragraph.\n\n## Endpoints\n")
        assert doc.title == "Users reference"
        assert "<h1" not in doc.html
        assert doc.description == "Intro paragraph."

    def test_heading_ids_match_the_link_checker_slug(self):
        doc = render_markdown("# T\n\n## System Health & Metrics\n\n### `POST /auth/login` fields\n")
        assert 'id="system-health--metrics"' in doc.html
        assert f'id="{slugify("`POST /auth/login` fields")}"' in doc.html
        assert [h.slug for h in doc.headings] == ["system-health--metrics", "post-authlogin-fields"]

    def test_duplicate_headings_get_github_style_suffixes(self):
        doc = render_markdown("# T\n\n## Example\n\n## Example\n\n## Example\n")
        assert [h.slug for h in doc.headings] == ["example", "example-1", "example-2"]

    def test_hash_comments_inside_code_fences_are_not_headings(self):
        doc = render_markdown("# T\n\n```bash\n# Step 1: log in\ncurl /auth/login\n```\n")
        assert doc.headings == []
        assert "<h1" not in doc.html
        assert "# Step 1: log in" in doc.html


class TestCodeBlocks:
    def test_fence_renders_language_label_copy_button_and_escaped_code(self):
        out = html_of('```json\n{"html": "<script>alert(1)</script>"}\n```')
        assert 'class="code-block" data-lang="json"' in out
        assert "JSON" in out and "data-copy-code" in out
        assert "<script>" not in out
        assert "&lt;script&gt;" in out

    def test_language_aliases_and_unknown_languages(self):
        assert 'data-lang="bash"' in html_of("```sh\nls\n```")
        assert 'data-lang="json"' in html_of("```jsonc\n{}\n```")
        assert 'data-lang="text"' in html_of("```\nplain\n```")

    def test_highlighter_marks_json_keys_strings_and_literals(self):
        out = highlight('{"ok": true, "n": 1, "s": "x"}', "json")
        assert '<span class="tk-p">&quot;ok&quot;</span>' in out or '<span class="tk-p">"ok"</span>' in out
        assert '<span class="tk-b">true</span>' in out
        assert '<span class="tk-n">1</span>' in out

    def test_highlighter_escapes_html_in_unknown_languages(self):
        assert highlight("<b>x</b>", "brainfuck") == "&lt;b&gt;x&lt;/b&gt;"

    def test_fence_inside_list_item_is_dedented(self):
        out = html_of("1. Run:\n\n   ```bash\n   curl /ping\n   ```\n2. Done\n")
        assert "<ol>" in out and 'data-lang="bash"' in out
        assert '<span class="tk-k">curl</span> /ping</code>' in out


class TestTables:
    def test_pipes_inside_code_spans_and_escaped_pipes_do_not_split_cells(self):
        assert split_table_row("| `a|b` | c \\| d | e |") == ["`a|b`", "c | d", "e"]

    def test_backtick_heavy_cells_render_intact(self):
        out = html_of("| `details` key | Present for |\n| --- | --- |\n| `context` | errors |\n")
        assert "<th><code>details</code> key</th>" in out
        assert "<td><code>context</code></td>" in out

    def test_method_cells_become_badges_and_alignment_is_kept(self):
        out = html_of("| Path | Method |\n| --- | :---: |\n| `/users` | GET, POST |\n")
        assert '<span class="method method-get">GET</span>' in out
        assert '<span class="method method-post">POST</span>' in out
        assert "text-align:center" in out

    def test_short_rows_are_padded(self):
        out = html_of("| a | b |\n| - | - |\n| only |\n")
        assert out.count("<td>") == 2


class TestLists:
    def test_nested_ordered_and_task_lists(self):
        out = html_of("3. three\n4. four\n   - nested\n\n- [x] done\n- [ ] todo\n")
        assert '<ol start="3">' in out
        assert "<ul><li>nested</li></ul>" in out
        assert 'class="task-list"' in out
        assert "checked" in out

    def test_tight_list_has_no_paragraph_wrappers(self):
        assert html_of("- a\n- b\n") == "<ul><li>a</li><li>b</li></ul>"

    def test_loose_list_wraps_paragraphs(self):
        assert "<li><p>a</p></li>" in html_of("- a\n\n- b\n")


class TestBlockquotesAndCallouts:
    def test_plain_blockquote(self):
        out = html_of("> This is a plain blockquote")
        assert out == "<blockquote><p>This is a plain blockquote</p></blockquote>"

    def test_consecutive_quote_lines_form_one_blockquote(self):
        out = html_of("> First line\n> second line\n")
        assert out.count("<blockquote>") == 1

    @pytest.mark.parametrize(
        "marker, kind",
        [("NOTE", "note"), ("TIP", "tip"), ("IMPORTANT", "important"), ("WARNING", "warning"), ("CAUTION", "caution")],
    )
    def test_github_alerts(self, marker, kind):
        out = html_of(f"> [!{marker}]\n> Body with **bold** text.\n")
        assert f"callout callout-{kind}" in out
        assert "<strong>bold</strong>" in out
        assert "[!" not in out

    @pytest.mark.parametrize(
        "marker, kind",
        [("!warning", "warning"), ("!warn", "warning"), ("!info", "note"), ("!note", "note"),
         ("!tip", "tip"), ("!danger", "caution"), ("!error", "caution")],
    )
    def test_legacy_callout_markers(self, marker, kind):
        out = html_of(f"> {marker} Short message")
        assert f"callout-{kind}" in out
        assert "Short message" in out

    def test_empty_blockquote_does_not_crash(self):
        assert "blockquote" in html_of("> ")

    def test_callout_can_hold_code_and_lists(self):
        out = html_of("> [!NOTE]\n> Steps:\n>\n> - one\n> - two\n>\n> ```bash\n> curl x\n> ```\n")
        assert "<ul>" in out and 'data-lang="bash"' in out


class TestInline:
    def test_raw_html_is_always_escaped(self):
        out = html_of('Hello <img src=x onerror="alert(1)"> and <script>x</script>')
        assert "<img" not in out and "<script>" not in out
        assert "&lt;script&gt;" in out

    def test_code_span_contents_are_literal(self):
        out = html_of("Use `**not bold**` and `<b>`.")
        assert "<code>**not bold**</code>" in out
        assert "<code>&lt;b&gt;</code>" in out

    def test_endpoint_code_spans_get_method_badges(self):
        out = html_of("Call `DELETE /users/{user_hash}` now.")
        assert '<code class="endpoint"><span class="method method-delete">DELETE</span>' in out

    def test_identifiers_with_underscores_are_not_italicised(self):
        out = html_of("Send project_hash and user_group_hash.")
        assert "<em>" not in out

    def test_emphasis_strong_and_strikethrough(self):
        out = html_of("*a* **b** _c_ __d__ ~~e~~")
        assert "<em>a</em>" in out and "<strong>b</strong>" in out
        assert "<em>c</em>" in out and "<strong>d</strong>" in out
        assert "<del>e</del>" in out

    def test_backslash_escapes(self):
        assert html_of(r"\*not italic\*") == "<p>*not italic*</p>"

    def test_links_are_classified(self):
        doc_path = "USAGE/users/README.md"
        out = html_of("[ref](reference.md#fields) [ext](https://example.com) [src](../../../src/main.py)", doc_path)
        assert '<a href="reference.md#fields">ref</a>' in out
        assert 'class="ext" href="https://example.com"' in out and 'rel="noopener noreferrer"' in out
        assert 'class="repo-ref" title="Repository file: src/main.py"' in out

    @pytest.mark.parametrize("target", ["javascript:alert(1)", "JavaScript:alert(1)", "data:text/html,x"])
    def test_script_capable_schemes_are_never_linked(self, target):
        out = html_of(f"[click]({target})")
        assert "href=" not in out
        assert "click" in out

    def test_mailto_links_are_kept(self):
        assert '<a href="mailto:ops@example.com">mail</a>' in html_of("[mail](mailto:ops@example.com)")

    def test_bare_urls_are_autolinked(self):
        out = html_of("See https://example.com/docs.")
        assert '<a class="ext" href="https://example.com/docs"' in out
        assert out.endswith(".</p>")


class TestSearchData:
    def test_sections_collect_text_and_code_keywords(self):
        doc = render_markdown("# T\n\n## Login\n\nSend `project_hash` to `POST /auth/login`.\n")
        login = [s for s in doc.sections if s.slug == "login"][0]
        assert "project_hash" in login.keywords
        assert "POST /auth/login" in login.keywords
        assert "Send project_hash" in " ".join(login.text)


# --------------------------------------------------------------------------- #
# Site model and serving
# --------------------------------------------------------------------------- #


@pytest.fixture()
def docs_root(tmp_path):
    root = tmp_path / "docs"
    usage = root / "USAGE"
    (usage / "users").mkdir(parents=True)
    (usage / "zeta-new").mkdir()
    (root / "RUNBOOKS").mkdir()
    (usage / "README.md").write_text("# Usage\n\nIndex.\n")
    (usage / "getting-started.md").write_text("# Getting started\n\nSet up.\n\n## Install\n\nRun it.\n")
    (usage / "users" / "README.md").write_text("# Users\n\nPeople.\n")
    (usage / "users" / "reference.md").write_text("# Users reference\n\n## Fields\n\n`user_hash` text.\n")
    (usage / "users" / "usage.md").write_text("# Users usage\n\nTasks.\n")
    (usage / "users" / "user-types.md").write_text("# User types\n\nTypes.\n")
    (usage / "zeta-new" / "README.md").write_text("# Zeta\n\nNew topic.\n")
    (root / "RUNBOOKS" / "ops.md").write_text("# Ops\n\nRunbook.\n")
    return root


class TestSite:
    def test_navigation_orders_guides_topics_and_pages_by_role(self, docs_root):
        site = docs_site.get_site(docs_root)
        titles = [section.title for section in site.sections]
        assert titles[0] == "Get started"
        assert "More" in titles  # unknown topic directories are never dropped
        users = next(topic for topic in site.topics if topic.key == "users")
        assert [page.label for page in users.pages] == ["Overview", "Usage", "User types", "Reference"]
        assert [p.path for p in site.order][:2] == ["USAGE/README.md", "USAGE/getting-started.md"]

    def test_previous_and_next_follow_reading_order(self, docs_root):
        site = docs_site.get_site(docs_root)
        page = site.page("USAGE/users/usage.md")
        previous, following = site.neighbours(page)
        assert previous.path == "USAGE/users/README.md"
        assert following.path == "USAGE/users/user-types.md"

    def test_search_index_lists_pages_and_sections(self, docs_root):
        index = json.loads(docs_site.search_index(docs_root, base_url="/documentation"))
        assert any(page["t"] == "Users reference" for page in index["pages"])
        fields = [s for s in index["sections"] if s["t"] == "Fields"][0]
        assert fields["a"] == "fields" and "user_hash" in fields["k"]

    def test_cache_is_rebuilt_when_a_document_changes(self, docs_root):
        first = docs_site.get_site(docs_root)
        assert docs_site.get_site(docs_root) is first
        target = docs_root / "USAGE" / "users" / "usage.md"
        target.write_text("# Users usage, revised\n\nMore tasks here.\n")
        os.utime(target, ns=(target.stat().st_atime_ns, target.stat().st_mtime_ns + 5_000_000))
        rebuilt = docs_site.get_site(docs_root)
        assert rebuilt is not first
        assert rebuilt.page("USAGE/users/usage.md").title == "Users usage, revised"


class TestServe:
    def serve(self, root, path, raw=False):
        return docs_site.serve(root, path, base_url="/documentation", version="1.0", raw=raw)

    def test_page_renders_with_navigation_outline_and_article(self, docs_root):
        result = self.serve(docs_root, "USAGE/getting-started.md")
        assert result.kind == "html" and result.status == 200
        assert "<article>" in result.body
        assert 'aria-current="page"' in result.body
        assert 'href="#install"' in result.body or "Install" in result.body

    def test_raw_format_returns_the_markdown_source(self, docs_root):
        result = self.serve(docs_root, "USAGE/users/reference.md", raw=True)
        assert result.kind == "markdown"
        assert result.body.startswith("# Users reference")

    def test_directories_redirect_to_their_readme(self, docs_root):
        result = self.serve(docs_root, "USAGE/users/")
        assert (result.kind, result.body) == ("redirect", "/documentation/USAGE/users/README.md")

    def test_directory_without_readme_lists_documents(self, docs_root):
        result = self.serve(docs_root, "RUNBOOKS")
        assert result.kind == "html" and "RUNBOOKS/ops.md" in result.body

    @pytest.mark.parametrize("path", ["../secrets.md", "USAGE/../../etc/passwd", "USAGE/missing.md", "a\x00b"])
    def test_missing_and_escaping_paths_are_404(self, docs_root, path):
        (docs_root.parent / "secrets.md").write_text("# secret")
        assert self.serve(docs_root, path).status == 404
        assert self.serve(docs_root, path, raw=True).status == 404

    def test_not_found_page_suggests_close_matches(self, docs_root):
        result = self.serve(docs_root, "USAGE/users/referense.md")
        assert result.status == 404 and "USAGE/users/reference.md" in result.body

    def test_home_and_markdown_index(self, docs_root):
        home = docs_site.render_home_page(docs_root, base_url="/documentation", version="9.9.9")
        assert "v9.9.9" in home and "Users" in home
        index = docs_site.markdown_index(docs_root, base_url="/documentation")
        assert "- [Users reference](/documentation/USAGE/users/reference.md?format=raw)" in index


class TestCompatibilityFacade:
    def test_render_markdown_returns_html_and_headings(self):
        html, headings = DocumentationRenderer.render_markdown("# T\n\n## A\n")
        assert 'id="a"' in html and headings[0].slug == "a"

    def test_render_page_wraps_content_in_the_shell(self):
        page = DocumentationRenderer.render_page("# Hello\n\nWorld.", "Hello", "docs/USAGE/hello.md")
        assert "<article>" in page and "Hello" in page
        assert re.search(r"<title>Hello · ", page)

    def test_slugify_is_exposed(self):
        assert DocumentationRenderer._slugify("Refresh Token Rotation") == "refresh-token-rotation"
