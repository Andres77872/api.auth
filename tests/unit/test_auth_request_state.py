"""
Unit tests for request.state session_validation pass-through.
"""

from unittest.mock import MagicMock, patch
from types import SimpleNamespace
import pytest
from starlette.responses import Response


# ==============================================================================
# 2.2.T1 — Decorator reads from request.state
# ==============================================================================

@pytest.mark.asyncio
async def test_decorator_reads_from_request_state():
    from src.Util.Models import EnhancedUserLogin
    import src.Util.decorators as decorators_mod

    mock_session = EnhancedUserLogin(
        user_hash="uhash_state",
        scope="project",
        project_hash="phash_state",
        project_name="State Project",
        user_project_hash="",
        session_token="tok_state_test",
        session_length=3600,
        user_id="555",
        username="stateuser",
        project_id="proj_555",
        groups=["state_group"],
        permissions=["state_perm"],
        available_projects=[],
        user_type="consumer",
    )

    mock_request = MagicMock()
    mock_request.state.session_validation = mock_session
    mock_request.client.host = "127.0.0.1"
    mock_request.headers.get.return_value = "test-agent"
    mock_request.method = "GET"

    mock_credentials = MagicMock()
    mock_credentials.credentials = "tok_state_test"

    with patch.object(decorators_mod, 'validate_session') as mock_validate:
        with patch.object(decorators_mod, 'REQUEST_STATE_PASSTHROUGH', True):
            from src.Util.decorators import log_and_handle_errors

            @log_and_handle_errors(
                operation_name="test_state_op",
                activity_type=None,
                log_success=False,
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
            mock_validate.assert_not_called()


@pytest.mark.asyncio
async def test_decorator_reads_from_request_state_with_activity_logging():
    from src.Util.Models import EnhancedUserLogin
    import src.Util.decorators as decorators_mod

    mock_session = EnhancedUserLogin(
        user_hash="uhash_log",
        scope="project",
        project_hash="phash_log",
        project_name="Log Project",
        user_project_hash="",
        session_token="tok_log_test",
        session_length=3600,
        user_id="666",
        username="loguser",
        project_id="proj_666",
        groups=["log_group"],
        permissions=["log_perm"],
        available_projects=[],
        user_type="consumer",
    )

    mock_request = MagicMock()
    mock_request.state.session_validation = mock_session
    mock_request.client.host = "10.0.0.1"
    mock_request.headers.get.return_value = "log-agent"
    mock_request.method = "POST"

    mock_credentials = MagicMock()
    mock_credentials.credentials = "tok_log_test"

    mock_background_tasks = MagicMock()

    with patch.object(decorators_mod, 'validate_session') as mock_validate:
        with patch.object(decorators_mod, 'REQUEST_STATE_PASSTHROUGH', True):
            with patch.object(decorators_mod, 'ASYNC_ACTIVITY_LOGGING', True):
                from src.Util.decorators import log_and_handle_errors
                from src.Util.activity_logger import ActivityType

                @log_and_handle_errors(
                    operation_name="test_state_log_op",
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
                mock_validate.assert_not_called()
                mock_background_tasks.add_task.assert_called_once()


# ==============================================================================
# 2.2.T2 — Decorator falls back to validate_session()
# ==============================================================================

@pytest.mark.asyncio
async def test_decorator_falls_back_when_state_missing():
    from src.Util.Models import EnhancedUserLogin
    import src.Util.decorators as decorators_mod

    mock_request = MagicMock()
    if hasattr(mock_request.state, 'session_validation'):
        del mock_request.state.session_validation
    mock_request.client.host = "127.0.0.1"
    mock_request.headers.get.return_value = "fallback-agent"
    mock_request.method = "GET"

    mock_credentials = MagicMock()
    mock_credentials.credentials = "tok_fallback"

    mock_session = EnhancedUserLogin(
        user_hash="uhash_fb",
        scope="project",
        project_hash="phash_fb",
        project_name="Fallback Project",
        user_project_hash="",
        session_token="tok_fallback",
        session_length=3600,
        user_id="777",
        username="fallbackuser",
        project_id="proj_777",
        groups=["fb_group"],
        permissions=["fb_perm"],
        available_projects=[],
        user_type="consumer",
    )

    with patch.object(decorators_mod, 'validate_session', return_value=mock_session) as mock_validate:
        with patch.object(decorators_mod, 'REQUEST_STATE_PASSTHROUGH', True):
            from src.Util.decorators import log_and_handle_errors

            @log_and_handle_errors(
                operation_name="test_fallback_op",
                activity_type=None,
                log_success=False,
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
            mock_validate.assert_called_once_with("tok_fallback")


@pytest.mark.asyncio
async def test_decorator_falls_back_when_passthrough_disabled():
    from src.Util.Models import EnhancedUserLogin
    import src.Util.decorators as decorators_mod

    mock_request = MagicMock()
    if hasattr(mock_request.state, 'session_validation'):
        del mock_request.state.session_validation
    mock_request.client.host = "127.0.0.1"
    mock_request.headers.get.return_value = "disabled-agent"
    mock_request.method = "GET"

    mock_credentials = MagicMock()
    mock_credentials.credentials = "tok_disabled"

    mock_session = EnhancedUserLogin(
        user_hash="uhash_dis",
        scope="project",
        project_hash="phash_dis",
        project_name="Disabled Project",
        user_project_hash="",
        session_token="tok_disabled",
        session_length=3600,
        user_id="888",
        username="disableduser",
        project_id="proj_888",
        groups=[],
        permissions=[],
        available_projects=[],
        user_type="consumer",
    )

    with patch.object(decorators_mod, 'validate_session', return_value=mock_session) as mock_validate:
        with patch.object(decorators_mod, 'REQUEST_STATE_PASSTHROUGH', False):
            from src.Util.decorators import log_and_handle_errors

            @log_and_handle_errors(
                operation_name="test_disabled_op",
                activity_type=None,
                log_success=False,
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
            mock_validate.assert_called_once_with("tok_disabled")


@pytest.mark.asyncio
async def test_auth_context_middleware_uses_session_cookie_for_state():
    from src.Util.Models import EnhancedUserLogin
    from src.middleware.auth_context import AuthContextMiddleware

    mock_session = EnhancedUserLogin(
        user_hash="uhash_cookie",
        scope="project",
        project_hash="phash_cookie",
        project_name="Cookie Project",
        user_project_hash="",
        session_token="jwt.cookie.access",
        session_length=3600,
        user_id="999",
        username="cookieuser",
        project_id="proj_999",
        groups=["cookie_group"],
        permissions=["cookie_perm"],
        available_projects=[],
        user_type="consumer",
    )

    request = MagicMock()
    request.headers = {}
    request.cookies = {"session_token": "jwt.cookie.access"}
    request.state = SimpleNamespace()

    async def call_next(req):
        return Response("ok")

    middleware = AuthContextMiddleware(app=MagicMock())
    with patch("src.Util.db.db_enhanced.validate_session", return_value=mock_session) as mock_validate:
        await middleware.dispatch(request, call_next)

    mock_validate.assert_called_once_with("jwt.cookie.access")
    assert request.state.user_id == "999"
    assert request.state.auth_method == "session"
    assert request.state.session_validation == mock_session
