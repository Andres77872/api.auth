"""Unit tests for src/Util/password_generator.py — Slice 2.

Pure logic using stdlib `secrets` and `string`, no external deps.
"""

import re

import pytest

from src.Util.password_generator import (
    PasswordGenerator,
    generate_temporary_password,
    generate_reset_token,
    create_password_reset_data,
    create_password_reset,
    validate_password_strength,
)


# ─── generate_temporary_password ────────────────────────────────────────────

class TestGenerateTemporaryPassword:
    def test_default_length_is_12(self):
        pw = generate_temporary_password()
        assert len(pw) == 12

    def test_explicit_length_8(self):
        pw = generate_temporary_password(8)
        assert len(pw) == 8

    def test_explicit_length_32(self):
        pw = generate_temporary_password(32)
        assert len(pw) == 32

    def test_length_below_minimum_clamps_to_8(self):
        pw = generate_temporary_password(5)
        assert len(pw) == 8

    def test_length_above_maximum_clamps_to_32(self):
        pw = generate_temporary_password(50)
        assert len(pw) == 32

    def test_contains_uppercase(self):
        pw = generate_temporary_password()
        assert any(c.isupper() for c in pw)

    def test_contains_lowercase(self):
        pw = generate_temporary_password()
        assert any(c.islower() for c in pw)

    def test_contains_digit(self):
        pw = generate_temporary_password()
        assert any(c.isdigit() for c in pw)

    def test_contains_special_char(self):
        pw = generate_temporary_password()
        special = "!@#$%^&*"
        assert any(c in special for c in pw)

    def test_boundary_minimum_length_8(self):
        pw = generate_temporary_password(8)
        assert len(pw) == 8
        assert any(c.isupper() for c in pw)
        assert any(c.islower() for c in pw)
        assert any(c.isdigit() for c in pw)
        assert any(c in "!@#$%^&*" for c in pw)

    def test_boundary_maximum_length_32(self):
        pw = generate_temporary_password(32)
        assert len(pw) == 32
        assert any(c.isupper() for c in pw)
        assert any(c.islower() for c in pw)
        assert any(c.isdigit() for c in pw)
        assert any(c in "!@#$%^&*" for c in pw)

    def test_uniqueness_across_calls(self):
        passwords = {generate_temporary_password() for _ in range(100)}
        assert len(passwords) == 100

    def test_class_method_same_as_function(self):
        # Both should produce valid passwords of correct length
        pw1 = PasswordGenerator.generate_temporary_password(16)
        pw2 = generate_temporary_password(16)
        assert len(pw1) == 16
        assert len(pw2) == 16


# ─── generate_reset_token ───────────────────────────────────────────────────

class TestGenerateResetToken:
    def test_returns_string(self):
        token = generate_reset_token()
        assert isinstance(token, str)

    def test_is_url_safe(self):
        token = generate_reset_token()
        # URL-safe base64: alphanumeric + - and _
        assert re.match(r"^[A-Za-z0-9_-]+$", token)

    def test_reasonable_length(self):
        # secrets.token_urlsafe(32) produces 43 chars
        token = generate_reset_token()
        assert len(token) == 43

    def test_uniqueness_across_calls(self):
        tokens = {generate_reset_token() for _ in range(100)}
        assert len(tokens) == 100

    def test_class_method_same_as_function(self):
        t1 = PasswordGenerator.generate_reset_token()
        t2 = generate_reset_token()
        assert len(t1) == len(t2) == 43


# ─── create_password_reset_data ─────────────────────────────────────────────

