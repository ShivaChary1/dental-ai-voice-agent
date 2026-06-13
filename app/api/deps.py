import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


class CurrentUser:
    def __init__(self, user_id: uuid.UUID, clinic_id: uuid.UUID, role: str):
        self.user_id = user_id
        self.clinic_id = clinic_id
        self.role = role


async def get_current_user(
    token: Annotated[str | None, Depends(oauth2_scheme)],
) -> CurrentUser:
    if token is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")

    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")

    try:
        return CurrentUser(
            user_id=uuid.UUID(payload["sub"]),
            clinic_id=uuid.UUID(payload["clinic_id"]),
            role=payload["role"],
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token payload") from exc


def require_role(*roles: str):
    async def _check(user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
        return user

    return _check


DbSession = Annotated[AsyncSession, Depends(get_db)]
AuthedUser = Annotated[CurrentUser, Depends(get_current_user)]
