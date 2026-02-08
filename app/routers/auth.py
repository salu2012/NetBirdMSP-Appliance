"""Authentication API endpoints — login, logout, current user, password change, Azure AD."""

import logging
import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import create_access_token, get_current_user
from app.models import SystemConfig, User
from app.utils.security import decrypt_value, hash_password, verify_password
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


class AzureCallbackRequest(BaseModel):
    """Azure AD auth code callback payload."""
    code: str
    redirect_uri: str


@router.get("/azure/config")
async def get_azure_config(db: Session = Depends(get_db)):
    """Public endpoint — returns Azure AD config for the login page."""
    config = db.query(SystemConfig).filter(SystemConfig.id == 1).first()
    if not config or not config.azure_enabled:
        return {"azure_enabled": False}
    return {
        "azure_enabled": True,
        "azure_tenant_id": config.azure_tenant_id,
        "azure_client_id": config.azure_client_id,
    }


@router.post("/azure/callback")
async def azure_callback(
    payload: AzureCallbackRequest,
    db: Session = Depends(get_db),
):
    """Exchange Azure AD authorization code for tokens and authenticate."""
    config = db.query(SystemConfig).filter(SystemConfig.id == 1).first()
    if not config or not config.azure_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Azure AD authentication is not enabled.",
        )

    if not config.azure_tenant_id or not config.azure_client_id or not config.azure_client_secret_encrypted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Azure AD is not fully configured.",
        )

    try:
        import msal

        client_secret = decrypt_value(config.azure_client_secret_encrypted)
        authority = f"https://login.microsoftonline.com/{config.azure_tenant_id}"

        app = msal.ConfidentialClientApplication(
            config.azure_client_id,
            authority=authority,
            client_credential=client_secret,
        )

        result = app.acquire_token_by_authorization_code(
            payload.code,
            scopes=["User.Read"],
            redirect_uri=payload.redirect_uri,
        )

        if "error" in result:
            logger.warning("Azure AD token exchange failed: %s", result.get("error_description", result["error"]))
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=result.get("error_description", "Azure AD authentication failed."),
            )

        id_token_claims = result.get("id_token_claims", {})
        email = id_token_claims.get("preferred_username") or id_token_claims.get("email", "")
        display_name = id_token_claims.get("name", email)

        if not email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Could not determine email from Azure AD token.",
            )

        # Find or create user
        user = db.query(User).filter(User.username == email).first()
        if not user:
            user = User(
                username=email,
                password_hash=hash_password(secrets.token_urlsafe(32)),
                email=email,
                is_active=True,
                role="admin",
                auth_provider="azure",
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            logger.info("Azure AD user '%s' auto-created.", email)
        elif not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is disabled.",
            )

        token = create_access_token(user.username)
        logger.info("Azure AD user '%s' logged in.", user.username)
        return {
            "access_token": token,
            "token_type": "bearer",
            "user": user.to_dict(),
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Azure AD authentication error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Azure AD authentication error: {exc}",
        )
