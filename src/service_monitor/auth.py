"""Simple bearer-token admin authentication."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import Settings

_bearer_scheme = HTTPBearer(auto_error=False)


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def require_admin(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> None:
    """Allow protected routes when configured for demo/local use or valid admin key."""
    settings = get_app_settings(request)

    if settings.admin_api_key:
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid Authorization header. Use Bearer token.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if credentials.credentials != settings.admin_api_key:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid admin API key.",
            )
        return

    if settings.demo_mode:
        return

    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=(
            "Admin API key is required for protected actions when DEMO_MODE is disabled. "
            "Set ADMIN_API_KEY or enable DEMO_MODE=true for local development."
        ),
    )
