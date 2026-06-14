"""RED shared password-policy surface tests.

Trace: `.dev/sdd/changes/password-recovery-email-validation/tasks.md` task 1.5.
"""

from __future__ import annotations

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
WEAK_CANDIDATE = "aaaaaaaaaaaa"
VALID_PASSPHRASE = "lowercase words are acceptable when long enough"


def _source(path: str) -> str:
    return (ROOT / path).read_text()


def _function_block(source: str, start_marker: str, end_markers: tuple[str, ...]) -> str:
    start = source.index(start_marker)
    end_positions = [source.find(marker, start + len(start_marker)) for marker in end_markers]
    end_positions = [pos for pos in end_positions if pos != -1]
    end = min(end_positions) if end_positions else len(source)
    return source[start:end]


def test_shared_policy_helper_rejects_same_weak_candidate_and_accepts_passphrase_shape():
    import src.Util.password_security as password_security

    assert hasattr(password_security, "validate_password_policy")

    weak = password_security.validate_password_policy(WEAK_CANDIDATE, min_length=8)
    valid = password_security.validate_password_policy(VALID_PASSPHRASE, min_length=12)

    assert weak.is_valid is False
    assert "repeated_or_sequential" in weak.reason_codes or "common_password" in weak.reason_codes
    assert valid.is_valid is True
    assert valid.reason_codes == ()


@pytest.mark.parametrize(
    ("surface", "path", "start_marker", "end_markers"),
    [
        ("registration", "src/routes/auth.py", "async def register(", ("@router.post",)),
        ("public_reset_consume", "src/routes/auth.py", "async def reset_password_with_link(", ("# ---------------------------------------------------------------------------", "@router.post")),
        ("authenticated_change_password", "src/routes/auth.py", "password/change", ("@router.post", "# ---------------------------------------------------------------------------")),
        ("root_creation", "src/routes/user_types_auth.py", "async def create_root_user_endpoint(", ("@router.post",)),
        ("admin_creation", "src/routes/user_types_auth.py", "async def create_admin_user_endpoint(", ("@router.",)),
        ("admin_reset_link_consume", "src/routes/users.py", "async def reset_user_password(", ("@router.",)),
    ],
)
def test_all_password_setting_surfaces_call_shared_password_policy(surface, path, start_marker, end_markers):
    source = _source(path)
    assert start_marker in source, f"{surface} marker missing in {path}"
    block = _function_block(source, start_marker, end_markers)

    assert "assert_password_policy" in block or "validate_password_policy" in block
    assert "password_generator" not in block


def test_password_generator_strength_scoring_is_not_the_authoritative_auth_policy():
    auth_source = _source("src/routes/auth.py")
    user_type_source = _source("src/routes/user_types_auth.py")
    users_source = _source("src/routes/users.py")

    combined = "\n".join([auth_source, user_type_source, users_source])
    assert "validate_password_strength" not in combined
    assert "generate_temporary_password" not in combined
