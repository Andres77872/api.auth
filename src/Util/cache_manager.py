"""
Enhanced Cache Manager for 3-Tier User Type Multi-Project Authentication

This module provides comprehensive caching for:
- User sessions (1 hour TTL)
- Access check results
- Global role permission checks
- User type information

Features:
- Cache-first access checks
- Automatic cache invalidation on user/role changes
- Redis-based storage with proper TTL management
"""

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Iterator, List

from src.Util.db_config import redis_client

# Configure logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)

# Cache TTL settings (in seconds)
SESSION_TTL = 3600  # 1 hour for sessions
ACCESS_CHECK_TTL = 1800  # 30 minutes for access checks
PERMISSION_CHECK_TTL = 1800  # 30 minutes for permission checks
USER_INFO_TTL = 3600  # 1 hour for user info
VALIDATE_CACHE_TTL = int(os.environ.get("VALIDATE_CACHE_TTL", "30"))  # Phase 2.1: full-session cache TTL in seconds

# Cache key prefixes
SESSION_PREFIX = "session:"
SESSION_FULL_PREFIX = "session_full:"  # Phase 2.1: full EnhancedUserLogin cache
ACCESS_PREFIX = "access:"
ROLE_PREFIX = "role:"
USER_INFO_PREFIX = "user_info:"
PERMISSION_PREFIX = "permission:"
USER_TYPE_PREFIX = "user_type:"
APIKEY_PREFIX = "apikey:"

# API key cache TTL (seconds) — short window to balance performance with security
APIKEY_TTL = 60  # 60 seconds


