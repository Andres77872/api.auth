"""
Unit tests for async activity logging via BackgroundTasks.
"""

from unittest.mock import MagicMock, patch
import pytest
from src.Util.activity_logger import ActivityLogger
from src.Util.error_handler import AuthorizationError, ErrorCode


# ==============================================================================
# 2.3.T1 — BackgroundTasks.add_task is used
# ==============================================================================

@pytest.mark.asyncio
async def test_background_tasks_used_instead_of_direct_call():
    from src.Util.Models import EnhancedUserLogin
    from src.Util.activity_logger import ActivityType
    import src.Util.decorators as decorators_mod

    mock_session = EnhancedUserLogin(
        user_hash="uhash_async",
        scope="project",
        project_hash="phash_async",
        project_name="Async Project",
        user_project_hash="",
        session_token="tok_async_test",
        session_length=3600,
        user_id="999",
        username="asyncuser",
        project_id="proj_999",
        groups=["async_group"],
        permissions=["async_perm"],
        available_projects=[],
        user_type="consumer",
    )

    mock_request = MagicMock()
    mock_request.state.session_validation = mock_session
    mock_request.client.host = "10.0.0.99"
    mock_request.headers.get.return_value = "async-agent"
    mock_request.method = "GET"

    mock_credentials = MagicMock()
    mock_credentials.credentials = "tok_async_test"

    mock_background_tasks = MagicMock()

    with patch.object(decorators_mod, 'ActivityLogger') as mock_logger:
        with patch.object(decorators_mod, 'ASYNC_ACTIVITY_LOGGING', True):
            with patch.object(decorators_mod, 'REQUEST_STATE_PASSTHROUGH', True):
                from src.Util.decorators import log_and_handle_errors

                @log_and_handle_errors(
                    operation_name="test_async_op",
                    activity_type=ActivityType.USER_LOGIN,
                    log_success=True,
                    require_auth=True,
                )
                async def test_endpoint(
                    credentials=None,
                    request=None,
                    log_context=None,
                    background_tasks=None,
                ):
                    return {"success": True}

                result = await test_endpoint(
                    credentials=mock_credentials,
                    request=mock_request,
                    background_tasks=mock_background_tasks,
                )

                assert result == {"success": True}
                # The logging must be deferred to the background, never awaited inline.
                mock_logger.log_activity.assert_not_called()
                mock_background_tasks.add_task.assert_called_once()


@pytest.mark.asyncio
async def test_background_tasks_passes_correct_args():
    from src.Util.Models import EnhancedUserLogin
    from src.Util.activity_logger import ActivityType
    import src.Util.decorators as decorators_mod

    mock_session = EnhancedUserLogin(
        user_hash="uhash_args",
        scope="project",
        project_hash="phash_args",
        project_name="Args Project",
        user_project_hash="",
        session_token="tok_args_test",
        session_length=3600,
        user_id="1111",
        username="argsuser",
        project_id="proj_1111",
        groups=["args_group"],
        permissions=["args_perm"],
        available_projects=[],
        user_type="consumer",
    )

    mock_request = MagicMock()
    mock_request.state.session_validation = mock_session
    mock_request.client.host = "192.168.1.1"
    mock_request.headers.get.return_value = "args-agent"
    mock_request.method = "POST"

    mock_credentials = MagicMock()
    mock_credentials.credentials = "tok_args_test"

    mock_background_tasks = MagicMock()

    with patch.object(decorators_mod, 'ASYNC_ACTIVITY_LOGGING', True):
        with patch.object(decorators_mod, 'REQUEST_STATE_PASSTHROUGH', True):
            from src.Util.decorators import log_and_handle_errors

            @log_and_handle_errors(
                operation_name="test_args_op",
                activity_type=ActivityType.ADMIN_ACTION,
                log_success=True,
                require_auth=True,
            )
            async def test_endpoint(
                credentials=None,
                request=None,
                log_context=None,
                background_tasks=None,
            ):
                return {"success": True}

            result = await test_endpoint(
                credentials=mock_credentials,
                request=mock_request,
                background_tasks=mock_background_tasks,
            )

            mock_background_tasks.add_task.assert_called_once()
            call_args = mock_background_tasks.add_task.call_args
            func = call_args[0][0]
            kwargs_from_call = call_args[1]

            assert func == ActivityLogger.log_activity
            assert kwargs_from_call["user_id"] == "1111"
            assert kwargs_from_call["activity_type"] == "admin_action"
            assert kwargs_from_call["project_id"] == "proj_1111"
            assert kwargs_from_call["ip_address"] == "192.168.1.1"
            assert kwargs_from_call["user_agent"] == "args-agent"
            assert kwargs_from_call["details"]["success"] is True


# ==============================================================================
# 2.3.T2 — Fallback to synchronous when BackgroundTasks unavailable
# ==============================================================================

