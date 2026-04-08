"""
authz.py - Access-aware retrieval filter for policy-sop-assistant.

Resolves caller identity via Google Identity token, fetches the caller's
Google Workspace / IAM group memberships, and appends ACL filter clauses
to Vertex AI Search queries so users only receive documents they are
authorized to view.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import Request, HTTPException, status
import google.auth
import google.auth.transport.requests
from google.oauth2 import id_token
from google.cloud import resourcemanager_v3

logger = logging.getLogger(__name__)


def resolve_caller_groups(request: Request) -> List[str]:
    """
    Extract caller email from Bearer token and return their group memberships.

    Returns a list of group emails the caller belongs to.
    Raises HTTPException(401) if the token is invalid or missing.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header.",
        )
    token = auth_header.removeprefix("Bearer ").strip()
    try:
        # Verify the Google Identity token
        request_adapter = google.auth.transport.requests.Request()
        claims = id_token.verify_firebase_token(token, request_adapter)
        caller_email: str = claims["email"]
    except Exception as exc:
        logger.warning("Token verification failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not verify identity token.",
        ) from exc

    # Fetch group memberships via Cloud Identity Groups API (stub - extend for your org)
    groups = _fetch_group_memberships(caller_email)
    logger.info("Caller %s belongs to groups: %s", caller_email, groups)
    return groups


def _fetch_group_memberships(email: str) -> List[str]:
    """
    Stub: fetch Google Workspace group memberships for a given email.

    In production, call the Cloud Identity Groups API:
        GET https://cloudidentity.googleapis.com/v1/groups/-/memberships:searchTransitiveGroups
        ?query=member_key_id='{email}'

    Returns a list of group email addresses.
    """
    # TODO: Replace with real Cloud Identity Groups API call
    logger.debug("Fetching group memberships for %s (stub)", email)
    return [email]  # Default: user can only see their own docs


def build_acl_filter(caller_groups: List[str]) -> Optional[str]:
    """
    Build a Vertex AI Search filter expression that restricts results
    to documents whose acl_groups metadata field overlaps with the
    caller's group memberships.

    Example filter string:
        acl_groups: ANY("group-a@example.com", "group-b@example.com")

    Returns None if no groups are available (no filter applied - open access).
    """
    if not caller_groups:
        return None
    quoted = ", ".join(f'"{g}"' for g in caller_groups)
    return f"acl_groups: ANY({quoted})"
