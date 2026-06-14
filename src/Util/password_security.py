"""
Password Security Module

Provides secure password hashing and verification using Argon2id algorithm.
Replaces the insecure SHA256 hashing with industry-standard password security.

Features:
- Argon2id algorithm (recommended variant)
- Salt generation and management
- Password verification
- Configurable security parameters
- Migration support for existing hashes
"""

import hashlib
import re
import secrets
import string
from dataclasses import dataclass
from typing import Iterable, Optional

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, HashingError

from src.Util.auth_constants import (
    DEFAULT_PASSWORD_MIN_LENGTH,
    DEFAULT_PASSWORD_WEAK_DENYLIST,
)


PASSWORD_POLICY_REASON_TOO_SHORT = "too_short"
PASSWORD_POLICY_REASON_COMMON = "common_password"
PASSWORD_POLICY_REASON_IDENTIFIER = "obvious_identifier_derivation"
PASSWORD_POLICY_REASON_REPEATED_OR_SEQUENTIAL = "repeated_or_sequential"


@dataclass(frozen=True)
class PasswordPolicyResult:
    """Secret-safe result for server-side password-policy validation.

    The submitted password and contextual identifiers are intentionally omitted
    from this object because tests, logs, and API errors may serialize it.
    """

    is_valid: bool
    reason_codes: tuple[str, ...]
    min_length: int


def _as_policy_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().casefold()


