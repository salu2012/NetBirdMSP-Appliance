"""Unit tests for the Docker service and port manager."""

import os
import pytest
from unittest.mock import patch, MagicMock

os.environ["SECRET_KEY"] = "test-secret-key-for-unit-tests"
os.environ["DATABASE_PATH"] = ":memory:"

from app.services import docker_service, port_manager
from app.models import Deployment


class TestPortManager:
    """Tests for UDP port allocation."""

    def test_allocate_first_port(self, db_session):
        """First allocation returns base port."""
        port = port_manager.allocate_port(db_session, base_port=3478)
        assert port == 3478

    def test_allocate_skips_used_ports(self, db_session, sample_deployment):
        """Allocation skips ports already in the database."""
        # sample_deployment uses port 3478
        port = port_manager.allocate_port(db_session, base_port=3478)
        assert port == 3479

    def test_allocate_raises_when_full(self, db_session):
        """Allocation raises RuntimeError when all ports are used."""
        # Fill all ports
        for i in range(100):
            db_session.add(Deployment(
                customer_id=1000 + i,
                container_prefix=f"test-{i}",
                relay_udp_port=3478 + i,
                relay_secret="secret",
                deployment_status="running",
            ))
        db_session.commit()

        with pytest.raises(RuntimeError, match="No available relay ports"):
            port_manager.allocate_port(db_session, base_port=3478, max_ports=100)

    def test_get_allocated_ports(self, db_session, sample_deployment):
        """Returns set of allocated ports."""
        ports = port_manager.get_allocated_ports(db_session)
        assert 3478 in ports

    def test_validate_port_available(self, db_session):
        """Available port returns True."""
        assert port_manager.validate_port_available(db_session, 3500) is True

    def test_validate_port_taken(self, db_session, sample_deployment):
        """Allocated port returns False."""
        assert port_manager.validate_port_available(db_session, 3478) is False


class TestDockerService:
    """Tests for Docker container management."""

    @patch("app.services.docker_service.subprocess.run")
    def test_compose_up_success(self, mock_run, tmp_path):
        """compose_up succeeds when docker compose returns 0."""
        compose_file = tmp_path / "docker-compose.yml"
        compose_file.write_text("version: '3.8'\nservices: {}")
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        result = docker_service.compose_up(str(tmp_path), "test-project")
        assert result is True
        mock_run.assert_called_once()

    @patch("app.services.docker_service.subprocess.run")
    def test_compose_up_failure(self, mock_run, tmp_path):
        """compose_up raises RuntimeError on failure."""
        compose_file = tmp_path / "docker-compose.yml"
        compose_file.write_text("version: '3.8'\nservices: {}")
        mock_run.return_value = MagicMock(returncode=1, stderr="Some error")

        with pytest.raises(RuntimeError, match="docker compose up failed"):
            docker_service.compose_up(str(tmp_path), "test-project")

    def test_compose_up_missing_file(self, tmp_path):
        """compose_up raises FileNotFoundError when compose file is missing."""
        with pytest.raises(FileNotFoundError):
            docker_service.compose_up(str(tmp_path), "test-project")

    @patch("app.services.docker_service.subprocess.run")
    def test_compose_stop(self, mock_run, tmp_path):
        """compose_stop returns True on success."""
        compose_file = tmp_path / "docker-compose.yml"
        compose_file.write_text("")
        mock_run.return_value = MagicMock(returncode=0)

        result = docker_service.compose_stop(str(tmp_path), "test-project")
        assert result is True

    @patch("app.services.docker_service._get_client")
    def test_get_container_status(self, mock_get_client):
        """get_container_status returns formatted container info."""
        mock_container = MagicMock()
        mock_container.name = "netbird-kunde1-management"
        mock_container.status = "running"
        mock_container.attrs = {"State": {"Health": {"Status": "healthy"}}, "Created": "2024-01-01"}
        mock_container.image.tags = ["netbirdio/management:latest"]

        mock_client = MagicMock()
        mock_client.containers.list.return_value = [mock_container]
        mock_get_client.return_value = mock_client

        result = docker_service.get_container_status("netbird-kunde1")
        assert len(result) == 1
        assert result[0]["name"] == "netbird-kunde1-management"
        assert result[0]["status"] == "running"
        assert result[0]["health"] == "healthy"

    @patch("app.services.docker_service._get_client")
    def test_get_container_logs(self, mock_get_client):
        """get_container_logs returns log text."""
        mock_container = MagicMock()
        mock_container.logs.return_value = b"2024-01-01 12:00:00 Started\n"

        mock_client = MagicMock()
        mock_client.containers.get.return_value = mock_container
        mock_get_client.return_value = mock_client

        result = docker_service.get_container_logs("netbird-kunde1-management")
        assert "Started" in result

    @patch("app.services.docker_service._get_client")
    def test_get_container_logs_not_found(self, mock_get_client):
        """get_container_logs handles missing container."""
        from docker.errors import NotFound
        mock_client = MagicMock()
        mock_client.containers.get.side_effect = NotFound("not found")
        mock_get_client.return_value = mock_client

        result = docker_service.get_container_logs("nonexistent")
        assert "not found" in result

    @patch("app.services.docker_service._get_client")
    def test_remove_instance_containers(self, mock_get_client):
        """remove_instance_containers force-removes all matching containers."""
        mock_c1 = MagicMock()
        mock_c1.name = "netbird-kunde1-management"
        mock_c2 = MagicMock()
        mock_c2.name = "netbird-kunde1-signal"

        mock_client = MagicMock()
        mock_client.containers.list.return_value = [mock_c1, mock_c2]
        mock_get_client.return_value = mock_client

        result = docker_service.remove_instance_containers("netbird-kunde1")
        assert result is True
        mock_c1.remove.assert_called_once_with(force=True)
        mock_c2.remove.assert_called_once_with(force=True)
