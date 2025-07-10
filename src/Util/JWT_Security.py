import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

import jwt
from fastapi import HTTPException
from jose import JWTError

# JWT Configuration
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", secrets.token_urlsafe(64))
JWT_ALGORITHM = "HS256"
JWT_ACCESS_TOKEN_EXPIRE_HOURS = 72  # 3 days, same as original system


class JWTTokenHandler:
    """
    JWT Token Handler to replace the custom Cypher system
    Maintains the same interface for easy migration
    """

    @staticmethod
    def create_access_token(session_id: int, user_hash: str, collection: str,
                            expires_delta: Optional[timedelta] = None) -> str:
        """
        Create a JWT access token with session data
        
        Args:
            session_id: Unique session identifier
            user_hash: User hash for identification
            collection: Collection identifier
            expires_delta: Token expiration time
            
        Returns:
            JWT token string
        """
        if expires_delta:
            expire = datetime.now(timezone.utc) + expires_delta
        else:
            expire = datetime.now(timezone.utc) + timedelta(hours=JWT_ACCESS_TOKEN_EXPIRE_HOURS)

        # Create JWT payload with same data structure as original system
        payload = {
            "session_id": session_id,
            "user_hash": user_hash,
            "collection": collection,
            "exp": expire,
            "iat": datetime.now(timezone.utc),
            "type": "access_token"
        }

        return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

    @staticmethod
    def decode_access_token(token: str) -> Dict[str, Any]:
        """
        Decode and validate JWT access token
        
        Args:
            token: JWT token string
            
        Returns:
            Decoded token payload
            
        Raises:
            HTTPException: If token is invalid or expired
        """
        try:
            payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])

            # Validate token type
            if payload.get("type") != "access_token":
                raise HTTPException(status_code=401, detail="Invalid token type")

            # Check if token is expired (jwt.decode already handles this, but double-check)
            if datetime.fromtimestamp(payload.get("exp", 0), timezone.utc) < datetime.now(timezone.utc):
                raise HTTPException(status_code=401, detail="Token expired")

            return payload

        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token expired")
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=401, detail="Invalid token")
        except JWTError:
            raise HTTPException(status_code=401, detail="Token validation failed")

    @staticmethod
    def extract_session_id(token: str) -> int:
        """
        Extract session ID from JWT token (maintains compatibility with original interface)
        
        Args:
            token: JWT token string
            
        Returns:
            Session ID as integer
        """
        payload = JWTTokenHandler.decode_access_token(token)
        return payload.get("session_id")

    @staticmethod
    def extract_user_hash(token: str) -> str:
        """
        Extract user hash from JWT token
        
        Args:
            token: JWT token string
            
        Returns:
            User hash string
        """
        payload = JWTTokenHandler.decode_access_token(token)
        return payload.get("user_hash")

    @staticmethod
    def extract_collection(token: str) -> str:
        """
        Extract collection from JWT token
        
        Args:
            token: JWT token string
            
        Returns:
            Collection string
        """
        payload = JWTTokenHandler.decode_access_token(token)
        return payload.get("collection")

    @staticmethod
    def validate_token_structure(token: str) -> bool:
        """
        Validate if token has the expected structure without full validation
        
        Args:
            token: JWT token string
            
        Returns:
            True if token structure is valid
        """
        try:
            # Just decode without verification to check structure
            unverified_payload = jwt.decode(token, options={"verify_signature": False})
            required_fields = ["session_id", "user_hash", "collection", "exp", "iat", "type"]
            return all(field in unverified_payload for field in required_fields)
        except:
            return False


# Compatibility functions to maintain the same interface as Cypher.py
def jwt_encode(session_id: int, user_hash: str, collection: str) -> tuple[str, None]:
    """
    Compatibility function that mimics cypher_x_encode interface
    
    Returns:
        Tuple of (token_string, None) to match original interface
    """
    token = JWTTokenHandler.create_access_token(session_id, user_hash, collection)
    return token, None


def jwt_decode(token: str) -> tuple[list[int], None]:
    """
    Compatibility function that mimics cypher_x_decode interface
    
    Returns:
        Tuple of ([session_id], None) to match original interface
    """
    try:
        session_id = JWTTokenHandler.extract_session_id(token)
        return [session_id], None
    except HTTPException:
        return [0], None


# Environment variable check
if not os.getenv("JWT_SECRET_KEY"):
    print("WARNING: JWT_SECRET_KEY environment variable not set. Using auto-generated key.")
    print("For production, set JWT_SECRET_KEY environment variable to a secure random string.")
