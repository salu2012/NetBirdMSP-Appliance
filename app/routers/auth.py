"""Authentication API endpoints — login, logout, current user, password change, MFA, Azure AD."""

import base64
import io
import logging
import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import create_access_token, create_mfa_token, get_current_user, verify_mfa_token
from app.models import SystemConfig, User
from app.utils.security import (
    decrypt_value,
    encrypt_value,
    generate_totp_secret,
    generate_totp_uri,
    hash_password,
    verify_password,
    verify_totp,
)
from app.utils.validators import ChangePasswordRequest, LoginRequest, MfaTokenRequest, MfaVerifyRequest

logger = logging.getLogger(__name__)
router = APIRouter()

from app.limiter import limiter


@router.post("/login")
@limiter.limit("10/minute")
async def login(request: Request, payload: LoginRequest, db: Session = Depends(get_db)):
    """Authenticate with username/password. May require MFA as a second step.

    Rate-limited to 10 attempts per minute per IP address.
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

    # Check if MFA is required (only for local users)
    if user.auth_provider == "local":
        config = db.query(SystemConfig).filter(SystemConfig.id == 1).first()
        if config and getattr(config, "mfa_enabled", False):
            mfa_token = create_mfa_token(user.username)
            return {
                "mfa_required": True,
                "mfa_token": mfa_token,
                "totp_setup_needed": not bool(user.totp_enabled),
            }

    token = create_access_token(user.username)
    logger.info("User %s logged in.", user.username)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": user.to_dict(),
    }


# ---------------------------------------------------------------------------
# MFA endpoints
# ---------------------------------------------------------------------------
@router.post("/mfa/setup")
async def mfa_setup(payload: MfaTokenRequest, db: Session = Depends(get_db)):
    """Generate a new TOTP secret and QR code for first-time MFA setup."""
    username = verify_mfa_token(payload.mfa_token)
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    # Generate new secret and store encrypted (not yet enabled)
    secret = generate_totp_secret()
    user.totp_secret_encrypted = encrypt_value(secret)
    db.commit()

    # Generate QR code as base64 data URI
    uri = generate_totp_uri(secret, username)
    import qrcode

    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    qr_b64 = base64.b64encode(buf.getvalue()).decode()

    return {
        "secret": secret,
        "qr_code": f"data:image/png;base64,{qr_b64}",
        "otpauth_uri": uri,
    }


@router.post("/mfa/setup/complete")
async def mfa_setup_complete(payload: MfaVerifyRequest, db: Session = Depends(get_db)):
    """Verify the first TOTP code to complete MFA setup, then issue access token."""
    username = verify_mfa_token(payload.mfa_token)
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    if not user.totp_secret_encrypted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="TOTP setup not initiated. Call /auth/mfa/setup first.",
        )

    secret = decrypt_value(user.totp_secret_encrypted)
    if not verify_totp(secret, payload.totp_code):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid TOTP code.",
        )

    user.totp_enabled = True
    db.commit()

    token = create_access_token(user.username)
    logger.info("User %s completed MFA setup and logged in.", user.username)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": user.to_dict(),
    }


@router.post("/mfa/verify")
@limiter.limit("10/minute")
async def mfa_verify(request: Request, payload: MfaVerifyRequest, db: Session = Depends(get_db)):
    """Verify a TOTP code for users who already have MFA set up.

    Rate-limited to 10 attempts per minute per IP address.
    """
    username = verify_mfa_token(payload.mfa_token)
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    if not user.totp_secret_encrypted or not user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="TOTP is not set up for this user.",
        )

    secret = decrypt_value(user.totp_secret_encrypted)
    if not verify_totp(secret, payload.totp_code):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid TOTP code.",
        )

    token = create_access_token(user.username)
    logger.info("User %s passed MFA verification.", user.username)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": user.to_dict(),
    }


@router.get("/mfa/status")
async def mfa_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return MFA status for the current user and global setting."""
    config = db.query(SystemConfig).filter(SystemConfig.id == 1).first()
    return {
        "mfa_enabled_global": bool(config and getattr(config, "mfa_enabled", False)),
        "totp_enabled_user": bool(current_user.totp_enabled),
    }


