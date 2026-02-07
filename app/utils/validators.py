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
