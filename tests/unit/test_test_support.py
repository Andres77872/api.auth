"""Regression tests for the test harness safeguards themselves."""

from __future__ import annotations

import importlib

from tests.support import (
    ALL_DB_CONNECTION_PATCH_LOCATIONS,
    make_db_connection_mock,
    make_db_cursor_mock,
    patch_db_connections,
)


def _resolve(target: str):
    module_name, _, attribute = target.rpartition(".")
    return importlib.import_module(module_name), attribute


def test_cursor_double_terminates_result_set_drain_and_iteration():
    cursor = make_db_cursor_mock()

    assert cursor.nextset() is None
    assert cursor.nextset() is None
    assert list(cursor) == []
    assert cursor.fetchall() == []
    assert cursor.fetchmany() == []


def test_connection_double_uses_same_safe_cursor_in_both_access_styles():
    cursor = make_db_cursor_mock(fetchone={"id": "row-1"})
    connection = make_db_connection_mock(cursor)

    assert connection.cursor() is cursor
    with connection.cursor() as context_cursor:
        assert context_cursor is cursor
        assert context_cursor.fetchone() == {"id": "row-1"}


def test_every_required_db_patch_target_exists_and_is_restored():
    connection = make_db_connection_mock()
    originals = {}
    for target in ALL_DB_CONNECTION_PATCH_LOCATIONS:
        module, attribute = _resolve(target)
        assert hasattr(module, attribute), f"stale required DB patch target: {target}"
        originals[target] = getattr(module, attribute)

    patchers = patch_db_connections(connection)
    try:
        for target in ALL_DB_CONNECTION_PATCH_LOCATIONS:
            module, attribute = _resolve(target)
            assert getattr(module, attribute)() is connection
    finally:
        for patcher in reversed(patchers):
            patcher.stop()

    for target, original in originals.items():
        module, attribute = _resolve(target)
        assert getattr(module, attribute) is original
