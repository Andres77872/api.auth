"""
Unit tests for decorator auth context construction.
"""

import pytest
from unittest.mock import MagicMock, patch


@pytest.mark.asyncio
async def test_decorator_uses_session_data_not_get_user_by_hash():
    """
    Verify the actual decorator code path: when session_data has username,
    get_user_by_hash is never called. Uses sentinel that raises to prove it.
    """
    from src.Util.Models import EnhancedUserLogin
    from src.Util.decorators import log_and_handle_errors

    # Use a real EnhancedUserLogin instance instead of MagicMock
    # so that Pydantic v2 receives actual string values, not Mock objects.
    session_data = EnhancedUserLogin(
        user_hash="uh-test-001",
        scope="project",
        project_hash="prj-test-001",
        project_name="Test Project",
        user_project_hash="",
        session_token="tok-decorator-test",
        session_length=3600,
        user_id="usr-test-001",
        username="testuser",
        project_id="1",
        groups=[],
        permissions=[],
        available_projects=[],
        user_type="consumer",
    )

    @log_and_handle_errors(
        operation_name="test_op",
        require_auth=True
    )
    async def dummy_endpoint(*args, **kwargs):
        return {"success": True}

    mock_request = MagicMock()
    mock_request.state.session_validation = None  # Force fallback to patched validate_session()
    mock_request.client.host = "127.0.0.1"
    mock_request.headers.get.return_value = "test-agent"
    mock_request.method = "GET"

    with patch("src.Util.decorators.validate_session", return_value=session_data), \
         patch("src.Util.decorators.get_user_by_hash", side_effect=RuntimeError("SHOULD NOT BE CALLED")) as mock_get_user:
        try:
            result = await dummy_endpoint(
                credentials=MagicMock(),
                request=mock_request
            )
            # If we got here, get_user_by_hash was never called
            mock_get_user.assert_not_called()
            assert result == {"success": True}
        except RuntimeError as e:
            if "SHOULD NOT BE CALLED" in str(e):
                pytest.fail("get_user_by_hash was called but should not have been")
            raise


@pytest.mark.asyncio
async def test_fallback_get_user_by_hash_when_no_username():
    """
    Verify the fallback path: when session_data does NOT have username
    (non-EnhancedUserLogin edge case), get_user_by_hash IS called.
    """
    from src.Util.decorators import log_and_handle_errors

    # session_data is a raw dict-like mock WITHOUT username.
    # Use spec=[] to prevent MagicMock from auto-creating 'username'
    # (which would make hasattr() return True and block the fallback path).
    session_data = MagicMock(spec=['user_id', 'user_hash', 'project_id', 'project_hash'])
    session_data.user_id = "usr-test-001"
    session_data.user_hash = "uh-test-001"
    session_data.project_id = "1"
    session_data.project_hash = "prj-test-001"
    # username is deliberately NOT set — hasattr(session_data, 'username')
    # returns False because 'username' is not in the spec.

    mock_user_data = MagicMock()
    mock_user_data.id = "usr-test-001"
    mock_user_data.username = "fallback-user"

    @log_and_handle_errors(
        operation_name="test_op",
        require_auth=True
    )
    async def dummy_endpoint(*args, **kwargs):
        return {"success": True}

    mock_request = MagicMock()
    mock_request.state.session_validation = None  # Force fallback to patched validate_session()
    mock_request.client.host = "127.0.0.1"
    mock_request.headers.get.return_value = "test-agent"
    mock_request.method = "GET"

    with patch("src.Util.decorators.validate_session", return_value=session_data), \
         patch("src.Util.decorators.get_user_by_hash", return_value=mock_user_data) as mock_get_user:
        result = await dummy_endpoint(
            credentials=MagicMock(),
            request=mock_request
        )

        # get_user_by_hash should have been called (fallback path)
        mock_get_user.assert_called_once_with("uh-test-001")
        assert result == {"success": True}