class CacheManager:
    """Enhanced cache manager for authentication system"""

    def __init__(self):
        self.redis = redis_client

    def _iter_keys(self, pattern: str, count: int = 100) -> Iterator[Any]:
        """Iterate keys with SCAN instead of blocking Redis with KEYS."""
        yield from self.redis.scan_iter(match=pattern, count=count)

    def _delete_keys(self, keys: List[Any]) -> int:
        if not keys:
            return 0
        return int(self.redis.delete(*keys))

    def _delete_pattern(self, pattern: str, batch_size: int = 100) -> int:
        deleted_count = 0
        batch: List[Any] = []

        for key in self._iter_keys(pattern, count=batch_size):
            batch.append(key)
            if len(batch) >= batch_size:
                deleted_count += self._delete_keys(batch)
                batch.clear()

        deleted_count += self._delete_keys(batch)
        return deleted_count

    def _count_pattern(self, pattern: str, batch_size: int = 100) -> int:
        return sum(1 for _ in self._iter_keys(pattern, count=batch_size))

    def invalidate_user_sessions(self, user_id: str) -> int:
        invalidated_count = 0

        # Scan raw session keys
        for key in self._iter_keys(f"{SESSION_PREFIX}*", count=100):
            try:
                session_data = self.redis.get(key)
                if not session_data:
                    continue

                data = json.loads(session_data)
                if data.get('user_id') == user_id:
                    invalidated_count += int(self.redis.delete(key))
            except Exception:
                continue

        # Phase 2.1c: Also scan and invalidate full-session cache keys
        for key in self._iter_keys(f"{SESSION_FULL_PREFIX}*", count=100):
            try:
                raw = self.redis.get(key)
                if not raw:
                    continue
                if isinstance(raw, bytes):
                    raw = raw.decode()
                data = json.loads(raw)
                if data.get('user_id') == user_id:
                    invalidated_count += int(self.redis.delete(key))
            except Exception:
                continue

        return invalidated_count

    # =============================================================================
    # CACHE KEY GENERATION
    # =============================================================================

    @staticmethod
    def _generate_cache_key(prefix: str, *args) -> str:
        """Generate a consistent cache key"""
        key_parts = [str(arg) for arg in args]
        return f"{prefix}{'_'.join(key_parts)}"

    @staticmethod
    def _hash_key(key: str) -> str:
        """Generate a hash for long keys"""
        return hashlib.sha256(key.encode()).hexdigest()[:16]

    # =============================================================================
    # SESSION MANAGEMENT
    # =============================================================================

    def set_session(self, session_token: str, session_data: Dict[str, Any]) -> bool:
        """
        Store session data in cache with 1-hour TTL
        
        Args:
            session_token: Session token
            session_data: Session data dictionary
            
        Returns:
            Success status
        """
        try:
            cache_key = f"{SESSION_PREFIX}{session_token}"
            session_json = json.dumps(session_data, default=str)

            result = self.redis.setex(cache_key, SESSION_TTL, session_json)

            if result:
                logger.debug(f"Session cached: {session_token[:8]}... for {SESSION_TTL} seconds")

            return bool(result)

        except Exception as e:
            logger.error(f"Failed to cache session {session_token[:8]}...: {e}")
            return False

    def get_session(self, session_token: str) -> Optional[Dict[str, Any]]:
        """
        Get session data from cache
        
        Args:
            session_token: Session token
            
        Returns:
            Session data or None if not found/expired
        """
        try:
            cache_key = f"{SESSION_PREFIX}{session_token}"
            cached_data = self.redis.get(cache_key)

            if cached_data:
                session_data = json.loads(cached_data)
                logger.debug(f"Session cache hit: {session_token[:8]}...")
                return session_data

            logger.debug(f"Session cache miss: {session_token[:8]}...")
            return None

        except Exception as e:
            logger.error(f"Failed to get session {session_token[:8]}...: {e}")
            return None

    # =============================================================================
    # FULL SESSION CACHE (Phase 2.1) — serialized EnhancedUserLogin
    # =============================================================================

    def set_session_full(self, session_token: str, login_data: 'EnhancedUserLogin') -> bool:
        """
        Serialize full EnhancedUserLogin to Redis with short TTL for cache-first validation.

        Args:
            session_token: Session token
            login_data: EnhancedUserLogin object to cache

        Returns:
            Success status
        """
        try:
            cache_key = f"{SESSION_FULL_PREFIX}{session_token}"
            json_data = login_data.model_dump_json()
            result = self.redis.setex(cache_key, VALIDATE_CACHE_TTL, json_data)
            if result:
                logger.debug(f"Full session cached: {session_token[:8]}... TTL={VALIDATE_CACHE_TTL}s")
            return bool(result)
        except Exception as e:
            logger.error(f"Failed to cache full session {session_token[:8]}...: {e}")
            return False

    def get_session_full(self, session_token: str) -> Optional['EnhancedUserLogin']:
        """
        Deserialize EnhancedUserLogin from Redis full-session cache.

        Args:
            session_token: Session token

        Returns:
            EnhancedUserLogin or None on miss/error
        """
        try:
            cache_key = f"{SESSION_FULL_PREFIX}{session_token}"
            raw = self.redis.get(cache_key)
            if not raw:
                logger.debug(f"Full session cache miss: {session_token[:8]}...")
                return None
            # Handle both bytes (default Redis) and str (decode_responses=True)
            if isinstance(raw, bytes):
                raw = raw.decode()
            from src.Util.Models import EnhancedUserLogin
            login_data = EnhancedUserLogin.model_validate_json(raw)
            logger.debug(f"Full session cache hit: {session_token[:8]}...")
            return login_data
        except Exception as e:
            logger.warning(f"Failed to deserialize full session {session_token[:8]}...: {e}")
            return None

    def invalidate_session(self, session_token: str) -> bool:
        """
        Remove session from cache (both raw session and full EnhancedUserLogin).
        
        Args:
            session_token: Session token
            
        Returns:
            Success status
        """
        try:
            cache_key = f"{SESSION_PREFIX}{session_token}"
            full_key = f"{SESSION_FULL_PREFIX}{session_token}"  # Phase 2.1c
            result = self.redis.delete(cache_key, full_key)

            if result:
                logger.debug(f"Session invalidated: {session_token[:8]}...")

            return bool(result)

        except Exception as e:
            logger.error(f"Failed to invalidate session {session_token[:8]}...: {e}")
            return False

    # =============================================================================
    # ACCESS CHECK CACHING
    # =============================================================================

    def set_access_check(self, user_id: str, project_id: str, access_result: Dict[str, Any]) -> bool:
        """
        Cache access check result
        
        Args:
            user_id: User ID
            project_id: Project ID
            access_result: Access check result
            
        Returns:
            Success status
        """
        try:
            cache_key = self._generate_cache_key(ACCESS_PREFIX, user_id, project_id)
            result_json = json.dumps(access_result, default=str)

            result = self.redis.setex(cache_key, ACCESS_CHECK_TTL, result_json)

            if result:
                logger.debug(f"Access check cached: user_{user_id}_project_{project_id}")

            return bool(result)

        except Exception as e:
            logger.error(f"Failed to cache access check user_{user_id}_project_{project_id}: {e}")
            return False

    def get_access_check(self, user_id: str, project_id: str) -> Optional[Dict[str, Any]]:
        """
        Get cached access check result
        
        Args:
            user_id: User ID
            project_id: Project ID
            
        Returns:
            Cached access result or None
        """
        try:
            cache_key = self._generate_cache_key(ACCESS_PREFIX, user_id, project_id)
            cached_data = self.redis.get(cache_key)

            if cached_data:
                access_result = json.loads(cached_data)
                logger.debug(f"Access check cache hit: user_{user_id}_project_{project_id}")
                return access_result

            logger.debug(f"Access check cache miss: user_{user_id}_project_{project_id}")
            return None

        except Exception as e:
            logger.error(f"Failed to get access check user_{user_id}_project_{project_id}: {e}")
            return None

    # =============================================================================
    # GLOBAL ROLE PERMISSION CACHING
    # =============================================================================

    def set_permission_check(self, user_id: str, permission: str, has_permission: bool) -> bool:
        """
        Cache global role permission check result
        
        Args:
            user_id: User ID
            permission: Permission name
            has_permission: Whether user has permission
            
        Returns:
            Success status
        """
        try:
            cache_key = f"{PERMISSION_PREFIX}{user_id}_{permission}"

            permission_data = {
                "has_permission": has_permission,
                "checked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "user_id": user_id,
                "permission": permission
            }

            result_json = json.dumps(permission_data)
            result = self.redis.setex(cache_key, PERMISSION_CHECK_TTL, result_json)

            if result:
                logger.debug(f"Permission check cached: user_{user_id}_{permission}")

            return bool(result)

        except Exception as e:
            logger.error(f"Failed to cache permission check: {e}")
            return False

    def get_permission_check(self, user_id: str, permission: str) -> Optional[bool]:
        """
        Get cached global role permission check result
        
        Args:
            user_id: User ID
            permission: Permission name
            
        Returns:
            Cached permission result or None
        """
        try:
            cache_key = f"{PERMISSION_PREFIX}{user_id}_{permission}"
            cached_data = self.redis.get(cache_key)

            if cached_data:
                permission_data = json.loads(cached_data)
                logger.debug(f"Permission check cache hit: user_{user_id}_{permission}")
                return permission_data.get("has_permission")

            logger.debug(f"Permission check cache miss: user_{user_id}_{permission}")
            return None

        except Exception as e:
            logger.error(f"Failed to get permission check: {e}")
            return None

    # =============================================================================
    # USER TYPE CACHING
    # =============================================================================

    def set_user_type(self, user_id: str, user_type: str, additional_data: Dict[str, Any] = None) -> bool:
        """
        Cache user type information
        
        Args:
            user_id: User ID
            user_type: User type (root, admin, consumer)
            additional_data: Additional user type data
            
        Returns:
            Success status
        """
        try:
            cache_key = self._generate_cache_key(USER_TYPE_PREFIX, user_id)

            type_data = {
                "user_type": user_type,
                "cached_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "user_id": user_id
            }

            if additional_data:
                type_data.update(additional_data)

            result_json = json.dumps(type_data, default=str)
            result = self.redis.setex(cache_key, USER_INFO_TTL, result_json)

            if result:
                logger.debug(f"User type cached: user_{user_id}_{user_type}")

            return bool(result)

        except Exception as e:
            logger.error(f"Failed to cache user type for user_{user_id}: {e}")
            return False

    def get_user_type(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Get cached user type information
        
        Args:
            user_id: User ID
            
        Returns:
            Cached user type data or None
        """
        try:
            cache_key = self._generate_cache_key(USER_TYPE_PREFIX, user_id)
            cached_data = self.redis.get(cache_key)

            if cached_data:
                type_data = json.loads(cached_data)
                logger.debug(f"User type cache hit: user_{user_id}")
                return type_data

            logger.debug(f"User type cache miss: user_{user_id}")
            return None

        except Exception as e:
            logger.error(f"Failed to get user type for user_{user_id}: {e}")
            return None

    # =============================================================================
    # CACHE INVALIDATION
    # =============================================================================

    def invalidate_user_cache(self, user_id: str) -> bool:
        """
        Invalidate all cache entries for a specific user including their sessions
        
        Args:
            user_id: User ID
            
        Returns:
            Success status
        """
        try:
            # Find all keys related to this user
            patterns = [
                f"{ACCESS_PREFIX}{user_id}_*",
                f"{PERMISSION_PREFIX}{user_id}_*",
                f"{USER_TYPE_PREFIX}{user_id}",
                f"{USER_INFO_PREFIX}{user_id}_*"
            ]

            deleted_count = 0
            for pattern in patterns:
                deleted_count += self._delete_pattern(pattern)
            
            # Also invalidate all sessions for this user
            deleted_count += self.invalidate_user_sessions(user_id)

            logger.info(f"Invalidated {deleted_count} cache entries for user_{user_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to invalidate user cache for user_{user_id}: {e}")
            return False

    def invalidate_project_cache(self, project_id: str) -> bool:
        """
        Invalidate all cache entries for a specific project
        
        Args:
            project_id: Project ID
            
        Returns:
            Success status
        """
        try:
            # Find all keys related to this project
            patterns = [
                f"{ACCESS_PREFIX}*_{project_id}",
                f"{PERMISSION_PREFIX}*_{project_id}_*",
                f"{ROLE_PREFIX}*_{project_id}_*"
            ]

            deleted_count = 0
            for pattern in patterns:
                deleted_count += self._delete_pattern(pattern)

            logger.info(f"Invalidated {deleted_count} cache entries for project_{project_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to invalidate project cache for project_{project_id}: {e}")
            return False

    def clear_all_cache(self) -> bool:
        """
        Clear entire authentication cache
        
        Returns:
            Success status
        """
        try:
            # Get all authentication-related cache keys
            patterns = [
                f"{SESSION_PREFIX}*",
                f"{ACCESS_PREFIX}*",
                f"{ROLE_PREFIX}*",
                f"{PERMISSION_PREFIX}*",
                f"{USER_INFO_PREFIX}*",
                f"{USER_TYPE_PREFIX}*"
            ]

            deleted_count = 0
            for pattern in patterns:
                deleted_count += self._delete_pattern(pattern)

            logger.warning(f"FULL CACHE CLEAR: Invalidated {deleted_count} cache entries")
            return True

        except Exception as e:
            logger.error(f"Failed to clear all cache: {e}")
            return False

    def invalidate_role_cache(self, user_id: Optional[str] = None) -> bool:
        """
        Invalidate global role-related cache entries
        
        Args:
            user_id: Optional user ID to limit scope
            
        Returns:
            True if invalidated successfully
        """
        try:
            if user_id:
                # Invalidate role cache for specific user
                patterns = [
                    f"{PERMISSION_PREFIX}{user_id}_*",
                    f"{ROLE_PREFIX}{user_id}_*"
                ]
            else:
                # Invalidate all role cache
                patterns = [
                    f"{PERMISSION_PREFIX}*",
                    f"{ROLE_PREFIX}*"
                ]

            deleted_count = 0
            for pattern in patterns:
                deleted_count += self._delete_pattern(pattern)

            scope = f"user_{user_id}" if user_id else "all_users"
            logger.info(f"Invalidated {deleted_count} role cache entries for {scope}")
            return True

        except Exception as e:
            logger.error(f"Failed to invalidate role cache: {e}")
            return False

    # =============================================================================
    # API KEY VALIDATION CACHING
    # =============================================================================

    def set_api_key(self, public_id: str, validation_data: Dict[str, Any]) -> bool:
        """
        Cache API key validation result with short TTL (60s).

        Args:
            public_id: The API key's public identifier
            validation_data: Dict with validated key metadata
                (user_id, project_id, permissions, groups, etc.)

        Returns:
            Success status
        """
        try:
            cache_key = f"{APIKEY_PREFIX}{public_id}"
            data_json = json.dumps(validation_data, default=str)

            result = self.redis.setex(cache_key, APIKEY_TTL, data_json)

            if result:
                logger.debug(f"API key cached: {public_id[:8]}... for {APIKEY_TTL} seconds")

            return bool(result)

        except Exception as e:
            logger.error(f"Failed to cache API key {public_id[:8]}...: {e}")
            return False

    def get_api_key(self, public_id: str) -> Optional[Dict[str, Any]]:
        """
        Get cached API key validation data.

        Args:
            public_id: The API key's public identifier

        Returns:
            Cached validation data or None if not found/expired
        """
        try:
            cache_key = f"{APIKEY_PREFIX}{public_id}"
            cached_data = self.redis.get(cache_key)

            if cached_data:
                validation_data = json.loads(cached_data)
                logger.debug(f"API key cache hit: {public_id[:8]}...")
                return validation_data

            logger.debug(f"API key cache miss: {public_id[:8]}...")
            return None

        except Exception as e:
            logger.error(f"Failed to get API key {public_id[:8]}...: {e}")
            return None

    def invalidate_api_key(self, public_id: str) -> bool:
        """
        Remove API key from cache immediately.

        Called on revocation, reactivation, or any state change that
        invalidates the cached validation result.

        Args:
            public_id: The API key's public identifier

        Returns:
            Success status
        """
        try:
            cache_key = f"{APIKEY_PREFIX}{public_id}"
            result = self.redis.delete(cache_key)

            if result:
                logger.debug(f"API key cache invalidated: {public_id[:8]}...")

            return bool(result)

        except Exception as e:
            logger.error(f"Failed to invalidate API key {public_id[:8]}...: {e}")
            return False

    # =============================================================================
    # CACHE STATISTICS
    # =============================================================================

    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics
        
        Returns:
            Cache statistics dictionary
        """
        try:
            stats = {
                "sessions": self._count_pattern(f"{SESSION_PREFIX}*"),
                "access_checks": self._count_pattern(f"{ACCESS_PREFIX}*"),
                "permission_checks": self._count_pattern(f"{PERMISSION_PREFIX}*"),
                "user_types": self._count_pattern(f"{USER_TYPE_PREFIX}*"),
                "role_checks": self._count_pattern(f"{ROLE_PREFIX}*"),
                "api_keys": self._count_pattern(f"{APIKEY_PREFIX}*"),
                "total_keys": self._count_pattern("*")
            }

            return stats

        except Exception as e:
            logger.error(f"Failed to get cache stats: {e}")
            return {}


# Global cache manager instance
cache_manager = CacheManager()
