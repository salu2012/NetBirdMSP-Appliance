"""FastAPI dependencies — JWT authentication, database session, rate limiting."""

from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.utils.config import JWT_ALGORITHM, JWT_EXPIRE_MINUTES, SECRET_KEY

security_scheme = HTTPBearer(auto_error=False)


def create_access_token(username: str, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token.

    Args:
        username: The user identity to encode.
        expires_delta: Custom expiration; defaults to JWT_EXPIRE_MINUTES.

    Returns:
        Encoded JWT string.
    """
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=JWT_EXPIRE_MINUTES))
    payload = {"sub": username, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGORITHM)


def create_mfa_token(username: str) -> str:
    """Create a short-lived JWT for the MFA verification step (5 min)."""
    expire = datetime.utcnow() + timedelta(minutes=5)
    payload = {"sub": username, "exp": expire, "purpose": "mfa"}
    return jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGORITHM)


def verify_mfa_token(token: str) -> str:
    """Verify an MFA-purpose JWT and return the username.

    Raises HTTPException if the token is invalid, expired, or not an MFA token.
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])
        if payload.get("purpose") != "mfa":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid MFA token.",
            )
        username: Optional[str] = payload.get("sub")
        if not username:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid MFA token.",
            )
        return username
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="MFA token expired or invalid.",
        )


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Validate the JWT bearer token and return the authenticated user.

    Args:
        credentials: Bearer token from the Authorization header.
        db: Database session.

    Returns:
        The authenticated User ORM object.

    Raises:
        HTTPException: If the token is missing, invalid, or the user is inactive.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])
        username: Optional[str] = payload.get("sub")
        if username is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload.",
            )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
        )

    user = db.query(User).filter(User.username == username).first()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive.",
        )
    return user
