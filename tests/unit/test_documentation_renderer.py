"""Unit tests for src/Util/documentation_renderer.py — Markdown rendering.

Tests cover:
- Plain blockquotes (no crash on missing callout marker)
- Callout blockquotes (!warning, !info, !tip, !danger)
- Edge cases: empty blockquotes, mixed content
"""

import pytest
from src.Util.documentation_renderer import DocumentationRenderer


class TestBlockquoteRendering:
    """Tests for blockquote/callout markdown rendering."""

    def test_plain_blockquote_no_crash(self):
        """Plain blockquotes without callout markers should render without crash."""
        renderer = DocumentationRenderer()
        html, _ = renderer.render_markdown("> This is a plain blockquote")
        assert "<blockquote>" in html
        assert "This is a plain blockquote" in html

    def test_plain_blockquote_with_formatting(self):
        """Plain blockquotes with bold/italic should render correctly."""
        renderer = DocumentationRenderer()
        html, _ = renderer.render_markdown("> **Important**: Read this carefully")
        assert "<blockquote>" in html
        assert "<strong>Important</strong>" in html

    def test_warning_callout(self):
        """!warning callouts should render with warning styling."""
        renderer = DocumentationRenderer()
        html, _ = renderer.render_markdown("> !warning This is a warning")
        assert "callout-warning" in html
        assert "callout-icon" in html
        assert "This is a warning" in html

    def test_warn_callout_alias(self):
        """!warn should be treated as !warning."""
        renderer = DocumentationRenderer()
        html, _ = renderer.render_markdown("> !warn Short warning")
        assert "callout-warning" in html
        assert "Short warning" in html

    def test_info_callout(self):
        """!info callouts should render with info styling."""
        renderer = DocumentationRenderer()
        html, _ = renderer.render_markdown("> !info This is informational")
        assert "callout-info" in html
        assert "This is informational" in html

    def test_note_callout_alias(self):
        """!note should be treated as !info."""
        renderer = DocumentationRenderer()
        html, _ = renderer.render_markdown("> !note This is a note")
        assert "callout-info" in html

    def test_tip_callout(self):
        """!tip callouts should render with success styling."""
        renderer = DocumentationRenderer()
        html, _ = renderer.render_markdown("> !tip Pro tip here")
        assert "callout-success" in html
        assert "Pro tip here" in html

    def test_danger_callout(self):
        """!danger callouts should render with error styling."""
        renderer = DocumentationRenderer()
        html, _ = renderer.render_markdown("> !danger Critical issue")
        assert "callout-error" in html
        assert "Critical issue" in html

    def test_error_callout_alias(self):
        """!error should be treated as !danger."""
        renderer = DocumentationRenderer()
        html, _ = renderer.render_markdown("> !error Something failed")
        assert "callout-error" in html

    def test_multiple_blockquotes(self):
        """Multiple blockquotes should all render correctly."""
        renderer = DocumentationRenderer()
        md = """> First blockquote
> !warning Warning here
> Second plain blockquote"""
        html, _ = renderer.render_markdown(md)
        assert html.count("<blockquote>") == 2
        assert "callout-warning" in html

    def test_no_double_processing(self):
        """Blockquotes should not be double-wrapped."""
        renderer = DocumentationRenderer()
        html, _ = renderer.render_markdown("> Test content")
        assert html.count("<blockquote>") == 1


class TestEdgeCases:
    """Tests for edge cases in markdown rendering."""

    def test_empty_blockquote_line(self):
        """An empty blockquote still renders as a blockquote, not a crash or a stray '>'."""
        renderer = DocumentationRenderer()
        html, _ = renderer.render_markdown("> ")
        assert "blockquote" in html

    def test_blockquote_with_link(self):
        """Blockquotes with links should render links correctly."""
        renderer = DocumentationRenderer()
        html, _ = renderer.render_markdown("> See [docs](getting-started.md) for more")
        assert "<blockquote>" in html
        assert '<a href="getting-started.md">docs</a>' in html

    def test_callout_with_markdown_formatting(self):
        """Callouts with markdown formatting should preserve it."""
        renderer = DocumentationRenderer()
        html, _ = renderer.render_markdown("> !warning **Bold** and *italic* warning")
        assert "callout-warning" in html
        assert "<strong>Bold</strong>" in html
        assert "<em>italic</em>" in html