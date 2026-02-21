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
    dashboard_base_port: int
    ssl_mode: str
    wildcard_cert_id: int | None
    # Windows DNS
    dns_enabled: bool = False
    dns_server: str = ""
    dns_username: str = ""
    dns_password: str = ""  # decrypted
    dns_zone: str = ""
    dns_record_ip: str = ""
    # LDAP
    ldap_enabled: bool = False
    ldap_server: str = ""
    ldap_port: int = 389
    ldap_use_ssl: bool = False
    ldap_bind_dn: str = ""
    ldap_bind_password: str = ""  # decrypted
    ldap_base_dn: str = ""
    ldap_user_filter: str = "(sAMAccountName={username})"
    ldap_group_dn: str = ""


# ---------------------------------------------------------------------------
# Environment-level settings (not stored in DB)
# ---------------------------------------------------------------------------

# Known insecure default values that must never be used in production.
_INSECURE_KEY_VALUES: set[str] = {
    "change-me-in-production",
    "local-test-secret-key-not-for-production-1234",
    "secret",
    "changeme",
    "",
}

SECRET_KEY: str = os.environ.get("SECRET_KEY", "")

# --- Startup security gate ---
# Abort immediately if the key is missing, too short, or a known default.
_MIN_KEY_LENGTH = 32
if SECRET_KEY in _INSECURE_KEY_VALUES or len(SECRET_KEY) < _MIN_KEY_LENGTH:
    raise RuntimeError(
        "FATAL: SECRET_KEY is insecure, missing, or too short.\n"
        f"  Current length : {len(SECRET_KEY)} characters (minimum: {_MIN_KEY_LENGTH})\n"
        "  The key must be at least 32 random characters and must not be a known default value.\n"
        "  Generate a secure key with:\n"
        "    python3 -c \"import secrets; print(secrets.token_hex(32))\"\n"
        "  Then set it in your .env file as: SECRET_KEY=<generated-value>"
    )

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
    try:
        dns_password = decrypt_value(row.dns_password_encrypted) if row.dns_password_encrypted else ""
    except Exception:
        dns_password = ""
    try:
        ldap_bind_password = decrypt_value(row.ldap_bind_password_encrypted) if row.ldap_bind_password_encrypted else ""
    except Exception:
        ldap_bind_password = ""

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
        dashboard_base_port=getattr(row, "dashboard_base_port", 9000) or 9000,
        ssl_mode=getattr(row, "ssl_mode", "letsencrypt") or "letsencrypt",
        wildcard_cert_id=getattr(row, "wildcard_cert_id", None),
        dns_enabled=bool(getattr(row, "dns_enabled", False)),
        dns_server=getattr(row, "dns_server", "") or "",
        dns_username=getattr(row, "dns_username", "") or "",
        dns_password=dns_password,
        dns_zone=getattr(row, "dns_zone", "") or "",
        dns_record_ip=getattr(row, "dns_record_ip", "") or "",
        ldap_enabled=bool(getattr(row, "ldap_enabled", False)),
        ldap_server=getattr(row, "ldap_server", "") or "",
        ldap_port=getattr(row, "ldap_port", 389) or 389,
        ldap_use_ssl=bool(getattr(row, "ldap_use_ssl", False)),
        ldap_bind_dn=getattr(row, "ldap_bind_dn", "") or "",
        ldap_bind_password=ldap_bind_password,
        ldap_base_dn=getattr(row, "ldap_base_dn", "") or "",
        ldap_user_filter=getattr(row, "ldap_user_filter", "(sAMAccountName={username})") or "(sAMAccountName={username})",
        ldap_group_dn=getattr(row, "ldap_group_dn", "") or "",
    )
