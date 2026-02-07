"""Authentication API endpoints — login, logout, current user, password change."""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import create_access_token, get_current_user
from app.models import User
from app.utils.security import hash_password, verify_password
from app.utils.validators import ChangePasswordRequest, LoginRequest

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/login")
async def login(payload: LoginRequest, db: Session = Depends(get_db)):
    """Authenticate and return a JWT token.

    Args:
        payload: Username and password.
        db: Database session.

    Returns:
        JSON with ``access_token`` and ``token_type``.
    """
    user = db.query(User).filter(User.username == payload.username).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled.",
        )

    token = create_access_token(user.username)
    logger.info("User %s logged in.", user.username)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": user.to_dict(),
    }


@router.post("/logout")
async def logout(current_user: User = Depends(get_current_user)):
    """Logout (client-side token discard).

    Returns:
        Confirmation message.
    """
    logger.info("User %s logged out.", current_user.username)
    return {"message": "Logged out successfully."}


@router.get("/me")
async def get_me(current_user: User = Depends(get_current_user)):
    """Return the current authenticated user's profile.

    Returns:
        User dict (no password hash).
    """
    return current_user.to_dict()


@router.post("/change-password")
async def change_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Change the current user's password.

    Args:
        payload: Current and new password.
        current_user: Authenticated user.
        db: Database session.

    Returns:
        Confirmation message.
    """
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect.",
        )

    current_user.password_hash = hash_password(payload.new_password)
    db.commit()
    logger.info("Password changed for user %s.", current_user.username)
    return {"message": "Password changed successfully."}
