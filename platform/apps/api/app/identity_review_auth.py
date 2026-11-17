"""Authentication for the provenance and identity-review API.

Credentials are configured as reviewer IDs mapped to SHA-256 token hashes.
The API never accepts reviewer identity from a request body.
"""
import hashlib
import hmac
import json

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings

_bearer = HTTPBearer(auto_error=False)


def require_identity_reviewer(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    """Return the configured reviewer ID for a valid bearer token; fail closed."""
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="A valid identity-review credential is required.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized

    try:
        configured = json.loads(settings.identity_review_credentials or "{}")
    except (TypeError, ValueError):
        raise unauthorized
    if not isinstance(configured, dict) or not configured:
        raise unauthorized

    supplied_hash = hashlib.sha256(credentials.credentials.encode("utf-8")).hexdigest()
    for reviewer_id, expected_hash in configured.items():
        if (
            isinstance(reviewer_id, str)
            and reviewer_id.strip()
            and isinstance(expected_hash, str)
            and hmac.compare_digest(supplied_hash, expected_hash.strip().lower())
        ):
            return reviewer_id.strip()
    raise unauthorized