@router.post("/mfa/disable")
async def mfa_disable(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Disable TOTP for the current user."""
    current_user.totp_enabled = False
    current_user.totp_secret_encrypted = None
    db.commit()
    logger.info("User %s disabled their TOTP.", current_user.username)
    return {"message": "TOTP disabled successfully."}


# ---------------------------------------------------------------------------
# Password change
# ---------------------------------------------------------------------------
@router.post("/logout")
async def logout(current_user: User = Depends(get_current_user)):
    """Logout (client-side token discard)."""
    logger.info("User %s logged out.", current_user.username)
    return {"message": "Logged out successfully."}


@router.get("/me")
async def get_me(current_user: User = Depends(get_current_user)):
    """Return the current authenticated user's profile."""
    return current_user.to_dict()


@router.post("/change-password")
async def change_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Change the current user's password."""
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect.",
        )

    current_user.password_hash = hash_password(payload.new_password)
    db.commit()
    logger.info("Password changed for user %s.", current_user.username)
    return {"message": "Password changed successfully."}


# ---------------------------------------------------------------------------
# Azure AD
# ---------------------------------------------------------------------------
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
        import httpx as _httpx

        client_secret = decrypt_value(config.azure_client_secret_encrypted)
        authority = f"https://login.microsoftonline.com/{config.azure_tenant_id}"

        msal_app = msal.ConfidentialClientApplication(
            config.azure_client_id,
            authority=authority,
            client_credential=client_secret,
        )

        result = msal_app.acquire_token_by_authorization_code(
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
        display_name = id_token_claims.get("name", email)  # noqa: F841
        user_access_token = result.get("access_token", "")

        if not email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Could not determine email from Azure AD token.",
            )

        # -----------------------------------------------------------------
        # Group membership check (Fix #3 – Azure AD group whitelist)
        # -----------------------------------------------------------------
        allowed_group_id = getattr(config, "azure_allowed_group_id", None)
        if allowed_group_id:
            # Use the user's own access token to check their group membership
            # via the Microsoft Graph API (requires GroupMember.Read.All or
            # the user's own memberOf delegated permission).
            graph_url = "https://graph.microsoft.com/v1.0/me/memberOf"
            is_member = False
            try:
                async with _httpx.AsyncClient(timeout=10) as http:
                    resp = await http.get(
                        graph_url,
                        headers={"Authorization": f"Bearer {user_access_token}"},
                    )
                    if resp.status_code == 200:
                        groups = resp.json().get("value", [])
                        is_member = any(
                            g.get("id") == allowed_group_id for g in groups
                        )
                    else:
                        logger.warning(
                            "Graph API group check returned %s for user '%s'.",
                            resp.status_code, email,
                        )
            except Exception as graph_exc:
                logger.error("Graph API group check failed: %s", graph_exc)
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Could not verify Azure AD group membership. Please try again.",
                )

            if not is_member:
                logger.warning(
                    "Azure AD login denied for '%s': not a member of required group '%s'.",
                    email, allowed_group_id,
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied: you are not a member of the required Azure AD group.",
                )
        else:
            logger.warning(
                "azure_allowed_group_id is not configured. All Azure AD tenant users can log in. "
                "Set azure_allowed_group_id in Settings to restrict access."
            )

        # Find or create user
        user = db.query(User).filter(User.username == email).first()
        if not user:
            user = User(
                username=email,
                password_hash=hash_password(secrets.token_urlsafe(32)),
                email=email,
                is_active=True,
                role="viewer",  # New Azure users start as viewer; promote manually
                auth_provider="azure",
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            logger.info("Azure AD user '%s' auto-created with role 'viewer'.", email)
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
