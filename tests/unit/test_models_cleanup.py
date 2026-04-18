"""
Slice 13 (Strategy Slice 13) — Dead UserGroupProject Model Removal

Characterization → cleanup: Confirm UserGroupProject in src/Util/Models.py
is never instantiated anywhere. Remove it. Verify no imports break.

Proof layer: Layer 1 (unit)
Trace: SQL architecture RISK 1
"""

import ast
import importlib
from pathlib import Path
from unittest.mock import patch

import pytest

# ─── Characterization: Prove the model is dead ───────────────────────────────

def test_user_group_project_is_never_instantiated():
    """UserGroupProject must not be instantiated anywhere in the codebase."""
    src_dir = Path(__file__).parent.parent.parent / "src"
    instantiation_sites = []

    for py_file in src_dir.rglob("*.py"):
        try:
            source = py_file.read_text()
            tree = ast.parse(source)
        except (SyntaxError, UnicodeDecodeError):
            continue

        for node in ast.walk(tree):
            # Check for UserGroupProject() calls
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id == "UserGroupProject":
                    instantiation_sites.append(f"{py_file}:{node.lineno}")
                elif isinstance(node.func, ast.Attribute) and node.func.attr == "UserGroupProject":
                    instantiation_sites.append(f"{py_file}:{node.lineno}")

    assert len(instantiation_sites) == 0, (
        f"UserGroupProject is instantiated at: {instantiation_sites}"
    )


def test_user_group_project_is_not_imported_in_db_user_groups():
    """After cleanup, UserGroupProject should NOT be imported in db_user_groups.py."""
    db_user_groups_path = Path(__file__).parent.parent.parent / "src" / "Util" / "db" / "db_user_groups.py"
    source = db_user_groups_path.read_text()

    assert "UserGroupProject" not in source, (
        "UserGroupProject should be removed from db_user_groups.py"
    )


# ─── Cleanup: Remove the dead model ─────────────────────────────────────────

def test_user_group_project_removed_from_models():
    """After cleanup, UserGroupProject should NOT exist in Models.py."""
    models_path = Path(__file__).parent.parent.parent / "src" / "Util" / "Models.py"
    source = models_path.read_text()

    # The class definition should be removed
    assert "class UserGroupProject" not in source, (
        "UserGroupProject class should be removed from Models.py"
    )


def test_user_group_project_removed_from_db_user_groups_imports():
    """After cleanup, UserGroupProject should NOT be imported in db_user_groups.py."""
    db_user_groups_path = Path(__file__).parent.parent.parent / "src" / "Util" / "db" / "db_user_groups.py"
    source = db_user_groups_path.read_text()

    assert "UserGroupProject" not in source, (
        "UserGroupProject should be removed from imports in db_user_groups.py"
    )


def test_models_module_imports_without_user_group_project():
    """src.Util.Models must import successfully after UserGroupProject removal."""
    # Force reimport to pick up any changes
    import sys
    if "src.Util.Models" in sys.modules:
        del sys.modules["src.Util.Models"]

    # This should not raise
    from src.Util.Models import User, Project, UserGroup, ProjectGroup
    assert User is not None
    assert Project is not None
    assert UserGroup is not None
    assert ProjectGroup is not None


def test_db_user_groups_imports_without_user_group_project():
    """src.Util.db.db_user_groups must import successfully after UserGroupProject removal."""
    import sys
    if "src.Util.db.db_user_groups" in sys.modules:
        del sys.modules["src.Util.db.db_user_groups"]

    # This should not raise
    from src.Util.db import db_user_groups
    assert hasattr(db_user_groups, "get_user_accessible_projects")
    assert hasattr(db_user_groups, "get_user_groups_for_user")
