"""
Password Generation Utility

Provides secure password generation for administrative functions
like password resets and temporary password creation.
"""

import secrets
import string
from datetime import datetime, timedelta
from typing import Dict, Any


class PasswordGenerator:
    """
    Secure password generation utility
    """

    @staticmethod
    def generate_temporary_password(length: int = 12) -> str:
        """
        Generate a secure temporary password
        
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
        Generate a secure password reset token
        
        Returns:
            URL-safe reset token
        """
        return secrets.token_urlsafe(32)

    @staticmethod
    def create_password_reset_data(user_id: int, expiry_hours: int = 24) -> Dict[str, Any]:
        """
        Create password reset data structure
        
        Args:
            user_id: User ID for the reset
            expiry_hours: Hours until token expires
            
        Returns:
            Password reset data
        """
        reset_token = PasswordGenerator.generate_reset_token()
        temp_password = PasswordGenerator.generate_temporary_password()

        expiry_time = datetime.utcnow() + timedelta(hours=expiry_hours)

        return {
            "reset_token": reset_token,
            "temporary_password": temp_password,
            "user_id": user_id,
            "expires_at": expiry_time,
            "created_at": datetime.utcnow()
        }

    @staticmethod
    def validate_password_strength(password: str) -> Dict[str, Any]:
        """
        Validate password strength
        
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


def create_password_reset(user_id: int, expiry_hours: int = 24) -> Dict[str, Any]:
    """Create password reset data"""
    return password_generator.create_password_reset_data(user_id, expiry_hours)


def create_password_reset_data(user_id: int, expiry_hours: int = 24) -> Dict[str, Any]:
    """Create password reset data (convenience function for users.py import)"""
    return password_generator.create_password_reset_data(user_id, expiry_hours)


def validate_password_strength(password: str) -> Dict[str, Any]:
    """Validate password strength"""
    return password_generator.validate_password_strength(password)
