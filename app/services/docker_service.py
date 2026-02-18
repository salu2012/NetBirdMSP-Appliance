"""Docker container management via the Python Docker SDK.

Responsible for creating, starting, stopping, restarting, and removing
per-customer Docker Compose stacks. Also provides log retrieval and
container health/status information.
"""

import asyncio
import logging
import os
import subprocess
import time
from typing import Any, Optional

import docker
from docker.errors import DockerException, NotFound

logger = logging.getLogger(__name__)


async def _run_cmd(cmd: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    """Run a subprocess command in a thread pool to avoid blocking the event loop."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(  # type: ignore[arg-type]
        None,
        lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=timeout),
    )


def _get_client() -> docker.DockerClient:
    """Return a Docker client connected via the Unix socket.

    Returns:
        docker.DockerClient instance.
    """
    return docker.from_env()


async def compose_up(
    instance_dir: str,
    project_name: str,
    services: Optional[list[str]] = None,
    timeout: int = 300,
) -> bool:
    """Run ``docker compose up -d`` for a customer instance.

    Args:
        instance_dir: Absolute path to the customer's instance directory.
        project_name: Docker Compose project name (e.g. ``netbird-kunde5``).
        services: Optional list of service names to start.
                  If None, all services are started.
        timeout: Subprocess timeout in seconds (default 300).

    Returns:
        True on success.

    Raises:
        RuntimeError: If ``docker compose up`` fails.
    """
    compose_file = os.path.join(instance_dir, "docker-compose.yml")
    if not os.path.isfile(compose_file):
        raise FileNotFoundError(f"docker-compose.yml not found at {compose_file}")

    cmd = [
        "docker", "compose",
        "-f", compose_file,
        "-p", project_name,
        "up", "-d",
    ]
    if not services:
        cmd.append("--remove-orphans")
    if services:
        cmd.extend(services)

    logger.info("Running: %s", " ".join(cmd))
    result = await _run_cmd(cmd, timeout=timeout)

    if result.returncode != 0:
        logger.error("docker compose up failed: %s", result.stderr)
        raise RuntimeError(f"docker compose up failed: {result.stderr}")

    svc_info = f" (services: {', '.join(services)})" if services else ""
    logger.info("docker compose up succeeded for %s%s", project_name, svc_info)
    return True


async def compose_down(instance_dir: str, project_name: str, remove_volumes: bool = False) -> bool:
    """Run ``docker compose down`` for a customer instance.

    Args:
        instance_dir: Absolute path to the customer's instance directory.
        project_name: Docker Compose project name.
        remove_volumes: Whether to also remove volumes.

    Returns:
        True on success.
    """
    compose_file = os.path.join(instance_dir, "docker-compose.yml")
    cmd = [
        "docker", "compose",
        "-f", compose_file,
        "-p", project_name,
        "down",
    ]
    if remove_volumes:
        cmd.append("-v")

    logger.info("Running: %s", " ".join(cmd))
    result = await _run_cmd(cmd)

    if result.returncode != 0:
        logger.warning("docker compose down returned non-zero: %s", result.stderr)
    return True


async def compose_stop(instance_dir: str, project_name: str) -> bool:
    """Run ``docker compose stop`` for a customer instance.

    Args:
        instance_dir: Absolute path to the customer's instance directory.
        project_name: Docker Compose project name.

    Returns:
        True on success.
    """
    compose_file = os.path.join(instance_dir, "docker-compose.yml")
    cmd = [
        "docker", "compose",
        "-f", compose_file,
        "-p", project_name,
        "stop",
    ]
    logger.info("Running: %s", " ".join(cmd))
    result = await _run_cmd(cmd)
    return result.returncode == 0


async def compose_start(instance_dir: str, project_name: str) -> bool:
    """Run ``docker compose start`` for a customer instance.

    Args:
        instance_dir: Absolute path to the customer's instance directory.
        project_name: Docker Compose project name.

    Returns:
        True on success.
    """
    compose_file = os.path.join(instance_dir, "docker-compose.yml")
    cmd = [
        "docker", "compose",
        "-f", compose_file,
        "-p", project_name,
        "start",
    ]
    logger.info("Running: %s", " ".join(cmd))
    result = await _run_cmd(cmd)
    return result.returncode == 0


async def compose_restart(instance_dir: str, project_name: str) -> bool:
    """Run ``docker compose restart`` for a customer instance.

    Args:
        instance_dir: Absolute path to the customer's instance directory.
        project_name: Docker Compose project name.

    Returns:
        True on success.
    """
    compose_file = os.path.join(instance_dir, "docker-compose.yml")
    cmd = [
        "docker", "compose",
        "-f", compose_file,
        "-p", project_name,
        "restart",
    ]
    logger.info("Running: %s", " ".join(cmd))
    result = await _run_cmd(cmd)
    return result.returncode == 0


def get_container_status(container_prefix: str) -> list[dict[str, Any]]:
    """Get the status of all containers matching a prefix.

    Args:
        container_prefix: Container name prefix (e.g. ``netbird-kunde5``).

    Returns:
        List of dicts with container name, status, and health info.
    """
    client = _get_client()
    results: list[dict[str, Any]] = []
    try:
        containers = client.containers.list(all=True, filters={"name": container_prefix})
        for c in containers:
            # Derive health from container status.
            # Docker HEALTHCHECK is unreliable (e.g. netbirdio/management
            # defines a wget-based check but wget is not installed).
            if c.status == "running":
                health = "healthy"
            else:
                health = "unhealthy"
            results.append({
                "name": c.name,
                "status": c.status,
                "health": health,
                "image": str(c.image.tags[0]) if c.image.tags else str(c.image.id[:12]),
                "created": c.attrs.get("Created", ""),
            })
    except DockerException as exc:
        logger.error("Failed to get container status: %s", exc)
    return results


def get_container_logs(container_name: str, tail: int = 200) -> str:
    """Retrieve recent logs from a container.

    Args:
        container_name: Full container name.
        tail: Number of log lines to retrieve.

    Returns:
        Log text.
    """
    client = _get_client()
    try:
        container = client.containers.get(container_name)
        return container.logs(tail=tail, timestamps=True).decode("utf-8", errors="replace")
    except NotFound:
        return f"Container {container_name} not found."
    except DockerException as exc:
        return f"Error retrieving logs: {exc}"


def get_all_container_logs(container_prefix: str, tail: int = 100) -> dict[str, str]:
    """Get logs for all containers matching a prefix.

    Args:
        container_prefix: Container name prefix.
        tail: Lines per container.

    Returns:
        Dict mapping container name to log text.
    """
    client = _get_client()
    logs: dict[str, str] = {}
    try:
        containers = client.containers.list(all=True, filters={"name": container_prefix})
        for c in containers:
            try:
                logs[c.name] = c.logs(tail=tail, timestamps=True).decode(
                    "utf-8", errors="replace"
                )
            except DockerException:
                logs[c.name] = "Error retrieving logs."
    except DockerException as exc:
        logger.error("Failed to list containers: %s", exc)
    return logs


def wait_for_healthy(container_prefix: str, timeout: int = 60) -> bool:
    """Wait until all containers with the given prefix are running.

    Args:
        container_prefix: Container name prefix.
        timeout: Maximum seconds to wait.

    Returns:
        True if all containers started within timeout.
    """
    client = _get_client()
    deadline = time.time() + timeout

    while time.time() < deadline:
        try:
            containers = client.containers.list(
                all=True, filters={"name": container_prefix}
            )
            if not containers:
                time.sleep(2)
                continue

            all_running = all(c.status == "running" for c in containers)
            if all_running:
                logger.info("All containers for %s are running.", container_prefix)
                return True
        except DockerException as exc:
            logger.warning("Health check error: %s", exc)

        time.sleep(3)

    logger.warning("Timeout waiting for %s containers to start.", container_prefix)
    return False


def get_docker_stats(container_prefix: str) -> list[dict[str, Any]]:
    """Retrieve resource usage stats for containers matching a prefix.

    Args:
        container_prefix: Container name prefix.

    Returns:
        List of dicts with CPU, memory, and network stats.
    """
    client = _get_client()
    stats_list: list[dict[str, Any]] = []
    try:
        containers = client.containers.list(filters={"name": container_prefix})
        for c in containers:
            try:
                raw = c.stats(stream=False)
                cpu_delta = (
                    raw.get("cpu_stats", {}).get("cpu_usage", {}).get("total_usage", 0)
                    - raw.get("precpu_stats", {}).get("cpu_usage", {}).get("total_usage", 0)
                )
                system_delta = (
                    raw.get("cpu_stats", {}).get("system_cpu_usage", 0)
                    - raw.get("precpu_stats", {}).get("system_cpu_usage", 0)
                )
                num_cpus = len(
                    raw.get("cpu_stats", {}).get("cpu_usage", {}).get("percpu_usage", [1])
                )
                cpu_pct = 0.0
                if system_delta > 0:
                    cpu_pct = (cpu_delta / system_delta) * num_cpus * 100

                mem_usage = raw.get("memory_stats", {}).get("usage", 0)
                mem_limit = raw.get("memory_stats", {}).get("limit", 1)

                stats_list.append({
                    "name": c.name,
                    "cpu_percent": round(cpu_pct, 2),
                    "memory_usage_mb": round(mem_usage / 1024 / 1024, 1),
                    "memory_limit_mb": round(mem_limit / 1024 / 1024, 1),
                    "memory_percent": round((mem_usage / mem_limit) * 100, 1) if mem_limit else 0,
                })
            except DockerException:
                stats_list.append({"name": c.name, "error": "Failed to get stats"})
    except DockerException as exc:
        logger.error("Failed to get docker stats: %s", exc)
    return stats_list


def remove_instance_containers(container_prefix: str) -> bool:
    """Force-remove all containers matching a prefix.

    Args:
        container_prefix: Container name prefix.

    Returns:
        True if removal succeeded.
    """
    client = _get_client()
    try:
        containers = client.containers.list(all=True, filters={"name": container_prefix})
        for c in containers:
            logger.info("Removing container %s", c.name)
            c.remove(force=True)
        return True
    except DockerException as exc:
        logger.error("Failed to remove containers: %s", exc)
        return False
