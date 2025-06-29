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

import secrets
import hashlib
from typing import Tuple, Optional
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, HashingError


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
            time_cost=3,          # Number of iterations
            memory_cost=65536,    # Memory usage in KiB (64 MiB)
            parallelism=1,        # Number of parallel threads
            hash_len=32,          # Hash length in bytes
            salt_len=16,          # Salt length in bytes
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