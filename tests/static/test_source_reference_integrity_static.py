"""Names the source looks up at runtime must exist.

``ErrorCode.X`` for a missing member and ``callproc('sp_x')`` for a procedure the
schema never creates both fail only when the branch runs: the first as an
AttributeError (500) and the second as MySQL error 1305, which DB wrappers with a
default return turn into a silent ``False``/``None``.
"""

from __future__ import annotations

import re
from pathlib import Path

from src.Util.error_handler import ErrorCode


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"


def _source_references(pattern: str) -> dict[str, list[str]]:
    references: dict[str, list[str]] = {}
    for path in sorted(SRC.rglob("*.py")):
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for name in re.findall(pattern, line):
                references.setdefault(name, []).append(f"{path.relative_to(ROOT)}:{line_number}")
    return references


def _schema_procedures() -> set[str]:
    names: set[str] = set()
    for path in (ROOT / "schemas").rglob("*.sql"):
        for name in re.findall(r"CREATE\s+PROCEDURE\s+([`\w.]+)", path.read_text(encoding="utf-8"), re.I):
            names.add(name.strip("`").split(".")[-1])
    return names


def test_every_referenced_error_code_is_an_enum_member():
    referenced = _source_references(r"\bErrorCode\.([A-Z][A-Z0-9_]*)\b")
    missing = {name: sites for name, sites in referenced.items() if name not in ErrorCode.__members__}

    assert missing == {}


def test_every_called_procedure_exists_in_the_schema():
    called = _source_references(r"callproc\(\s*['\"](\w+)['\"]")
    undefined = set(called) - _schema_procedures()

    assert sorted(undefined) == []