@pytest.mark.asyncio
async def test_fallback_to_sync_when_no_background_tasks():
    from src.Util.Models import EnhancedUserLogin
    from src.Util.activity_logger import ActivityType
    import src.Util.decorators as decorators_mod

    mock_session = EnhancedUserLogin(
        user_hash="uhash_sync",
        scope="project",
        project_hash="phash_sync",
        project_name="Sync Fallback",
        user_project_hash="",
        session_token="tok_sync_fallback",
        session_length=3600,
        user_id="2222",
        username="syncuser",
        project_id="proj_2222",
        groups=["sync_group"],
        permissions=["sync_perm"],
        available_projects=[],
        user_type="consumer",
    )

    mock_request = MagicMock()
    mock_request.state.session_validation = mock_session
    mock_request.client.host = "10.0.0.2"
    mock_request.headers.get.return_value = "sync-agent"
    mock_request.method = "DELETE"

    mock_credentials = MagicMock()
    mock_credentials.credentials = "tok_sync_fallback"

    with patch.object(decorators_mod, 'ActivityLogger') as mock_logger:
        mock_logger.log_activity.return_value = True
        with patch.object(decorators_mod, 'ASYNC_ACTIVITY_LOGGING', True):
            with patch.object(decorators_mod, 'REQUEST_STATE_PASSTHROUGH', True):
                from src.Util.decorators import log_and_handle_errors

                @log_and_handle_errors(
                    operation_name="test_sync_fallback_op",
                    activity_type=ActivityType.USER_LOGOUT,
                    log_success=True,
                    require_auth=True,
                )
                async def test_endpoint(
                    credentials=None,
                    request=None,
                    log_context=None,
                ):
                    return {"success": True}

                result = await test_endpoint(
                    credentials=mock_credentials,
                    request=mock_request,
                )

                assert result == {"success": True}
                mock_logger.log_activity.assert_called_once()


@pytest.mark.asyncio
async def test_sync_when_async_disabled():
    from src.Util.Models import EnhancedUserLogin
    from src.Util.activity_logger import ActivityType
    import src.Util.decorators as decorators_mod

    mock_session = EnhancedUserLogin(
        user_hash="uhash_sync_disabled",
        scope="project",
        project_hash="phash_sync_disabled",
        project_name="Sync Disabled",
        user_project_hash="",
        session_token="tok_sync_disabled",
        session_length=3600,
        user_id="3333",
        username="syncdisabled",
        project_id="proj_3333",
        groups=[],
        permissions=[],
        available_projects=[],
        user_type="consumer",
    )

    mock_request = MagicMock()
    mock_request.state.session_validation = mock_session
    mock_request.client.host = "10.0.0.3"
    mock_request.headers.get.return_value = "sync-disabled-agent"
    mock_request.method = "GET"

    mock_credentials = MagicMock()
    mock_credentials.credentials = "tok_sync_disabled"

    mock_background_tasks = MagicMock()

    with patch.object(decorators_mod, 'ActivityLogger') as mock_logger:
        mock_logger.log_activity.return_value = True
        with patch.object(decorators_mod, 'ASYNC_ACTIVITY_LOGGING', False):
            with patch.object(decorators_mod, 'REQUEST_STATE_PASSTHROUGH', True):
                from src.Util.decorators import log_and_handle_errors

                @log_and_handle_errors(
                    operation_name="test_sync_disabled_op",
                    activity_type=ActivityType.ADMIN_ACTION,
                    log_success=True,
                    require_auth=True,
                )
                async def test_endpoint(
                    credentials=None,
                    request=None,
                    log_context=None,
                    background_tasks=None,
                ):
                    return {"success": True}

                result = await test_endpoint(
                    credentials=mock_credentials,
                    request=mock_request,
                    background_tasks=mock_background_tasks,
                )

                assert result == {"success": True}
                mock_logger.log_activity.assert_called_once()
                mock_background_tasks.add_task.assert_not_called()


@pytest.mark.asyncio
async def test_denied_login_activity_details_include_attempted_project_hash():
    """Denied unauthenticated login audit details include raw submitted project_hash."""
    from src.Util.activity_logger import ActivityType
    import src.Util.decorators as decorators_mod
    from src.Util.decorators import log_unauthenticated_operation

    mock_request = MagicMock()
    mock_request.client.host = "10.0.0.50"
    mock_request.headers.get.return_value = "audit-agent"
    mock_request.method = "POST"

    with patch.object(decorators_mod, "ActivityLogger") as mock_logger:
        @log_unauthenticated_operation(
            operation_name="user_login",
            activity_type=ActivityType.USER_LOGIN,
            extract_username=lambda *args, **kwargs: kwargs.get("username"),
        )
        async def denied_login(username=None, project_hash=None, request=None, log_context=None):
            raise AuthorizationError(
                message="Access denied to requested project",
                error_code=ErrorCode.PROJECT_ACCESS_DENIED,
            )

        with pytest.raises(AuthorizationError):
            await denied_login(
                username="consumer@example.com",
                project_hash="prj-secret-attempted-hash",
                request=mock_request,
            )

    details = mock_logger.log_activity.call_args.kwargs["details"]
    assert details["success"] is False
    assert details["operation"] == "user_login"
    assert details["project_hash"] == "prj-secret-attempted-hash"
