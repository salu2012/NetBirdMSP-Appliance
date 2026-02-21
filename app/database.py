"""Database setup and session management for NetBird MSP Appliance."""

import os
import sys
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker, declarative_base

DATABASE_PATH = os.environ.get("DATABASE_PATH", "/app/data/netbird_msp.db")
DATABASE_URL = f"sqlite:///{DATABASE_PATH}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)

# Enable WAL mode and foreign keys for SQLite
@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """Yield a database session, ensuring it is closed after use."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all database tables and run lightweight migrations."""
    from app.models import (  # noqa: F401
        Customer,
        Deployment,
        DeploymentLog,
        SystemConfig,
        User,
    )

    Base.metadata.create_all(bind=engine)
    _run_migrations()

    # Insert default SystemConfig row (id=1) if it doesn't exist yet
    db = SessionLocal()
    try:
        if not db.query(SystemConfig).filter(SystemConfig.id == 1).first():
            db.add(SystemConfig(
                id=1,
                base_domain="example.com",
                admin_email="admin@example.com",
                npm_api_url="http://localhost:81",
                npm_api_email_encrypted="",
                npm_api_password_encrypted="",
            ))
            db.commit()
    finally:
        db.close()


def _run_migrations() -> None:
    """Add columns that may be missing from older database versions."""
    import sqlite3

    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    def _has_column(table: str, column: str) -> bool:
        cursor.execute(f"PRAGMA table_info({table})")
        return any(row[1] == column for row in cursor.fetchall())

    migrations = [
        ("deployments", "dashboard_port", "INTEGER"),
        ("system_config", "dashboard_base_port", "INTEGER DEFAULT 9000"),
        ("deployments", "netbird_admin_email", "TEXT"),
        ("deployments", "netbird_admin_password", "TEXT"),
        ("system_config", "branding_name", "TEXT DEFAULT 'NetBird MSP Appliance'"),
        ("system_config", "branding_logo_path", "TEXT"),
        ("users", "role", "TEXT DEFAULT 'admin'"),
        ("users", "auth_provider", "TEXT DEFAULT 'local'"),
        ("system_config", "azure_enabled", "BOOLEAN DEFAULT 0"),
        ("system_config", "azure_tenant_id", "TEXT"),
        ("system_config", "azure_client_id", "TEXT"),
        ("system_config", "azure_client_secret_encrypted", "TEXT"),
        ("system_config", "branding_subtitle", "TEXT DEFAULT 'Multi-Tenant Management Platform'"),
        ("system_config", "default_language", "TEXT DEFAULT 'en'"),
        ("users", "default_language", "TEXT"),
        ("deployments", "npm_stream_id", "INTEGER"),
        ("system_config", "mfa_enabled", "BOOLEAN DEFAULT 0"),
        ("users", "totp_secret_encrypted", "TEXT"),
        ("users", "totp_enabled", "BOOLEAN DEFAULT 0"),
        ("system_config", "ssl_mode", "TEXT DEFAULT 'letsencrypt'"),
        ("system_config", "wildcard_cert_id", "INTEGER"),
        # Windows DNS
        ("system_config", "dns_enabled", "BOOLEAN DEFAULT 0"),
        ("system_config", "dns_server", "TEXT"),
        ("system_config", "dns_username", "TEXT"),
        ("system_config", "dns_password_encrypted", "TEXT"),
        ("system_config", "dns_zone", "TEXT"),
        ("system_config", "dns_record_ip", "TEXT"),
        # LDAP
        ("system_config", "ldap_enabled", "BOOLEAN DEFAULT 0"),
        ("system_config", "ldap_server", "TEXT"),
        ("system_config", "ldap_port", "INTEGER DEFAULT 389"),
        ("system_config", "ldap_use_ssl", "BOOLEAN DEFAULT 0"),
        ("system_config", "ldap_bind_dn", "TEXT"),
        ("system_config", "ldap_bind_password_encrypted", "TEXT"),
        ("system_config", "ldap_base_dn", "TEXT"),
        ("system_config", "ldap_user_filter", "TEXT DEFAULT '(sAMAccountName={username})'"),
        ("system_config", "ldap_group_dn", "TEXT"),
    ]
    for table, column, col_type in migrations:
        if not _has_column(table, column):
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")

    conn.commit()
    conn.close()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "init":
        init_db()
        print("Database initialized successfully.")
