from __future__ import annotations

import os
import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer


_bearer_scheme = HTTPBearer(auto_error=False)


def _require_token(
    credentials: HTTPAuthorizationCredentials | None,
    *,
    environment_name: str,
) -> None:
    expected_token = os.getenv(environment_name, "").strip()

    if not expected_token:
        environment = os.getenv(
            "PAUSEABLE_ENV",
            "development",
        ).strip().lower()
        if environment != "production":
            return
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{environment_name} is not configured",
        )

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token is required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not secrets.compare_digest(credentials.credentials, expected_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid bearer token",
        )


def require_app_token(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(_bearer_scheme),
    ],
) -> None:
    _require_token(
        credentials,
        environment_name="PAUSEABLE_APP_TOKEN",
    )


def require_worker_token(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(_bearer_scheme),
    ],
) -> None:
    _require_token(
        credentials,
        environment_name="PAUSEABLE_WORKER_TOKEN",
    )


def require_device_token(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(_bearer_scheme),
    ],
) -> None:
    _require_token(
        credentials,
        environment_name="PAUSEABLE_DEVICE_TOKEN",
    )
