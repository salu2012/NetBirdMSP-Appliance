"""Configuration management — loads all settings from the database (system_config table).

There is NO .env file for application config. The install.sh script collects values
interactively and seeds them into the database. The Web UI settings page allows
editing every value at runtime.
"""

import os
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from app.utils.security import decrypt_value


@dataclass
class AppConfig:
    """In-memory snapshot of system configuration."""

    base_domain: str
    admin_email: str
    npm_api_url: str
    npm_api_email: str  # decrypted — NPM login email
    npm_api_password: str  # decrypted — NPM login password
    netbird_management_image: str
    netbird_signal_image: str
    netbird_relay_image: str
    netbird_dashboard_image: str
    data_dir: str
    docker_network: str
    relay_base_port: int


# Environment-level settings (not stored in DB)
SECRET_KEY: str = os.environ.get("SECRET_KEY", "change-me-in-production")
DATABASE_PATH: str = os.environ.get("DATABASE_PATH", "/app/data/netbird_msp.db")
LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")
JWT_ALGORITHM: str = "HS256"
JWT_EXPIRE_MINUTES: int = 480  # 8 hours


def get_system_config(db: Session) -> Optional[AppConfig]:
    """Load the singleton SystemConfig row and return an AppConfig dataclass.

    Args:
        db: Active SQLAlchemy session.

    Returns:
        AppConfig instance or None if the system_config row does not exist yet.
    """
    from app.models import SystemConfig

    row = db.query(SystemConfig).filter(SystemConfig.id == 1).first()
    if row is None:
        return None

    try:
        npm_email = decrypt_value(row.npm_api_email_encrypted)
    except Exception:
        npm_email = ""
    try:
        npm_password = decrypt_value(row.npm_api_password_encrypted)
    except Exception:
        npm_password = ""

    return AppConfig(
        base_domain=row.base_domain,
        admin_email=row.admin_email,
        npm_api_url=row.npm_api_url,
        npm_api_email=npm_email,
        npm_api_password=npm_password,
        netbird_management_image=row.netbird_management_image,
        netbird_signal_image=row.netbird_signal_image,
        netbird_relay_image=row.netbird_relay_image,
        netbird_dashboard_image=row.netbird_dashboard_image,
        data_dir=row.data_dir,
        docker_network=row.docker_network,
        relay_base_port=row.relay_base_port,
    )
