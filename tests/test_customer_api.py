"""Unit and API tests for customer management."""

import os
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

os.environ["SECRET_KEY"] = "test-secret-key-for-unit-tests"
os.environ["DATABASE_PATH"] = ":memory:"

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app
from app.models import Customer, User, SystemConfig
from app.utils.security import hash_password, encrypt_value
from app.dependencies import get_current_user


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------
@pytest.fixture()
def test_db():
    """Create a test database."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _set_pragma(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    # Seed data
    admin = User(username="admin", password_hash=hash_password("testpassword123"), email="admin@test.com")
    session.add(admin)

    config = SystemConfig(
        id=1,
        base_domain="test.example.com",
        admin_email="admin@test.com",
        npm_api_url="http://localhost:81/api",
        npm_api_email_encrypted=encrypt_value("admin@npm.local"),
        npm_api_password_encrypted=encrypt_value("test-npm-password"),
    )
    session.add(config)
    session.commit()

    yield session
    session.close()


@pytest.fixture()
def client(test_db):
    """Create a test client with overridden dependencies."""
    admin = test_db.query(User).filter(User.username == "admin").first()

    def override_get_db():
        yield test_db

    def override_get_user():
        return admin

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_user

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
class TestCustomerList:
    """Tests for GET /api/customers."""

    def test_empty_list(self, client: TestClient):
        """List returns empty when no customers exist."""
        resp = client.get("/api/customers")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []

    def test_list_with_customers(self, client: TestClient, test_db):
        """List returns customers after creating them."""
        for i in range(3):
            test_db.add(Customer(name=f"Customer {i}", subdomain=f"cust{i}", email=f"c{i}@test.com"))
        test_db.commit()

        resp = client.get("/api/customers")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert len(data["items"]) == 3

    def test_search_filter(self, client: TestClient, test_db):
        """Search filters customers by name/subdomain/email."""
        test_db.add(Customer(name="Alpha Corp", subdomain="alpha", email="alpha@test.com"))
        test_db.add(Customer(name="Beta Inc", subdomain="beta", email="beta@test.com"))
        test_db.commit()

        resp = client.get("/api/customers?search=alpha")
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["name"] == "Alpha Corp"

    def test_status_filter(self, client: TestClient, test_db):
        """Status filter returns only matching customers."""
        test_db.add(Customer(name="Active", subdomain="active1", email="a@t.com", status="active"))
        test_db.add(Customer(name="Error", subdomain="error1", email="e@t.com", status="error"))
        test_db.commit()

        resp = client.get("/api/customers?status=error")
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["status"] == "error"


class TestCustomerCreate:
    """Tests for POST /api/customers."""

    @patch("app.services.netbird_service.deploy_customer", new_callable=AsyncMock)
    def test_create_customer(self, mock_deploy, client: TestClient):
        """Creating a customer returns 201 and triggers deployment."""
        mock_deploy.return_value = {"success": True, "setup_url": "https://new.test.example.com"}

        resp = client.post("/api/customers", json={
            "name": "New Customer",
            "subdomain": "newcust",
            "email": "new@test.com",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "New Customer"
        assert data["subdomain"] == "newcust"

    def test_duplicate_subdomain(self, client: TestClient, test_db):
        """Duplicate subdomain returns 409."""
        test_db.add(Customer(name="Existing", subdomain="taken", email="e@test.com"))
        test_db.commit()

        resp = client.post("/api/customers", json={
            "name": "Another",
            "subdomain": "taken",
            "email": "a@test.com",
        })
        assert resp.status_code == 409

    def test_invalid_subdomain(self, client: TestClient):
        """Invalid subdomain format returns 422."""
        resp = client.post("/api/customers", json={
            "name": "Bad",
            "subdomain": "UPPER_CASE!",
            "email": "b@test.com",
        })
        assert resp.status_code == 422

    def test_invalid_email(self, client: TestClient):
        """Invalid email returns 422."""
        resp = client.post("/api/customers", json={
            "name": "Bad Email",
            "subdomain": "bademail",
            "email": "not-an-email",
        })
        assert resp.status_code == 422


class TestCustomerDetail:
    """Tests for GET/PUT/DELETE /api/customers/{id}."""

    def test_get_customer(self, client: TestClient, test_db):
        """Get customer returns full details."""
        cust = Customer(name="Detail Test", subdomain="detail", email="d@test.com")
        test_db.add(cust)
        test_db.commit()
        test_db.refresh(cust)

        resp = client.get(f"/api/customers/{cust.id}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Detail Test"

    def test_get_nonexistent(self, client: TestClient):
        """Get nonexistent customer returns 404."""
        resp = client.get("/api/customers/999")
        assert resp.status_code == 404

    def test_update_customer(self, client: TestClient, test_db):
        """Update customer fields."""
        cust = Customer(name="Before", subdomain="update1", email="u@test.com")
        test_db.add(cust)
        test_db.commit()
        test_db.refresh(cust)

        resp = client.put(f"/api/customers/{cust.id}", json={"name": "After"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "After"

    @patch("app.services.netbird_service.undeploy_customer", new_callable=AsyncMock)
    def test_delete_customer(self, mock_undeploy, client: TestClient, test_db):
        """Delete customer returns success."""
        mock_undeploy.return_value = {"success": True}

        cust = Customer(name="ToDelete", subdomain="del1", email="del@test.com")
        test_db.add(cust)
        test_db.commit()
        test_db.refresh(cust)

        resp = client.delete(f"/api/customers/{cust.id}")
        assert resp.status_code == 200

        # Verify deleted
        resp = client.get(f"/api/customers/{cust.id}")
        assert resp.status_code == 404
