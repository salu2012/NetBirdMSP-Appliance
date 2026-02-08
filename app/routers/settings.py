"""System configuration API — read/write all settings from the database.

There is no .env file. Every setting lives in the ``system_config`` table
(singleton row with id=1) and is editable via the Web UI settings page.
"""

import logging
import os
import shutil
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import SystemConfig, User
from app.services import npm_service
from app.utils.config import get_system_config
from app.utils.security import encrypt_value
from app.utils.validators import SystemConfigUpdate

logger = logging.getLogger(__name__)
router = APIRouter()

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "static", "uploads")
MAX_LOGO_SIZE = 512 * 1024  # 500 KB
ALLOWED_LOGO_TYPES = {"image/png", "image/jpeg", "image/svg+xml"}


@router.get("/system")
async def get_settings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return all system configuration values (token masked).

    Returns:
        System config dict.
    """
    row = db.query(SystemConfig).filter(SystemConfig.id == 1).first()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="System configuration not initialized. Run install.sh first.",
        )
    return row.to_dict()


@router.put("/system")
async def update_settings(
    payload: SystemConfigUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update system configuration values.

    Only provided (non-None) fields are updated. NPM credentials are
    encrypted before storage.

    Args:
        payload: Fields to update.

    Returns:
        Updated system config dict.
    """
    row = db.query(SystemConfig).filter(SystemConfig.id == 1).first()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="System configuration not initialized.",
        )

    update_data = payload.model_dump(exclude_none=True)

    # Handle NPM credentials encryption
    if "npm_api_email" in update_data:
        raw_email = update_data.pop("npm_api_email")
        row.npm_api_email_encrypted = encrypt_value(raw_email)
    if "npm_api_password" in update_data:
        raw_password = update_data.pop("npm_api_password")
        row.npm_api_password_encrypted = encrypt_value(raw_password)

    # Handle Azure client secret encryption
    if "azure_client_secret" in update_data:
        raw_secret = update_data.pop("azure_client_secret")
        row.azure_client_secret_encrypted = encrypt_value(raw_secret)

    for field, value in update_data.items():
        if hasattr(row, field):
            setattr(row, field, value)

    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)

    logger.info("System configuration updated by %s.", current_user.username)
    return row.to_dict()


@router.get("/test-npm")
async def test_npm(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Test connectivity to the Nginx Proxy Manager API.

    Loads the NPM URL and decrypted token from the database and attempts
    to list proxy hosts.

    Returns:
        Dict with ``ok`` and ``message``.
    """
    config = get_system_config(db)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="System configuration not initialized.",
        )
    if not config.npm_api_url or not config.npm_api_email or not config.npm_api_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="NPM API URL or credentials not configured.",
        )

    result = await npm_service.test_npm_connection(
        config.npm_api_url, config.npm_api_email, config.npm_api_password
    )
    return result


@router.get("/branding")
async def get_branding(db: Session = Depends(get_db)):
    """Public endpoint — returns branding info for the login page (no auth required)."""
    row = db.query(SystemConfig).filter(SystemConfig.id == 1).first()
    if not row:
        return {
            "branding_name": "NetBird MSP Appliance",
            "branding_subtitle": "Multi-Tenant Management Platform",
            "branding_logo_path": None,
            "default_language": "en",
        }
    return {
        "branding_name": row.branding_name or "NetBird MSP Appliance",
        "branding_subtitle": row.branding_subtitle or "Multi-Tenant Management Platform",
        "branding_logo_path": row.branding_logo_path,
        "default_language": row.default_language or "en",
    }


@router.post("/branding/logo")
async def upload_logo(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload a branding logo image (PNG, JPG, SVG, max 500KB)."""
    if file.content_type not in ALLOWED_LOGO_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File type '{file.content_type}' not allowed. Use PNG, JPG, or SVG.",
        )

    content = await file.read()
    if len(content) > MAX_LOGO_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large ({len(content)} bytes). Maximum is {MAX_LOGO_SIZE} bytes.",
        )

    os.makedirs(UPLOAD_DIR, exist_ok=True)

    ext_map = {"image/png": ".png", "image/jpeg": ".jpg", "image/svg+xml": ".svg"}
    ext = ext_map.get(file.content_type, ".png")
    filename = f"logo{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)

    with open(filepath, "wb") as f:
        f.write(content)

    logo_url = f"/static/uploads/{filename}"

    row = db.query(SystemConfig).filter(SystemConfig.id == 1).first()
    if row:
        row.branding_logo_path = logo_url
        row.updated_at = datetime.utcnow()
        db.commit()

    logger.info("Logo uploaded by %s: %s", current_user.username, logo_url)
    return {"branding_logo_path": logo_url}


@router.delete("/branding/logo")
async def delete_logo(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove the branding logo and reset to default icon."""
    row = db.query(SystemConfig).filter(SystemConfig.id == 1).first()
    if row and row.branding_logo_path:
        old_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            row.branding_logo_path.lstrip("/"),
        )
        if os.path.isfile(old_path):
            os.remove(old_path)
        row.branding_logo_path = None
        row.updated_at = datetime.utcnow()
        db.commit()

    return {"branding_logo_path": None}
