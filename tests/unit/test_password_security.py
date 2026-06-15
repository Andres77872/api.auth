"""Unit tests for src/Util/password_security.py — Slice 3.

Argon2id hashing + password policy. No external services needed.
Note: Argon2 is computationally expensive (~1s per hash), so tests are fewer.
"""

import pytest

from src.Util.password_security import (
    PasswordManager,
    hash_password,
    verify_password,
    needs_rehash,
    password_manager,
)


# ─── hash_password ──────────────────────────────────────────────────────────

class TestHashPassword:
    def test_returns_argon2_hash(self):
        h = hash_password("test_password")
        assert h.startswith("$argon2")

    def test_different_passwords_different_hashes(self):
        h1 = hash_password("password1")
        h2 = hash_password("password2")
        assert h1 != h2

    def test_same_password_different_hashes_due_to_salt(self):
        h1 = hash_password("same_password")
        h2 = hash_password("same_password")
        assert h1 != h2  # Different salts

    def test_class_method_produces_argon2(self):
        pm = PasswordManager()
        h = pm.hash_password("test")
        assert h.startswith("$argon2")


# ─── verify_password ────────────────────────────────────────────────────────

class TestVerifyPassword:
    def test_correct_password_returns_true(self):
        h = hash_password("correct_password")
        assert verify_password("correct_password", h) is True

    def test_wrong_password_returns_false(self):
        h = hash_password("correct_password")
        assert verify_password("wrong_password", h) is False

    def test_empty_password_against_hash(self):
        h = hash_password("not_empty")
        assert verify_password("", h) is False

    def test_case_sensitive(self):
        h = hash_password("Password123")
        assert verify_password("password123", h) is False

    def test_class_method_verification(self):
        pm = PasswordManager()
        h = pm.hash_password("test")
        assert pm.verify_password("test", h) is True
        assert pm.verify_password("wrong", h) is False


# ─── needs_rehash ───────────────────────────────────────────────────────────

class TestNeedsRehash:
    def test_argon2_hash_does_not_need_rehash(self):
        h = hash_password("password")
        # Current params match, so should not need rehash
        assert needs_rehash(h) is False

    def test_invalid_string_needs_rehash(self):
        assert needs_rehash("not_a_hash_at_all") is True


# ─── password policy contract (password-recovery-email-validation 1.1) ───────

def _validate_policy(candidate: str, **context):
    """Call the future shared password-policy API without breaking collection."""

    import src.Util.password_security as password_security

    assert hasattr(password_security, "validate_password_policy")
    return password_security.validate_password_policy(candidate, **context)


def _assert_policy_safe(result, candidate: str, *context_values: str) -> None:
    serialized = repr(result).lower()
    assert candidate.lower() not in serialized
    for value in context_values:
        assert value.lower() not in serialized


class TestPasswordPolicyContracts:
    def test_configurable_minimum_length_rejects_too_short_passwords_without_echo(self):
        candidate = "short7"

        result = _validate_policy(candidate, min_length=12)

        assert result.is_valid is False
        assert "too_short" in result.reason_codes
        assert result.min_length == 12
        _assert_policy_safe(result, candidate)

    def test_common_password_denylist_rejects_configured_values_without_echo(self):
        candidate = "common-contract-candidate"

        result = _validate_policy(candidate, min_length=8, extra_blocklist={candidate})

        assert result.is_valid is False
        assert "common_password" in result.reason_codes
        _assert_policy_safe(result, candidate)

    def test_username_and_email_derived_passwords_are_rejected_without_identifier_echo(self):
        candidate = "andres-credential-rotation-2026"
        username = "andres"
        email = "andres.contract@example.test"

        result = _validate_policy(candidate, username=username, email=email, min_length=8)

        assert result.is_valid is False
        assert "obvious_identifier_derivation" in result.reason_codes
        _assert_policy_safe(result, candidate, username, email)

    @pytest.mark.parametrize(
        "candidate",
        [
            "aaaaaaaaaaaaaaaa",
            "abcdefghijklmnop",
            "1234567890123456",
        ],
    )
    def test_repeated_or_sequential_passwords_are_rejected(self, candidate):
        result = _validate_policy(candidate, min_length=8)

        assert result.is_valid is False
        assert "repeated_or_sequential" in result.reason_codes
        _assert_policy_safe(result, candidate)

    @pytest.mark.parametrize(
        "candidate",
        [
            "lowercase words make a long memorable phrase",
            "nouppercaseordigitbutlongenough",
            "with spaces but no symbols or digits",
        ],
    )
    def test_long_passphrases_are_accepted_without_character_class_requirements(self, candidate):
        result = _validate_policy(candidate, min_length=12)

        assert result.is_valid is True
        assert result.reason_codes == ()

    def test_assert_password_policy_raises_sanitized_weak_password_error(self):
        import src.Util.password_security as password_security

        candidate = "bbbbbbbbbbbbbbbb"

        assert hasattr(password_security, "assert_password_policy")
        with pytest.raises(Exception) as exc_info:
            password_security.assert_password_policy(candidate, min_length=8)

        serialized = repr(exc_info.value).lower()
        assert "weak_password" in serialized or "val_3007" in serialized
        assert candidate not in serialized
