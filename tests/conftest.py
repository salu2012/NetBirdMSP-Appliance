"""Shared test fixtures for the NetBird MSP Appliance test suite."""

import os
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

# Override env vars BEFORE importing app modules
os.environ["SECRET_KEY"] = "test-secret-key-for-unit-tests"
os.environ["DATABASE_PATH"] = ":memory:"

from app.database import Base
from app.models import Customer, Deployment, DeploymentLog, SystemConfig, User
from app.utils.security import hash_password, encrypt_value


@pytest.fixture()
def db_session():
    """Create an in-memory SQLite database session for tests."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _set_pragma(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    # Seed admin user
    admin = User(
        username="admin",
        password_hash=hash_password("testpassword123"),
        email="admin@test.com",
    )
    session.add(admin)

    # Seed system config
    config = SystemConfig(
        id=1,
        base_domain="test.example.com",
        admin_email="admin@test.com",
        npm_api_url="http://localhost:81/api",
        npm_api_token_encrypted=encrypt_value("test-npm-token"),
        data_dir="/tmp/netbird-test",
        docker_network="test-network",
        relay_base_port=3478,
    )
    session.add(config)
    session.commit()

    yield session
    session.close()


@pytest.fixture()
def sample_customer(db_session):
    """Create and return a sample customer."""
    customer = Customer(
        name="Test Customer",
        company="Test Corp",
        subdomain="testcust",
        email="test@example.com",
        max_devices=20,
        status="active",
    )
    db_session.add(customer)
    db_session.commit()
    db_session.refresh(customer)
    return customer


@pytest.fixture()
def sample_deployment(db_session, sample_customer):
    """Create and return a sample deployment for the sample customer."""
    deployment = Deployment(
        customer_id=sample_customer.id,
        container_prefix=f"netbird-kunde{sample_customer.id}",
        relay_udp_port=3478,
        relay_secret=encrypt_value("test-relay-secret"),
        setup_url=f"https://testcust.test.example.com",
        deployment_status="running",
    )
    db_session.add(deployment)
    db_session.commit()
    db_session.refresh(deployment)
    return deployment