class TestCreatePasswordResetData:
    def test_returns_dict_with_expected_keys(self):
        data = create_password_reset_data("usr-123")
        assert "reset_token" in data
        assert "temporary_password" in data
        assert "user_id" in data
        assert "expires_at" in data
        assert "created_at" in data

    def test_user_id_is_set(self):
        data = create_password_reset_data("usr-test-abc")
        assert data["user_id"] == "usr-test-abc"

    def test_temporary_password_is_valid(self):
        data = create_password_reset_data("usr-123")
        pw = data["temporary_password"]
        assert len(pw) == 12  # default length
        assert any(c.isupper() for c in pw)
        assert any(c.islower() for c in pw)
        assert any(c.isdigit() for c in pw)

    def test_reset_token_is_url_safe(self):
        data = create_password_reset_data("usr-123")
        assert re.match(r"^[A-Za-z0-9_-]+$", data["reset_token"])

    def test_expiry_hours_default_24(self):
        from datetime import datetime, timedelta

        data = create_password_reset_data("usr-123")
        # expires_at should be roughly 24 hours after created_at
        diff = data["expires_at"] - data["created_at"]
        assert diff.total_seconds() == pytest.approx(24 * 3600, abs=2)

    def test_expiry_hours_custom(self):
        data = create_password_reset_data("usr-123", expiry_hours=48)
        diff = data["expires_at"] - data["created_at"]
        assert diff.total_seconds() == pytest.approx(48 * 3600, abs=2)

    def test_convenience_function_alias(self):
        # create_password_reset should delegate to create_password_reset_data
        data = create_password_reset("usr-456")
        assert data["user_id"] == "usr-456"
        assert "reset_token" in data


# ─── validate_password_strength ─────────────────────────────────────────────

class TestValidatePasswordStrength:
    def test_empty_string_score_zero(self):
        result = validate_password_strength("")
        assert result["score"] == 0
        assert result["strength"] == "weak"
        assert result["is_valid"] is False

    def test_all_requirements_met_minimum(self):
        # "Ab1!" → length>=8: No (4 chars), but has upper, lower, digit, special
        result = validate_password_strength("Ab1!")
        # length < 8: 0, upper: 20, lower: 20, digit: 20, special: 20 = 80
        # Wait — length < 8 means length req is False, so 0 for length
        # Actually let me re-read the code:
        # requirements["length"] = len(password) >= 8 → False for "Ab1!"
        # score: upper(20) + lower(20) + digit(20) + special(20) = 80
        # No length bonus (len < 12)
        # strength: score >= 80 → "strong"
        # is_valid: score >= 60 → True
        assert result["score"] == 80
        assert result["strength"] == "strong"
        assert result["is_valid"] is True

    def test_score_60_medium(self):
        # "Ab1x" → length < 8: 0, upper: 20, lower: 20, digit: 20, special: 0 = 60
        result = validate_password_strength("Ab1x")
        assert result["score"] == 60
        assert result["strength"] == "medium"
        assert result["is_valid"] is True

    def test_score_below_60_weak(self):
        # "abc" → length < 8: 0, upper: 0, lower: 20, digit: 0, special: 0 = 20
        result = validate_password_strength("abc")
        assert result["score"] == 20
        assert result["strength"] == "weak"
        assert result["is_valid"] is False

    def test_length_bonus_12_chars(self):
        # "Ab1!xxxxxxxx" → 12 chars: length(20) + upper(20) + lower(20) + digit(20) + special(20) + bonus12(10) = 110 → capped at 100
        result = validate_password_strength("Ab1!xxxxxxxx")
        assert result["score"] == 100  # capped
        assert result["strength"] == "strong"

    def test_length_bonus_16_chars(self):
        # "Ab1!xxxxxxxxxxxx" → 16 chars: 100 + bonus12(10) + bonus16(10) = 120 → capped at 100
        result = validate_password_strength("Ab1!xxxxxxxxxxxx")
        assert result["score"] == 100

    def test_score_capped_at_100(self):
        # Very long password with all requirements
        result = validate_password_strength("Ab1!xxxxxxxxxxxxxxxxx")
        assert result["score"] <= 100

    def test_requirements_dict_all_true(self):
        result = validate_password_strength("Ab1!xxxxxx")
        assert result["requirements"]["length"] is True
        assert result["requirements"]["uppercase"] is True
        assert result["requirements"]["lowercase"] is True
        assert result["requirements"]["digits"] is True
        assert result["requirements"]["special"] is True

    def test_requirements_dict_all_false(self):
        result = validate_password_strength("")
        assert result["requirements"]["length"] is False
        assert result["requirements"]["uppercase"] is False
        assert result["requirements"]["lowercase"] is False
        assert result["requirements"]["digits"] is False
        assert result["requirements"]["special"] is False

    def test_only_lowercase(self):
        result = validate_password_strength("abcdefgh")
        assert result["score"] == 40  # length(20) + lower(20)
        assert result["strength"] == "weak"
        assert result["is_valid"] is False

    def test_class_method_same_as_function(self):
        r1 = PasswordGenerator.validate_password_strength("Ab1!")
        r2 = validate_password_strength("Ab1!")
        assert r1 == r2
