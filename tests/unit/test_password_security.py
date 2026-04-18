"""Unit tests for src/Util/password_security.py — Slice 3.

Argon2id hashing + legacy SHA256 migration. No external services needed.
Note: Argon2 is computationally expensive (~1s per hash), so tests are fewer.
"""

import hashlib

import pytest

from src.Util.password_security import (
    PasswordManager,
    hash_password,
    verify_password,
    needs_rehash,
    migrate_legacy_hash,
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


# ─── _is_legacy_hash ────────────────────────────────────────────────────────

class TestIsLegacyHash:
    def test_sha256_hex_64_chars_uppercase(self):
        legacy = "5E884898DA28047151D0E56F8DC6292773603D0D6AABBDD62A11EF721D1542D8"
        assert password_manager._is_legacy_hash(legacy) is True

    def test_sha256_hex_64_chars_lowercase(self):
        legacy = "5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8"
        assert password_manager._is_legacy_hash(legacy) is True

    def test_sha256_hex_64_chars_mixed_case(self):
        legacy = "5e884898DA28047151D0E56F8DC6292773603D0D6AABBDD62A11EF721D1542D8"
        assert password_manager._is_legacy_hash(legacy) is True

    def test_argon2_hash_not_legacy(self):
        argon2 = "$argon2id$v=19$m=65536,t=3,p=1$abc123"
        assert password_manager._is_legacy_hash(argon2) is False

    def test_short_string_not_legacy(self):
        assert password_manager._is_legacy_hash("not_a_hash") is False

    def test_empty_string_not_legacy(self):
        assert password_manager._is_legacy_hash("") is False

    def test_non_string_not_legacy(self):
        assert password_manager._is_legacy_hash(12345) is False

    def test_63_chars_not_legacy(self):
        short = "a" * 63
        assert password_manager._is_legacy_hash(short) is False

    def test_65_chars_not_legacy(self):
        long = "a" * 65
        assert password_manager._is_legacy_hash(long) is False

    def test_64_chars_with_non_hex_not_legacy(self):
        non_hex = "g" * 64  # 'g' is not a valid hex char
        assert password_manager._is_legacy_hash(non_hex) is False


# ─── needs_rehash ───────────────────────────────────────────────────────────

class TestNeedsRehash:
    def test_legacy_hash_needs_rehash(self):
        legacy = hashlib.sha256(b"password").hexdigest()
        assert needs_rehash(legacy) is True

    def test_argon2_hash_does_not_need_rehash(self):
        h = hash_password("password")
        # Current params match, so should not need rehash
        assert needs_rehash(h) is False

    def test_invalid_string_needs_rehash(self):
        assert needs_rehash("not_a_hash_at_all") is True


# ─── migrate_legacy_hash ────────────────────────────────────────────────────

class TestMigrateLegacyHash:
    def test_correct_password_returns_new_argon2_hash(self):
        legacy = hashlib.sha256(b"migrate_me").hexdigest()
        new_hash = migrate_legacy_hash("migrate_me", legacy)
        assert new_hash is not None
        assert new_hash.startswith("$argon2")

    def test_wrong_password_returns_none(self):
        legacy = hashlib.sha256(b"correct").hexdigest()
        result = migrate_legacy_hash("wrong", legacy)
        assert result is None

    def test_migrated_hash_verifies_with_original_password(self):
        legacy = hashlib.sha256(b"test_migrate").hexdigest()
        new_hash = migrate_legacy_hash("test_migrate", legacy)
        assert verify_password("test_migrate", new_hash) is True


# ─── verify_password with legacy SHA256 ─────────────────────────────────────

class TestVerifyPasswordLegacy:
    def test_verify_lowercase_sha256(self):
        legacy = hashlib.sha256(b"legacy_pass").hexdigest().lower()
        assert verify_password("legacy_pass", legacy) is True

    def test_verify_uppercase_sha256(self):
        legacy = hashlib.sha256(b"legacy_pass").hexdigest().upper()
        assert verify_password("legacy_pass", legacy) is True

    def test_verify_wrong_password_legacy(self):
        legacy = hashlib.sha256(b"correct").hexdigest()
        assert verify_password("wrong", legacy) is False
