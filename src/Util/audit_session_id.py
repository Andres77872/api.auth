"""
Audit Session Identifiers

``api_audit_log.session_id`` and ``error_logs.session_id`` record which session
made a request. Anyone who can read those rows (``GET /admin/audit/logs``, audit
exports, direct SQL, backups) must never see token material, so a bearer token is
reduced to its ``session_id`` claim (a random id that authenticates nothing) or,
when no usable claim exists, to a keyed hash of the token.
"""

import hashlib
import hmac
import re
from functools import lru_cache
from typing import Any, Optional

import jwt

# Values of this shape are plain identifiers: UUIDs, ``usr-``/``key-`` style ids and
# integers all match. Anything else is treated as token material.
_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,128}")
# The charset alone would admit a single base64url JWT segment or an API key token,
# so values starting like one are token material too.
_TOKEN_PREFIXES = ("eyJ", "sk_")

TOKEN_HASH_PREFIX = "tokhash:"
_TOKEN_HASH_PATTERN = re.compile(re.escape(TOKEN_HASH_PREFIX) + r"[0-9a-f]{32}")
# Contains "/", which no JWT signing input can, so the derived key never produces
# a value that doubles as a token signature.
_HASH_KEY_LABEL = b"api-audit/session-id/v1"


def _is_identifier(value: str) -> bool:
    return _IDENTIFIER_PATTERN.fullmatch(value) is not None and not value.startswith(_TOKEN_PREFIXES)


@lru_cache(maxsize=1)
def _hash_key() -> bytes:
    from src.Util.JWT_Security import JWT_SECRET_KEY

    return hmac.digest(JWT_SECRET_KEY.encode("utf-8"), _HASH_KEY_LABEL, "sha256")


def keyed_token_hash(token: str) -> str:
    """Return a stable label for ``token`` that cannot be turned back into it.

    Rows written with the same token share the label, so they still correlate.
    """
    digest = hmac.new(_hash_key(), token.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{TOKEN_HASH_PREFIX}{digest[:32]}"


def _session_claim(token: str) -> Optional[str]:
    """The ``session_id`` (else ``jti``) claim of a JWT, read WITHOUT verifying it.

    The result only labels a log row. Never authorize anything from it.
    """
    try:
        claims = jwt.decode(token, options={"verify_signature": False})
    except Exception:
        # Truncated or malformed tokens (every legacy stored prefix) land here.
        return None
    for name in ("session_id", "jti"):
        value = claims.get(name)
        if value not in (None, "") and _is_identifier(str(value)):
            return str(value)
    return None


def audit_session_id(value: Any) -> Optional[str]:
    """Reduce a session reference to a value that is safe to store and to show.

    Plain identifiers (an API key id, a ``session_id`` claim, an existing keyed hash)
    pass through. Anything else is treated as token material: a JWT becomes its
    ``session_id``/``jti`` claim, and whatever cannot be decoded, including the
    256-character token prefixes older rows stored, becomes a keyed hash. Applying
    it twice changes nothing.
    """
    if value is None:
        return None
    text = str(value)
    if not text:
        return None
    if _is_identifier(text) or _TOKEN_HASH_PATTERN.fullmatch(text):
        return text
    return _session_claim(text) or keyed_token_hash(text)
