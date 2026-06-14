"""
Password Generation Utility

Provides legacy password generation helpers for older administrative utilities.

These helpers are not authoritative for auth password reset/change flows. The
current reset contract is link-only and the accepted password policy lives in
``src.Util.password_security.validate_password_policy``.
"""

import secrets
import string
from datetime import datetime, timedelta, timezone
from typing import Dict, Any


class PasswordGenerator:
    """
    Legacy password generation utility.

    Do not use this class to implement auth reset/change policy. Character-class
    scoring and temporary passwords are retained only for stale compatibility
    paths until those callers are removed.
    """

    @staticmethod
    def generate_temporary_password(length: int = 12) -> str:
        """
        Generate a legacy temporary password.

        Not authoritative for password recovery/change flows; reset/change must
        use hash-only links plus caller-submitted passwords validated by
        ``password_security.validate_password_policy``.
        
        Args:
            length: Password length (minimum 8, maximum 32)
            
        Returns:
            Generated temporary password
        """
        if length < 8:
            length = 8
        elif length > 32:
            length = 32

        # Define character sets
        uppercase = string.ascii_uppercase
        lowercase = string.ascii_lowercase
        digits = string.digits
        special = "!@#$%^&*"

        # Ensure at least one character from each set
        password = [
            secrets.choice(uppercase),
            secrets.choice(lowercase),
            secrets.choice(digits),
            secrets.choice(special)
        ]

        # Fill the rest with random characters from all sets
        all_chars = uppercase + lowercase + digits + special
        for _ in range(length - 4):
            password.append(secrets.choice(all_chars))

        # Shuffle the password list
        secrets.SystemRandom().shuffle(password)

        return ''.join(password)

    @staticmethod
    def generate_reset_token() -> str:
        """
        Generate a legacy reset token.

        Not used by current auth reset/change flows, which store only hash-only
        purpose-scoped link-token verifiers.
        
        Returns:
            URL-safe reset token
        """
        return secrets.token_urlsafe(32)

    @staticmethod
    def create_password_reset_data(user_id: str, expiry_hours: int = 24) -> Dict[str, Any]:
        """
        Create a legacy password reset data structure.

        This contains plaintext reset/temporary password material and must not be
        used for live auth reset/change flows.
        
        Args:
            user_id: User ID for the reset
            expiry_hours: Hours until token expires
            
        Returns:
            Password reset data
        """
        reset_token = PasswordGenerator.generate_reset_token()
        temp_password = PasswordGenerator.generate_temporary_password()

        expiry_time = datetime.now(timezone.utc) + timedelta(hours=expiry_hours)

        return {
            "reset_token": reset_token,
            "temporary_password": temp_password,
            "user_id": user_id,
            "expires_at": expiry_time,
            "created_at": datetime.now(timezone.utc)
        }

    @staticmethod
    def validate_password_strength(password: str) -> Dict[str, Any]:
        """
        Legacy character-class strength scoring.

        This score is not the server-side authentication password policy. Use
        ``src.Util.password_security.validate_password_policy`` instead.
        
        Args:
            password: Password to validate
            
        Returns:
            Validation result with score and requirements
        """
        score = 0
        requirements = {
            "length": len(password) >= 8,
            "uppercase": any(c.isupper() for c in password),
            "lowercase": any(c.islower() for c in password),
            "digits": any(c.isdigit() for c in password),
            "special": any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in password)
        }

        # Calculate score
        if requirements["length"]:
            score += 20
        if requirements["uppercase"]:
            score += 20
        if requirements["lowercase"]:
            score += 20
        if requirements["digits"]:
            score += 20
        if requirements["special"]:
            score += 20

        # Bonus for length
        if len(password) >= 12:
            score += 10
        if len(password) >= 16:
            score += 10

        strength = "weak"
        if score >= 80:
            strength = "strong"
        elif score >= 60:
            strength = "medium"

        return {
            "score": min(score, 100),
            "strength": strength,
            "requirements": requirements,
            "is_valid": score >= 60
        }


# Global instance
password_generator = PasswordGenerator()


# Convenience functions
def generate_temporary_password(length: int = 12) -> str:
    """Generate a temporary password"""
    return password_generator.generate_temporary_password(length)


def generate_reset_token() -> str:
    """Generate a password reset token"""
    return password_generator.generate_reset_token()


def create_password_reset(user_id: str, expiry_hours: int = 24) -> Dict[str, Any]:
    """Create password reset data"""
    return password_generator.create_password_reset_data(user_id, expiry_hours)


def create_password_reset_data(user_id: str, expiry_hours: int = 24) -> Dict[str, Any]:
    """Create password reset data (convenience function for users.py import)"""
    return password_generator.create_password_reset_data(user_id, expiry_hours)


def validate_password_strength(password: str) -> Dict[str, Any]:
    """Validate password strength"""
    return password_generator.validate_password_strength(password)
