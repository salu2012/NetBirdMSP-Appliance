"""System configuration API — read/write all settings from the database.

There is no .env file. Every setting lives in the ``system_config`` table
(singleton row with id=1) and is editable via the Web UI settings page.
"""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
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
