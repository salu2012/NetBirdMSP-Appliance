"""User management API — CRUD operations for local users."""

import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import User
from app.utils.security import hash_password
from app.utils.validators import UserCreate, UserUpdate

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("")
async def list_users(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all users."""
    users = db.query(User).order_by(User.id).all()
    return [u.to_dict() for u in users]


@router.post("")
async def create_user(
    payload: UserCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new local user."""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can create new users.",
        )

    existing = db.query(User).filter(User.username == payload.username).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Username '{payload.username}' already exists.",
        )

    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        email=payload.email,
        is_active=True,
        role="admin",
        auth_provider="local",
        default_language=payload.default_language,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    logger.info("User '%s' created by '%s'.", user.username, current_user.username)
    return user.to_dict()


@router.put("/{user_id}")
async def update_user(
    user_id: int,
    payload: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update an existing user (email, is_active, role)."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    update_data = payload.model_dump(exclude_none=True)
    for field, value in update_data.items():
        if hasattr(user, field):
            setattr(user, field, value)

    db.commit()
    db.refresh(user)

    logger.info("User '%s' updated by '%s'.", user.username, current_user.username)
    return user.to_dict()


@router.delete("/{user_id}")
async def delete_user(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a user (cannot delete yourself)."""
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot delete your own account.",
        )

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    username = user.username
    db.delete(user)
    db.commit()

    logger.info("User '%s' deleted by '%s'.", username, current_user.username)
    return {"message": f"User '{username}' deleted."}


@router.post("/{user_id}/reset-password")
async def reset_password(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate a new random password for a user."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    if user.auth_provider != "local":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot reset password for external auth users (Azure AD / LDAP).",
        )

    new_password = secrets.token_urlsafe(16)
    user.password_hash = hash_password(new_password)
    db.commit()

    logger.info("Password reset for user '%s' by '%s'.", user.username, current_user.username)
    return {"message": "Password reset successfully.", "new_password": new_password}


@router.post("/{user_id}/reset-mfa")
async def reset_mfa(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Reset MFA (TOTP) for a user. They will need to set up again on next login."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    if user.auth_provider != "local":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot reset MFA for external auth users (Azure AD / LDAP).",
        )

    user.totp_enabled = False
    user.totp_secret_encrypted = None
    db.commit()

    logger.info("MFA reset for user '%s' by '%s'.", user.username, current_user.username)
    return {"message": f"MFA reset for '{user.username}'."}
