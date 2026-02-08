"""SQLAlchemy ORM models for NetBird MSP Appliance."""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Customer(Base):
    """Customer model representing an MSP client."""

    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    company: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    subdomain: Mapped[str] = mapped_column(String(63), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    max_devices: Mapped[int] = mapped_column(Integer, default=20)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        default="active",
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'inactive', 'deploying', 'error')",
            name="ck_customer_status",
        ),
    )

    deployment: Mapped[Optional["Deployment"]] = relationship(
        "Deployment", back_populates="customer", uselist=False, cascade="all, delete-orphan"
    )
    logs: Mapped[list["DeploymentLog"]] = relationship(
        "DeploymentLog", back_populates="customer", cascade="all, delete-orphan"
    )

    def to_dict(self) -> dict:
        """Serialize customer to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "company": self.company,
            "subdomain": self.subdomain,
            "email": self.email,
            "max_devices": self.max_devices,
            "notes": self.notes,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class Deployment(Base):
    """Deployment model tracking a customer's NetBird instance."""

    __tablename__ = "deployments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("customers.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    container_prefix: Mapped[str] = mapped_column(String(100), nullable=False)
    relay_udp_port: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    dashboard_port: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    npm_proxy_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    npm_stream_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    relay_secret: Mapped[str] = mapped_column(Text, nullable=False)
    setup_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    netbird_admin_email: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    netbird_admin_password: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    deployment_status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False
    )
    deployed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_health_check: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "deployment_status IN ('pending', 'running', 'stopped', 'failed')",
            name="ck_deployment_status",
        ),
    )

    customer: Mapped["Customer"] = relationship("Customer", back_populates="deployment")

    def to_dict(self) -> dict:
        """Serialize deployment to dictionary."""
        return {
            "id": self.id,
            "customer_id": self.customer_id,
            "container_prefix": self.container_prefix,
            "relay_udp_port": self.relay_udp_port,
            "dashboard_port": self.dashboard_port,
            "npm_proxy_id": self.npm_proxy_id,
            "npm_stream_id": self.npm_stream_id,
            "relay_secret": "***",  # Never expose secrets
            "setup_url": self.setup_url,
            "has_credentials": bool(self.netbird_admin_email and self.netbird_admin_password),
            "deployment_status": self.deployment_status,
            "deployed_at": self.deployed_at.isoformat() if self.deployed_at else None,
            "last_health_check": (
                self.last_health_check.isoformat() if self.last_health_check else None
            ),
        }


class SystemConfig(Base):
    """Singleton system configuration — always id=1."""

    __tablename__ = "system_config"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, default=1
    )
    base_domain: Mapped[str] = mapped_column(String(255), nullable=False)
    admin_email: Mapped[str] = mapped_column(String(255), nullable=False)
    npm_api_url: Mapped[str] = mapped_column(String(500), nullable=False)
    npm_api_email_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    npm_api_password_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    netbird_management_image: Mapped[str] = mapped_column(
        String(255), default="netbirdio/management:latest"
    )
    netbird_signal_image: Mapped[str] = mapped_column(
        String(255), default="netbirdio/signal:latest"
    )
    netbird_relay_image: Mapped[str] = mapped_column(
        String(255), default="netbirdio/relay:latest"
    )
    netbird_dashboard_image: Mapped[str] = mapped_column(
        String(255), default="netbirdio/dashboard:latest"
    )
    data_dir: Mapped[str] = mapped_column(String(500), default="/opt/netbird-instances")
    docker_network: Mapped[str] = mapped_column(String(100), default="npm-network")
    relay_base_port: Mapped[int] = mapped_column(Integer, default=3478)
    dashboard_base_port: Mapped[int] = mapped_column(Integer, default=9000)
    branding_name: Mapped[Optional[str]] = mapped_column(
        String(255), default="NetBird MSP Appliance"
    )
    branding_subtitle: Mapped[Optional[str]] = mapped_column(
        String(255), default="Multi-Tenant Management Platform"
    )
    branding_logo_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    default_language: Mapped[Optional[str]] = mapped_column(String(10), default="en")
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    azure_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    azure_tenant_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    azure_client_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    azure_client_secret_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        CheckConstraint("id = 1", name="ck_system_config_singleton"),
    )

    def to_dict(self) -> dict:
        """Serialize config to dictionary (credentials masked)."""
        return {
            "base_domain": self.base_domain,
            "admin_email": self.admin_email,
            "npm_api_url": self.npm_api_url,
            "npm_credentials_set": bool(self.npm_api_email_encrypted and self.npm_api_password_encrypted),
            "netbird_management_image": self.netbird_management_image,
            "netbird_signal_image": self.netbird_signal_image,
            "netbird_relay_image": self.netbird_relay_image,
            "netbird_dashboard_image": self.netbird_dashboard_image,
            "data_dir": self.data_dir,
            "docker_network": self.docker_network,
            "relay_base_port": self.relay_base_port,
            "dashboard_base_port": self.dashboard_base_port,
            "branding_name": self.branding_name or "NetBird MSP Appliance",
            "branding_subtitle": self.branding_subtitle or "Multi-Tenant Management Platform",
            "branding_logo_path": self.branding_logo_path,
            "default_language": self.default_language or "en",
            "mfa_enabled": bool(self.mfa_enabled),
            "azure_enabled": bool(self.azure_enabled),
            "azure_tenant_id": self.azure_tenant_id or "",
            "azure_client_id": self.azure_client_id or "",
            "azure_client_secret_set": bool(self.azure_client_secret_encrypted),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class DeploymentLog(Base):
    """Log entries for deployment actions."""

    __tablename__ = "deployment_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        CheckConstraint(
            "status IN ('success', 'error', 'info')",
            name="ck_log_status",
        ),
    )

    customer: Mapped["Customer"] = relationship("Customer", back_populates="logs")

    def to_dict(self) -> dict:
        """Serialize log entry to dictionary."""
        return {
            "id": self.id,
            "customer_id": self.customer_id,
            "action": self.action,
            "status": self.status,
            "message": self.message,
            "details": self.details,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class User(Base):
    """Admin user model."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    role: Mapped[str] = mapped_column(String(20), default="admin")
    auth_provider: Mapped[str] = mapped_column(String(20), default="local")
    default_language: Mapped[Optional[str]] = mapped_column(String(10), nullable=True, default=None)
    totp_secret_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> dict:
        """Serialize user to dictionary (no password, no TOTP secret)."""
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "is_active": self.is_active,
            "role": self.role or "admin",
            "auth_provider": self.auth_provider or "local",
            "default_language": self.default_language,
            "totp_enabled": bool(self.totp_enabled),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
