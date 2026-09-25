"""`POST /system/cache/invalidate/project/{project_id}` accepts real `proj-...` IDs.

Regression: the path parameter was declared ``int``, so every real project ID
(``proj-<uuid>``) was rejected with 400 and the endpoint could never be used.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.routes import system


PROJECT_ID = "proj-550e8400-e29b-41d4-a716-446655440000"


def _project_id_param():
    route = next(
        r for r in system.router.routes if getattr(r, "path", "").endswith("/cache/invalidate/project/{project_id}")
    )
    return route.dependant.path_params[0]


def test_real_project_ids_pass_path_validation():
    value, errors = _project_id_param().validate(PROJECT_ID, {}, loc=("path", "project_id"))
    assert errors is None
    assert value == PROJECT_ID


@pytest.mark.parametrize("value", ["*", "proj-*", "proj-[a]", "proj?", "a" * 129])
def test_glob_characters_cannot_widen_the_invalidation_pattern(value):
    _, errors = _project_id_param().validate(value, {}, loc=("path", "project_id"))
    assert errors


@pytest.mark.asyncio
async def test_handler_invalidates_the_string_project_id(monkeypatch):
    cache = MagicMock()
    cache.invalidate_project_cache.return_value = True
    monkeypatch.setattr(system, "cache_manager", cache)
    monkeypatch.setattr(system, "get_user_type", lambda user_id: "admin")
    monkeypatch.setattr(system, "is_root_user", lambda user_id: False)

    response = await system.invalidate_project_cache.__wrapped__(
        project_id=PROJECT_ID,
        credentials=None,
        log_context=SimpleNamespace(user_id="admin-1", user_hash="usr-admin"),
    )

    cache.invalidate_project_cache.assert_called_once_with(PROJECT_ID)
    assert response.success is True
    assert PROJECT_ID in response.message
