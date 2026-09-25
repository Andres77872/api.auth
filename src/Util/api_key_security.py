"""
API Key Token Generation and Verification

Implements split-token API key security using HMAC-SHA-256 with server-side pepper.

Token format: sk_{public_id}.{secret}
- public_id: 12-char base64url (9 bytes entropy) — indexed in DB for fast lookup
- secret: 43-char base64url (32 bytes entropy) — NEVER stored in plaintext
- stored_hash: HMAC-SHA-256(pepper, "v1:{public_id}:{secret}") — BINARY(32)

Security properties:
- Constant-time comparison via hmac.compare_digest()
- Dummy hash for malformed tokens (timing-attack resistance)
- One-time secret reveal at creation only
- Validation-cache hits re-verify the presented secret against the cached stored_hash
"""

import base64
import hashlib
import hmac
import os
import secrets
from typing import Optional

# Load pepper at module level — raises KeyError if missing (fail-fast at startup)
API_KEY_PEPPER = os.environ["API_KEY_PEPPER"].encode("utf-8")

# Token entropy constants
PUBLIC_ID_BYTES = 9    # 9 bytes → ~12 base64url chars
SECRET_BYTES = 32      # 32 bytes → ~43 base64url chars
HASH_VERSION = "v1"    # Algorithm version prefix for hash material


def generate_api_key_token() -> dict:
    """Generate a new API key token pair.

    Returns a dict with all material needed for DB storage and one-time reveal:

    Returns:
        {
            "token": "sk_{public_id}.{secret}",    # Full token (shown exactly once)
            "public_id": "{public_id}",             # Indexed in DB for lookup
            "secret_hash": bytes,                   # BINARY(32) HMAC-SHA-256 for DB storage
            "fingerprint": "{12-char hex}",         # BLAKE2s-based short identifier for UI
            "secret_last4": "{last 4 chars}"        # Last 4 chars of secret for confirmation
        }
    """
    # Generate public_id: 9 random bytes → base64url → strip padding → 12 chars
    public_id = base64.urlsafe_b64encode(
        secrets.token_bytes(PUBLIC_ID_BYTES)
    ).rstrip(b"=").decode("ascii")

    # Generate secret: 32 random bytes → base64url → strip padding → 43 chars
    secret = base64.urlsafe_b64encode(
        secrets.token_bytes(SECRET_BYTES)
    ).rstrip(b"=").decode("ascii")

    # Full token in split-token format
    token = f"sk_{public_id}.{secret}"

    # HMAC-SHA-256 with server-side pepper
    # Hash material includes version, public_id, and secret to bind them together
    material = f"{HASH_VERSION}:{public_id}:{secret}".encode("utf-8")
    secret_hash = hmac.digest(API_KEY_PEPPER, material, "sha256")  # Returns BINARY(32)

    # Fingerprint: first 6 bytes of BLAKE2s of the full token → 12 hex chars
    fingerprint = hashlib.blake2s(token.encode("utf-8"), digest_size=6).hexdigest()

    return {
        "token": token,
        "public_id": public_id,
        "secret_hash": secret_hash,
        "fingerprint": fingerprint,
        "secret_last4": secret[-4:],
    }


def verify_api_key_token(presented_token: str, public_id: str, stored_hash: bytes) -> bool:
    """Verify a presented API key token against a stored hash.

    Uses constant-time comparison (hmac.compare_digest) to prevent timing attacks.
    For malformed tokens, computes a dummy hash so rejection time matches valid tokens.

    Args:
        presented_token: The full token string from the client (e.g., "sk_abc123.xyz789...")
        public_id: The expected public_id portion (from DB lookup)
        stored_hash: The BINARY(32) HMAC-SHA-256 hash stored in the database

    Returns:
        True if the token is valid, False otherwise
    """
    # Pre-compute dummy hash for malformed tokens (timing-attack resistance)
    dummy = hmac.digest(API_KEY_PEPPER, b"v1:invalid:invalid", "sha256")

    try:
        # Parse: sk_{public_id}.{secret}
        # Split on the LAST dot to separate public_id from secret
        left, secret = presented_token.rsplit(".", 1)

        # Split left side: "sk_{public_id}" → prefix "sk" and the public_id
        if not left.startswith("sk_"):
            return hmac.compare_digest(dummy, stored_hash)

        token_public_id = left[3:]  # Remove "sk_" prefix

        if token_public_id != public_id:
            return hmac.compare_digest(dummy, stored_hash)
    except ValueError:
        # rsplit failed — malformed token (no dot found)
        return hmac.compare_digest(dummy, stored_hash)

    # Compute candidate hash from the presented token
    material = f"{HASH_VERSION}:{public_id}:{secret}".encode("utf-8")
    candidate = hmac.digest(API_KEY_PEPPER, material, "sha256")

    # Constant-time comparison
    return hmac.compare_digest(candidate, stored_hash)


def encode_secret_hash_for_cache(stored_hash: bytes) -> str:
    """Encode the stored BINARY(32) hash as hex for the JSON validation cache entry.

    The cache entry carries the stored hash (never the secret) so every cache hit
    can re-verify the presented token instead of trusting the public_id alone.
    """
    return bytes(stored_hash).hex()


def verify_api_key_token_against_cache(presented_token: str, public_id: str, cached: Optional[dict]) -> bool:
    """Verify a presented token against the stored hash held in a cache entry.

    A cache hit is only trustworthy when the presented secret matches. Entries that
    are not "valid", lack a well-formed hash (e.g. written before hashes were cached),
    or do not match must be treated as a cache miss by the caller.

    Args:
        presented_token: The full token string from the client
        public_id: The public_id parsed from the presented token (cache key)
        cached: The decoded apikey:{public_id} cache entry, or None

    Returns:
        True only if the entry is valid and the presented token verifies against it
    """
    if not cached or cached.get("validation_status") != "valid":
        return False

    encoded_hash = cached.get("secret_hash")
    if not isinstance(encoded_hash, str):
        return False

    try:
        stored_hash = bytes.fromhex(encoded_hash)
    except ValueError:
        return False

    if len(stored_hash) != hashlib.sha256().digest_size:
        return False

    return verify_api_key_token(presented_token, public_id, stored_hash)
