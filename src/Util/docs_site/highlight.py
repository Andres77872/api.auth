"""Tiny regex syntax highlighter for documentation code blocks.

Covers the languages the usage docs actually fence (shell, JSON, HTTP, Python,
JavaScript/TypeScript, SQL, YAML and dotenv). Each language is an ordered list of
``(token_class, pattern)`` rules compiled into one alternation; text between
matches is escaped verbatim. Anything unknown is returned escaped and unstyled.
"""

from __future__ import annotations

import html
import re
from functools import lru_cache

# Canonical language keys and the labels shown in the code-block header.
LANGUAGE_ALIASES = {
    "sh": "bash",
    "shell": "bash",
    "zsh": "bash",
    "console": "bash",
    "curl": "bash",
    "jsonc": "json",
    "json5": "json",
    "js": "javascript",
    "jsx": "javascript",
    "mjs": "javascript",
    "ts": "typescript",
    "tsx": "typescript",
    "py": "python",
    "yml": "yaml",
    "dotenv": "env",
    "ini": "env",
    "plaintext": "text",
    "txt": "text",
    "": "text",
}

LANGUAGE_LABELS = {
    "bash": "Shell",
    "json": "JSON",
    "http": "HTTP",
    "python": "Python",
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "sql": "SQL",
    "yaml": "YAML",
    "env": ".env",
    "text": "Text",
}

_JS_KEYWORDS = (
    "async|await|break|case|catch|class|const|continue|default|delete|do|else|export|extends|"
    "finally|for|from|function|if|import|in|instanceof|interface|let|new|of|return|switch|throw|"
    "try|type|typeof|var|void|while|yield|as|implements|enum|readonly|private|public|protected"
)
_PY_KEYWORDS = (
    "and|as|assert|async|await|break|class|continue|def|del|elif|else|except|finally|for|from|"
    "global|if|import|in|is|lambda|nonlocal|not|or|pass|raise|return|try|while|with|yield"
)
_SQL_KEYWORDS = (
    "select|from|where|and|or|not|insert|into|values|update|set|delete|create|table|procedure|"
    "function|view|trigger|index|unique|primary|key|foreign|references|join|left|right|inner|"
    "outer|on|as|group|by|order|limit|offset|call|begin|end|declare|if|then|else|elseif|case|"
    "when|null|is|in|exists|distinct|having|union|all|default|return|returns|drop|alter|add|"
    "column|constraint|cascade|using|like|between|asc|desc|count|sum|max|min|now|interval|"
    "varchar|char|int|bigint|tinyint|boolean|text|json|datetime|timestamp|binary|varbinary|enum"
)

_STRING_DQ = r'"(?:[^"\\\n]|\\.)*"'
_STRING_SQ = r"'(?:[^'\\\n]|\\.)*'"
_NUMBER = r"(?<![\w.])-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b"

