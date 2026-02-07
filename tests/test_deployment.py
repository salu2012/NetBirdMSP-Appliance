"""Integration tests for the deployment workflow."""

import os
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

os.environ["SECRET_KEY"] = "test-secret-key-for-unit-tests"
os.environ["DATABASE_PATH"] = ":memory:"

from app.models import Customer, Deployment, DeploymentLog
from app.services import netbird_service


class TestDeploymentWorkflow:
    """Tests for the full deploy/undeploy lifecycle."""

    @patch("app.services.netbird_service.docker_service")
    @patch("app.services.netbird_service.npm_service")
    @patch("app.services.netbird_service.port_manager")
    @pytest.mark.asyncio
    async def test_successful_deployment(
        self, mock_port_mgr, mock_npm, mock_docker, db_session, sample_customer
    ):
        """Full deployment creates containers, NPM entry, and DB records."""
        mock_port_mgr.allocate_port.return_value = 3478
        mock_docker.compose_up.return_value = True
        mock_docker.wait_for_healthy.return_value = True
        mock_npm.create_proxy_host = AsyncMock(return_value={"proxy_id": 42})

        # Create temp dir for templates
        os.makedirs("/tmp/netbird-test", exist_ok=True)

        result = await netbird_service.deploy_customer(db_session, sample_customer.id)

        assert result["success"] is True
        assert "setup_url" in result
        assert result["setup_url"].startswith("https://")

        # Verify deployment record created
        dep = db_session.query(Deployment).filter(
            Deployment.customer_id == sample_customer.id
        ).first()
        assert dep is not None
        assert dep.deployment_status == "running"
        assert dep.relay_udp_port == 3478

        # Verify customer status updated
        db_session.refresh(sample_customer)
        assert sample_customer.status == "active"

    @patch("app.services.netbird_service.docker_service")
    @patch("app.services.netbird_service.npm_service")
    @patch("app.services.netbird_service.port_manager")
    @pytest.mark.asyncio
    async def test_deployment_rollback_on_docker_failure(
        self, mock_port_mgr, mock_npm, mock_docker, db_session, sample_customer
    ):
        """Failed docker compose up triggers rollback."""
        mock_port_mgr.allocate_port.return_value = 3479
        mock_docker.compose_up.side_effect = RuntimeError("Docker compose failed")
        mock_docker.compose_down.return_value = True

        os.makedirs("/tmp/netbird-test", exist_ok=True)

        result = await netbird_service.deploy_customer(db_session, sample_customer.id)

        assert result["success"] is False
        assert "Docker compose failed" in result["error"]

        # Verify rollback
        db_session.refresh(sample_customer)
        assert sample_customer.status == "error"

        # Verify error log
        logs = db_session.query(DeploymentLog).filter(
            DeploymentLog.customer_id == sample_customer.id,
            DeploymentLog.status == "error",
        ).all()
        assert len(logs) >= 1

    @patch("app.services.netbird_service.docker_service")
    @patch("app.services.netbird_service.npm_service")
    @pytest.mark.asyncio
    async def test_undeploy_customer(
        self, mock_npm, mock_docker, db_session, sample_customer, sample_deployment
    ):
        """Undeployment removes containers, NPM entry, and cleans up."""
        mock_docker.compose_down.return_value = True
        mock_npm.delete_proxy_host = AsyncMock(return_value=True)

        result = await netbird_service.undeploy_customer(db_session, sample_customer.id)

        assert result["success"] is True

        # Verify deployment record removed
        dep = db_session.query(Deployment).filter(
            Deployment.customer_id == sample_customer.id
        ).first()
        assert dep is None


class TestStartStopRestart:
    """Tests for start/stop/restart operations."""

    @patch("app.services.netbird_service.docker_service")
    def test_stop_customer(self, mock_docker, db_session, sample_customer, sample_deployment):
        """Stop sets deployment_status to stopped."""
        mock_docker.compose_stop.return_value = True

        result = netbird_service.stop_customer(db_session, sample_customer.id)
        assert result["success"] is True

        db_session.refresh(sample_deployment)
        assert sample_deployment.deployment_status == "stopped"

    @patch("app.services.netbird_service.docker_service")
    def test_start_customer(self, mock_docker, db_session, sample_customer, sample_deployment):
        """Start sets deployment_status to running."""
        mock_docker.compose_start.return_value = True

        result = netbird_service.start_customer(db_session, sample_customer.id)
        assert result["success"] is True

        db_session.refresh(sample_deployment)
        assert sample_deployment.deployment_status == "running"

    @patch("app.services.netbird_service.docker_service")
    def test_restart_customer(self, mock_docker, db_session, sample_customer, sample_deployment):
        """Restart sets deployment_status to running."""
        mock_docker.compose_restart.return_value = True

        result = netbird_service.restart_customer(db_session, sample_customer.id)
        assert result["success"] is True

        db_session.refresh(sample_deployment)
        assert sample_deployment.deployment_status == "running"

    def test_stop_nonexistent_deployment(self, db_session, sample_customer):
        """Stop fails gracefully when no deployment exists."""
        result = netbird_service.stop_customer(db_session, sample_customer.id)
        assert result["success"] is False


class TestHealthCheck:
    """Tests for health check functionality."""

    @patch("app.services.netbird_service.docker_service")
    def test_healthy_deployment(self, mock_docker, db_session, sample_customer, sample_deployment):
        """Health check returns healthy when all containers are running."""
        mock_docker.get_container_status.return_value = [
            {"name": "netbird-kunde1-management", "status": "running", "health": "healthy", "image": "test", "created": ""},
            {"name": "netbird-kunde1-signal", "status": "running", "health": "N/A", "image": "test", "created": ""},
        ]

        result = netbird_service.get_customer_health(db_session, sample_customer.id)
        assert result["healthy"] is True
        assert len(result["containers"]) == 2

    @patch("app.services.netbird_service.docker_service")
    def test_unhealthy_deployment(self, mock_docker, db_session, sample_customer, sample_deployment):
        """Health check returns unhealthy when a container is stopped."""
        mock_docker.get_container_status.return_value = [
            {"name": "netbird-kunde1-management", "status": "running", "health": "healthy", "image": "test", "created": ""},
            {"name": "netbird-kunde1-signal", "status": "exited", "health": "N/A", "image": "test", "created": ""},
        ]

        result = netbird_service.get_customer_health(db_session, sample_customer.id)
        assert result["healthy"] is False

    def test_health_no_deployment(self, db_session, sample_customer):
        """Health check handles missing deployment."""
        result = netbird_service.get_customer_health(db_session, sample_customer.id)
        assert result["healthy"] is False
        assert "No deployment" in result["error"]
