"""Drift guards for docs/llms.txt, the template served at GET /llms.txt.

The file follows https://llmstxt.org: one H1, a blockquote summary, then H2 sections.
These tests read source text instead of importing the FastAPI application, so they stay
deterministic and need no MySQL or Redis.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LLMS_TXT = ROOT / "docs" / "llms.txt"

PLACEHOLDERS = {"{{BASE_URL}}", "{{VERSION}}"}
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)\s]+)\)")
LIST_LINK = re.compile(r"^- \[[^\]]+\]\([^)\s]+\)(?:: .+)?$")


def _text() -> str:
    return LLMS_TXT.read_text(encoding="utf-8")


def test_structure_follows_the_llms_txt_format():
    # Code fences hold bash comments that start with "# "; they are not headings.
    prose = re.sub(r"^```.*?^```$", "", _text(), flags=re.MULTILINE | re.DOTALL)
    lines = prose.splitlines()

    assert lines[0].startswith("# "), "the first line must be the H1 title"
    assert [line for line in lines if re.match(r"^# ", line)] == [lines[0]], "exactly one H1"
    assert lines[1] == "" and lines[2].startswith("> "), "a blockquote summary follows the H1"
    assert not _text().startswith(("---", "{")), "no front matter outside the llms.txt grammar"

    first_h2 = next(index for index, line in enumerate(lines) if line.startswith("## "))
    preamble = lines[:first_h2]
    assert not [line for line in preamble if line.startswith("#")][1:], "no headings before the first H2"

    sections = re.split(r"^## ", prose, flags=re.MULTILINE)
    headings = [section.splitlines()[0] for section in sections[1:]]
    assert headings[-1] == "Optional", "the Optional section comes last"
    for section in sections[1:]:
        if section.splitlines()[0] in {"Docs", "Optional"}:
            items = [line for line in section.splitlines()[1:] if line.strip()]
            assert items and all(LIST_LINK.match(item) for item in items), section.splitlines()[0]


def test_only_known_placeholders_are_used():
    assert set(re.findall(r"\{\{[^}]*\}\}", _text())) == PLACEHOLDERS


def test_links_are_absolute_and_documentation_links_resolve():
    failures = []
    for target in MARKDOWN_LINK.findall(_text()):
        if target.startswith("https://"):
            continue
        if not target.startswith("{{BASE_URL}}/"):
            failures.append(f"relative link {target}")
            continue
        path = target.removeprefix("{{BASE_URL}}").partition("?")[0]
        if path.startswith("/documentation/") and not (
            ROOT / "docs" / path.removeprefix("/documentation/")
        ).is_file():
            failures.append(f"missing documentation page {target}")

    assert failures == []


def test_json_code_fences_contain_valid_json():
    for block in re.findall(r"```json\n(.*?)```", _text(), re.DOTALL):
        json.loads(block)