def _compact_policy_text(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", _as_policy_text(value))


def _denylist_values(extra_blocklist: Iterable[str] | None = None) -> set[str]:
    values: set[str] = set()
    for item in DEFAULT_PASSWORD_WEAK_DENYLIST:
        normalized = _as_policy_text(item)
        compact = _compact_policy_text(item)
        if normalized:
            values.add(normalized)
        if compact:
            values.add(compact)

    if extra_blocklist:
        for item in extra_blocklist:
            normalized = _as_policy_text(item)
            compact = _compact_policy_text(item)
            if normalized:
                values.add(normalized)
            if compact:
                values.add(compact)
    return values


def _contextual_values(*values: str | None) -> set[str]:
    contextual: set[str] = set()
    for value in values:
        if not value:
            continue
        normalized = _as_policy_text(value)
        compact = _compact_policy_text(value)
        local_part = normalized.split("@", 1)[0] if "@" in normalized else normalized
        for candidate in (normalized, compact, _compact_policy_text(local_part)):
            if len(candidate) >= 3:
                contextual.add(candidate)
    return contextual


def _is_repeated_or_sequence(password: str) -> bool:
    compact = _compact_policy_text(password)
    if len(compact) < 8:
        return False

    if len(set(compact)) == 1:
        return True

    if compact.isalpha() and _is_monotonic_sequence(compact, string.ascii_lowercase):
        return True
    if compact.isdigit() and _is_monotonic_sequence(compact, string.digits):
        return True

    return False


def _is_monotonic_sequence(value: str, alphabet: str) -> bool:
    positions = [alphabet.find(char) for char in value]
    if any(position < 0 for position in positions):
        return False

    size = len(alphabet)
    forward = all((positions[index] - positions[index - 1]) % size == 1 for index in range(1, len(positions)))
    backward = all((positions[index - 1] - positions[index]) % size == 1 for index in range(1, len(positions)))
    return forward or backward


def validate_password_policy(
    password: str,
    *,
    username: str | None = None,
    email: str | None = None,
    identifier: str | None = None,
    min_length: int | None = None,
    extra_blocklist: Iterable[str] | None = None,
) -> PasswordPolicyResult:
    """Validate a candidate against the shared NIST-style server policy.

    This helper intentionally avoids character-class requirements and never
    returns the candidate password, context identifiers, or denylist contents.
    """

    candidate = password if isinstance(password, str) else ""
    effective_min_length = max(1, int(min_length if min_length is not None else DEFAULT_PASSWORD_MIN_LENGTH))
    reason_codes: list[str] = []

    if len(candidate) < effective_min_length:
        reason_codes.append(PASSWORD_POLICY_REASON_TOO_SHORT)

    candidate_normalized = _as_policy_text(candidate)
    candidate_compact = _compact_policy_text(candidate)
    denylist = _denylist_values(extra_blocklist)
    if candidate_normalized in denylist or candidate_compact in denylist:
        reason_codes.append(PASSWORD_POLICY_REASON_COMMON)

    contextual_values = _contextual_values(username, email, identifier)
    if candidate_compact and any(value in candidate_compact for value in contextual_values):
        reason_codes.append(PASSWORD_POLICY_REASON_IDENTIFIER)

    if _is_repeated_or_sequence(candidate):
        reason_codes.append(PASSWORD_POLICY_REASON_REPEATED_OR_SEQUENTIAL)

    ordered_unique_reasons = tuple(dict.fromkeys(reason_codes))
    return PasswordPolicyResult(
        is_valid=not ordered_unique_reasons,
        reason_codes=ordered_unique_reasons,
        min_length=effective_min_length,
    )


def assert_password_policy(password: str, **context) -> None:
    """Raise a sanitized VAL_3007 error when a candidate fails policy."""

    result = validate_password_policy(password, **context)
    if result.is_valid:
        return

    from src.Util.error_handler import create_weak_password_error

    raise create_weak_password_error(
        reason_codes=result.reason_codes,
        min_length=result.min_length,
    )


class PasswordManager:
    """
    Secure password management using Argon2id algorithm
    """

    def __init__(self):
        """
        Initialize password hasher with secure parameters.
        
        Parameters chosen for good security/performance balance:
        - time_cost: 3 (number of iterations)
        - memory_cost: 65536 (64 MiB memory usage)
        - parallelism: 1 (number of parallel threads)
        - hash_len: 32 (32 byte hash length)
        - salt_len: 16 (16 byte salt length)
        """
        self.hasher = PasswordHasher(
            time_cost=3,  # Number of iterations
            memory_cost=65536,  # Memory usage in KiB (64 MiB)
            parallelism=1,  # Number of parallel threads
            hash_len=32,  # Hash length in bytes
            salt_len=16,  # Salt length in bytes
        )

    def hash_password(self, password: str) -> str:
        """
        Hash a password using Argon2id with automatic salt generation.
        
        Args:
            password: Plain text password to hash
            
        Returns:
            Argon2 hash string (includes algorithm, parameters, salt, and hash)
            
        Raises:
            HashingError: If password hashing fails
        """
        try:
            return self.hasher.hash(password)
        except Exception as e:
            raise HashingError(f"Password hashing failed: {str(e)}")

    def verify_password(self, password: str, hashed_password: str) -> bool:
        """
        Verify a password against its hash.
        
        Args:
            password: Plain text password to verify
            hashed_password: Stored hash to verify against
            
        Returns:
            True if password matches, False otherwise
        """
        try:
            # Handle legacy SHA256 hashes during migration
            if self._is_legacy_hash(hashed_password):
                return self._verify_legacy_hash(password, hashed_password)

            # Verify Argon2 hash
            self.hasher.verify(hashed_password, password)
            return True

        except (VerifyMismatchError, VerificationError):
            return False
        except Exception:
            return False

    def needs_rehash(self, hashed_password: str) -> bool:
        """
        Check if a password hash needs to be updated.
        
        This will return True for:
        - Legacy SHA256 hashes (for migration)
        - Argon2 hashes with outdated parameters
        
        Args:
            hashed_password: Hash to check
            
        Returns:
            True if hash needs updating, False otherwise
        """
        try:
            # Legacy hashes always need rehashing
            if self._is_legacy_hash(hashed_password):
                return True

            # Check if Argon2 parameters need updating
            return self.hasher.check_needs_rehash(hashed_password)

        except Exception:
            # If we can't parse the hash, it needs rehashing
            return True

    def _is_legacy_hash(self, hashed_password: str) -> bool:
        """
        Check if a hash is a legacy SHA256 hash.
        
        Args:
            hashed_password: Hash to check
            
        Returns:
            True if it's a legacy hash, False otherwise
        """
        # Legacy SHA256 hashes are 64 characters of hex (uppercase or lowercase)
        return (
                isinstance(hashed_password, str) and
                len(hashed_password) == 64 and
                all(c in '0123456789ABCDEFabcdef' for c in hashed_password)
        )

    def _verify_legacy_hash(self, password: str, legacy_hash: str) -> bool:
        """
        Verify password against legacy SHA256 hash.
        
        Args:
            password: Plain text password
            legacy_hash: Legacy SHA256 hash (uppercase or lowercase)
            
        Returns:
            True if password matches legacy hash, False otherwise
        """
        try:
            computed_hash = hashlib.sha256(password.encode()).hexdigest()
            # Compare case-insensitively by converting both to lowercase
            return secrets.compare_digest(computed_hash.lower(), legacy_hash.lower())
        except Exception:
            return False

    def migrate_legacy_hash(self, password: str, legacy_hash: str) -> Optional[str]:
        """
        Migrate a legacy hash to Argon2 if password is correct.
        
        Args:
            password: Plain text password
            legacy_hash: Legacy hash to migrate
            
        Returns:
            New Argon2 hash if migration successful, None otherwise
        """
        if self._verify_legacy_hash(password, legacy_hash):
            return self.hash_password(password)
        return None


# Global password manager instance
password_manager = PasswordManager()


# Convenience functions for backward compatibility
def hash_password(password: str) -> str:
    """
    Hash a password using Argon2id.
    
    Args:
        password: Plain text password to hash
        
    Returns:
        Argon2 hash string
    """
    return password_manager.hash_password(password)


def verify_password(password: str, hashed_password: str) -> bool:
    """
    Verify a password against its hash.
    
    Args:
        password: Plain text password to verify
        hashed_password: Stored hash to verify against
        
    Returns:
        True if password matches, False otherwise
    """
    return password_manager.verify_password(password, hashed_password)


def needs_rehash(hashed_password: str) -> bool:
    """
    Check if a password hash needs to be updated.
    
    Args:
        hashed_password: Hash to check
        
    Returns:
        True if hash needs updating, False otherwise
    """
    return password_manager.needs_rehash(hashed_password)


def migrate_legacy_hash(password: str, legacy_hash: str) -> Optional[str]:
    """
    Migrate a legacy hash to Argon2 if password is correct.
    
    Args:
        password: Plain text password
        legacy_hash: Legacy hash to migrate
        
    Returns:
        New Argon2 hash if migration successful, None otherwise
    """
    return password_manager.migrate_legacy_hash(password, legacy_hash)