_RULES: dict[str, list[tuple[str, str]]] = {
    "json": [
        ("c", r"//[^\n]*|/\*[\s\S]*?\*/"),
        ("p", _STRING_DQ + r"(?=\s*:)"),
        ("s", _STRING_DQ),
        ("n", _NUMBER),
        ("b", r"\b(?:true|false|null)\b"),
        ("o", r"\.\.\.|[{}\[\],:]"),
    ],
    "bash": [
        ("c", r"(?<![^\s])#[^\n]*"),
        ("s", r"'[^']*'|\"(?:[^\"\\]|\\.)*\""),
        ("v", r"\$\{[^}\n]+\}|\$[A-Za-z_][A-Za-z0-9_]*|\$\([^)\n]*\)"),
        ("u", r"https?://[^\s\"'\\]+"),
        (
            "k",
            r"(?m)(?<![\w-])(?:curl|export|echo|cd|docker|compose|python3?|pip|uvicorn|pytest|git|jq|"
            r"source|openssl|mysql|redis-cli|stripe|npm|pnpm|npx|node|cat|grep|set|unset|sleep|"
            r"for|in|do|done|if|then|else|fi|while)(?![\w-])",
        ),
        ("f", r"(?<=[\s(])--?[A-Za-z][\w-]*"),
        ("o", r"\\\n|\|\||&&|\||>>?|<"),
    ],
    "http": [
        ("k", r"(?m)^(?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\b"),
        ("b", r"HTTP/\d(?:\.\d)?(?:\s+\d{3})?"),
        ("p", r"(?m)^[A-Za-z][\w-]*(?=:\s)"),
        ("s", _STRING_DQ),
        ("n", _NUMBER),
        ("o", r"[{}\[\],]"),
    ],
    "python": [
        ("c", r"#[^\n]*"),
        ("s", r'[rbfuRBFU]{0,2}(?:"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'|' + _STRING_DQ + "|" + _STRING_SQ + ")"),
        ("d", r"(?m)^\s*@[\w.]+"),
        ("k", r"\b(?:" + _PY_KEYWORDS + r")\b"),
        ("b", r"\b(?:True|False|None|self|cls)\b"),
        ("n", _NUMBER),
    ],
    "javascript": [
        ("c", r"//[^\n]*|/\*[\s\S]*?\*/"),
        ("s", r"`(?:[^`\\]|\\.)*`|" + _STRING_DQ + "|" + _STRING_SQ),
        ("k", r"\b(?:" + _JS_KEYWORDS + r")\b"),
        ("b", r"\b(?:true|false|null|undefined|this|NaN)\b"),
        ("n", _NUMBER),
    ],
    "sql": [
        ("c", r"--[^\n]*|/\*[\s\S]*?\*/"),
        ("s", _STRING_SQ),
        ("k", r"(?i)\b(?:" + _SQL_KEYWORDS + r")\b"),
        ("n", _NUMBER),
        ("v", r"@\w+"),
    ],
    "yaml": [
        ("c", r"(?<![^\s])#[^\n]*"),
        ("p", r"(?m)^\s*-?\s*[\w.-]+(?=:(?:\s|$))"),
        ("s", _STRING_DQ + "|" + _STRING_SQ),
        ("b", r"\b(?:true|false|null|yes|no)\b"),
        ("n", _NUMBER),
    ],
    "env": [
        ("c", r"(?m)^\s*#[^\n]*"),
        ("p", r"(?m)^\s*(?:export\s+)?[A-Za-z_][A-Za-z0-9_]*(?==)"),
        ("s", _STRING_DQ + "|" + _STRING_SQ),
        ("o", r"="),
    ],
}
_RULES["typescript"] = _RULES["javascript"]


def normalize_language(lang: str | None) -> str:
    key = (lang or "").strip().lower()
    return LANGUAGE_ALIASES.get(key, key)


def language_label(lang: str) -> str:
    return LANGUAGE_LABELS.get(lang, lang.upper() if len(lang) <= 4 else lang.capitalize())


@lru_cache(maxsize=None)
def _compiled(lang: str) -> re.Pattern[str] | None:
    rules = _RULES.get(lang)
    if not rules:
        return None
    # Inline flags such as (?m)/(?i) must be scoped per alternative.
    parts = []
    for index, (_, pattern) in enumerate(rules):
        flags = ""
        match = re.match(r"^\(\?([aiLmsux]+)\)", pattern)
        if match:
            flags = match.group(1)
            pattern = pattern[match.end():]
        body = f"(?{flags}:{pattern})" if flags else f"(?:{pattern})"
        parts.append(f"(?P<t{index}>{body})")
    return re.compile("|".join(parts))


def highlight(code: str, lang: str) -> str:
    """Return HTML-escaped ``code`` with ``<span class="tk-*">`` tokens."""

    pattern = _compiled(lang)
    if pattern is None:
        return html.escape(code, quote=False)

    rules = _RULES[lang]
    out: list[str] = []
    position = 0
    for match in pattern.finditer(code):
        start, end = match.span()
        if start == end:
            continue
        if start > position:
            out.append(html.escape(code[position:start], quote=False))
        index = int(match.lastgroup[1:])  # type: ignore[index]
        token = html.escape(match.group(0), quote=False)
        out.append(f'<span class="tk-{rules[index][0]}">{token}</span>')
        position = end
    out.append(html.escape(code[position:], quote=False))
    return "".join(out)
