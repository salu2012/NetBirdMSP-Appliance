"""Input validation with Pydantic models for all API endpoints."""

import re
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
class LoginRequest(BaseModel):
    """Login credentials."""

    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1)


class ChangePasswordRequest(BaseModel):
    """Password change payload."""

    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=12, max_length=128)


class MfaTokenRequest(BaseModel):
    """Request containing only an MFA token (for setup initiation)."""

    mfa_token: str = Field(..., min_length=1)


class MfaVerifyRequest(BaseModel):
    """MFA TOTP verification payload."""

    mfa_token: str = Field(..., min_length=1)
    totp_code: str = Field(..., min_length=6, max_length=6)


# ---------------------------------------------------------------------------
# Customer
# ---------------------------------------------------------------------------
class CustomerCreate(BaseModel):
    """Payload to create a new customer."""

    name: str = Field(..., min_length=1, max_length=255)
    company: Optional[str] = Field(None, max_length=255)
    subdomain: str = Field(..., min_length=1, max_length=63)
    email: str = Field(..., max_length=255)
    max_devices: int = Field(default=20, ge=1, le=10000)
    notes: Optional[str] = None

    @field_validator("subdomain")
    @classmethod
    def validate_subdomain(cls, v: str) -> str:
        """Subdomain must be lowercase alphanumeric + hyphens, no leading/trailing hyphen."""
        v = v.lower().strip()
        if not re.match(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$", v):
            raise ValueError(
                "Subdomain must be lowercase, alphanumeric with hyphens, "
                "2-63 chars, no leading/trailing hyphen."
            )
        return v

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        """Basic email format check."""
        pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        if not re.match(pattern, v):
            raise ValueError("Invalid email address.")
        return v.lower().strip()


class CustomerUpdate(BaseModel):
    """Payload to update an existing customer."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    company: Optional[str] = Field(None, max_length=255)
    email: Optional[str] = Field(None, max_length=255)
    max_devices: Optional[int] = Field(None, ge=1, le=10000)
    notes: Optional[str] = None
    status: Optional[str] = None

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: Optional[str]) -> Optional[str]:
        """Basic email format check."""
        if v is None:
            return v
        pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        if not re.match(pattern, v):
            raise ValueError("Invalid email address.")
        return v.lower().strip()

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: Optional[str]) -> Optional[str]:
        """Status must be one of the allowed values."""
        if v is None:
            return v
        allowed = {"active", "inactive", "deploying", "error"}
        if v not in allowed:
            raise ValueError(f"Status must be one of: {', '.join(sorted(allowed))}")
        return v


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
class SystemConfigUpdate(BaseModel):
    """Payload to update system configuration."""

    base_domain: Optional[str] = Field(None, min_length=1, max_length=255)
    admin_email: Optional[str] = Field(None, max_length=255)
    npm_api_url: Optional[str] = Field(None, max_length=500)
    npm_api_email: Optional[str] = Field(None, max_length=255)  # NPM login email
    npm_api_password: Optional[str] = None  # NPM login password, encrypted before storage
    netbird_management_image: Optional[str] = Field(None, max_length=255)
    netbird_signal_image: Optional[str] = Field(None, max_length=255)
    netbird_relay_image: Optional[str] = Field(None, max_length=255)
    netbird_dashboard_image: Optional[str] = Field(None, max_length=255)
    data_dir: Optional[str] = Field(None, max_length=500)
    docker_network: Optional[str] = Field(None, max_length=100)
    relay_base_port: Optional[int] = Field(None, ge=1024, le=65535)
    dashboard_base_port: Optional[int] = Field(None, ge=1024, le=65535)
    branding_name: Optional[str] = Field(None, max_length=255)
    branding_subtitle: Optional[str] = Field(None, max_length=255)
    default_language: Optional[str] = Field(None, max_length=10)
    ssl_mode: Optional[str] = Field(None, max_length=20)
    wildcard_cert_id: Optional[int] = Field(None, ge=0)
    mfa_enabled: Optional[bool] = None
    azure_enabled: Optional[bool] = None
    azure_tenant_id: Optional[str] = Field(None, max_length=255)
    azure_client_id: Optional[str] = Field(None, max_length=255)
    azure_client_secret: Optional[str] = None  # encrypted before storage
    azure_allowed_group_id: Optional[str] = Field(
        None, max_length=255,
        description="Azure AD group object ID. If set, only members of this group can log in."
    )
    # Windows DNS
    dns_enabled: Optional[bool] = None
    dns_server: Optional[str] = Field(None, max_length=255)
    dns_username: Optional[str] = Field(None, max_length=255)
    dns_password: Optional[str] = None  # plaintext, encrypted before storage
    dns_zone: Optional[str] = Field(None, max_length=255)
    dns_record_ip: Optional[str] = Field(None, max_length=45)
    # LDAP
    ldap_enabled: Optional[bool] = None
    ldap_server: Optional[str] = Field(None, max_length=255)
    ldap_port: Optional[int] = Field(None, ge=1, le=65535)
    ldap_use_ssl: Optional[bool] = None
    ldap_bind_dn: Optional[str] = Field(None, max_length=500)
    ldap_bind_password: Optional[str] = None  # plaintext, encrypted before storage
    ldap_base_dn: Optional[str] = Field(None, max_length=500)
    ldap_user_filter: Optional[str] = Field(None, max_length=255)
    ldap_group_dn: Optional[str] = Field(None, max_length=500)

    @field_validator("ssl_mode")
    @classmethod
    def validate_ssl_mode(cls, v: Optional[str]) -> Optional[str]:
        """SSL mode must be 'letsencrypt' or 'wildcard'."""
        if v is None:
            return v
        allowed = {"letsencrypt", "wildcard"}
        if v not in allowed:
            raise ValueError(f"ssl_mode must be one of: {', '.join(sorted(allowed))}")
        return v

    @field_validator("base_domain")
    @classmethod
    def validate_domain(cls, v: Optional[str]) -> Optional[str]:
        """Validate domain format."""
        if v is None:
            return v
        pattern = r"^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$"
        if not re.match(pattern, v):
            raise ValueError("Invalid domain format.")
        return v.lower().strip()

    @field_validator("npm_api_url")
    @classmethod
    def validate_npm_url(cls, v: Optional[str]) -> Optional[str]:
        """NPM URL must start with http(s)://."""
        if v is None:
            return v
        if not re.match(r"^https?://", v):
            raise ValueError("NPM API URL must start with http:// or https://")
        return v.rstrip("/")

    @field_validator("admin_email")
    @classmethod
    def validate_email(cls, v: Optional[str]) -> Optional[str]:
        """Validate admin email."""
        if v is None:
            return v
        pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        if not re.match(pattern, v):
            raise ValueError("Invalid email address.")
        return v.lower().strip()


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
class UserCreate(BaseModel):
    """Payload to create a new local user."""

    username: str = Field(..., min_length=3, max_length=100)
    password: str = Field(..., min_length=8, max_length=128)
    email: Optional[str] = Field(None, max_length=255)
    default_language: Optional[str] = Field(None, max_length=10)

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_.-]+$", v):
            raise ValueError("Username may only contain letters, digits, dots, hyphens, and underscores.")
        return v.strip()

    @field_validator("email")
    @classmethod
    def validate_user_email(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        if not re.match(pattern, v):
            raise ValueError("Invalid email address.")
        return v.lower().strip()


class UserUpdate(BaseModel):
    """Payload to update an existing user."""

    email: Optional[str] = Field(None, max_length=255)
    is_active: Optional[bool] = None
    role: Optional[str] = Field(None, max_length=20)
    default_language: Optional[str] = Field(None, max_length=10)

    @field_validator("email")
    @classmethod
    def validate_user_email(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        if not re.match(pattern, v):
            raise ValueError("Invalid email address.")
        return v.lower().strip()


# ---------------------------------------------------------------------------
# Query params
# ---------------------------------------------------------------------------
class CustomerListParams(BaseModel):
    """Query parameters for listing customers."""

    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=25, ge=1, le=100)
    search: Optional[str] = None
    status: Optional[str] = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: Optional[str]) -> Optional[str]:
        """Filter status validation."""
        if v is None or v == "":
            return None
        allowed = {"active", "inactive", "deploying", "error"}
        if v not in allowed:
            raise ValueError(f"Status must be one of: {', '.join(sorted(allowed))}")
        return v
