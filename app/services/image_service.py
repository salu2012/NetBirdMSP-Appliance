"""NetBird Docker image update service.

Compares locally pulled images against Docker Hub to detect available updates.
Provides pull and per-customer container recreation functions without data loss.
"""

import asyncio
import json
import logging
import os
import subprocess
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Services that make up a customer's NetBird deployment
NETBIRD_SERVICES = ["management", "signal", "relay", "dashboard"]


async def _run_cmd(cmd: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    """Run a subprocess command without blocking the event loop."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=timeout),
    )


def _parse_image_name(image: str) -> tuple[str, str]:
    """Split 'repo/name:tag' into ('repo/name', 'tag'). Defaults tag to 'latest'."""
    if ":" in image:
        name, tag = image.rsplit(":", 1)
    else:
        name, tag = image, "latest"
    return name, tag


async def get_hub_digest(image: str) -> str | None:
    """Fetch the manifest-list digest from the Docker Registry v2 API.

    Uses anonymous auth against registry-1.docker.io — does NOT pull the image.
    Returns the Docker-Content-Digest header value (sha256:...) which is identical
    to the digest stored in local RepoDigests after a pull, enabling correct comparison.
    """
    name, tag = _parse_image_name(image)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # Step 1: obtain anonymous pull token
            token_resp = await client.get(
                "https://auth.docker.io/token",
                params={"service": "registry.docker.io", "scope": f"repository:{name}:pull"},
            )
            if token_resp.status_code != 200:
                logger.warning("Failed to get registry token for %s", image)
                return None
            token = token_resp.json().get("token")

            # Step 2: fetch manifest — prefer manifest list (multi-arch) so the digest
            # matches what `docker pull` stores in RepoDigests.
            manifest_resp = await client.get(
                f"https://registry-1.docker.io/v2/{name}/manifests/{tag}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": (
                        "application/vnd.docker.distribution.manifest.list.v2+json, "
                        "application/vnd.oci.image.index.v1+json, "
                        "application/vnd.docker.distribution.manifest.v2+json"
                    ),
                },
            )
            if manifest_resp.status_code != 200:
                logger.warning("Registry API returned %d for %s", manifest_resp.status_code, image)
                return None

            # The Docker-Content-Digest header is the canonical digest
            digest = manifest_resp.headers.get("docker-content-digest")
            if digest:
                return digest
            return None
    except Exception as exc:
        logger.warning("Failed to fetch registry digest for %s: %s", image, exc)
        return None


def get_local_digest(image: str) -> str | None:
    """Get the RepoDigest for a locally pulled image.

    Returns the digest (sha256:...) or None if image not found locally.
    """
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", image, "--format", "{{json .RepoDigests}}"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return None
        digests = json.loads(result.stdout.strip())
        if not digests:
            return None
        # RepoDigests look like "netbirdio/management@sha256:abc..."
        for d in digests:
            if "@" in d:
                return d.split("@", 1)[1]
        return None
    except Exception as exc:
        logger.warning("Failed to inspect local image %s: %s", image, exc)
        return None


def get_container_image_id(container_name: str) -> str | None:
    """Get the full image ID (sha256:...) of a running or stopped container."""
    try:
        result = subprocess.run(
            ["docker", "inspect", container_name, "--format", "{{.Image}}"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None
    except Exception:
        return None


def get_local_image_id(image: str) -> str | None:
    """Get the full image ID (sha256:...) of a locally stored image."""
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", image, "--format", "{{.Id}}"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None
    except Exception:
        return None


async def check_image_status(image: str) -> dict[str, Any]:
    """Check whether a configured image has an update available on Docker Hub.

    Returns a dict with:
        image: the image name:tag
        local_digest: digest of locally cached image (or None)
        hub_digest: latest digest from Docker Hub (or None)
        update_available: True if hub_digest differs from local_digest
    """
    hub_digest, local_digest = await asyncio.gather(
        get_hub_digest(image),
        asyncio.get_event_loop().run_in_executor(None, get_local_digest, image),
    )

    if hub_digest and local_digest:
        update_available = hub_digest != local_digest
    elif hub_digest and not local_digest:
        # Image not pulled locally yet — needs pull
        update_available = True
    else:
        update_available = False

    return {
        "image": image,
        "local_digest": local_digest,
        "hub_digest": hub_digest,
        "update_available": update_available,
    }


async def check_all_images(config) -> dict[str, Any]:
    """Check all 4 configured NetBird images for available updates.

    Returns a dict with:
        images: dict mapping image name -> status dict
        any_update_available: bool
    """
    images = [
        config.netbird_management_image,
        config.netbird_signal_image,
        config.netbird_relay_image,
        config.netbird_dashboard_image,
    ]
    results = await asyncio.gather(*[check_image_status(img) for img in images])
    by_image = {r["image"]: r for r in results}
    any_update = any(r["update_available"] for r in results)
    return {"images": by_image, "any_update_available": any_update}


async def pull_image(image: str) -> dict[str, Any]:
    """Pull a Docker image. Returns success/error dict."""
    logger.info("Pulling image: %s", image)
    result = await _run_cmd(["docker", "pull", image], timeout=600)
    if result.returncode != 0:
        logger.error("Failed to pull %s: %s", image, result.stderr)
        return {"image": image, "success": False, "error": result.stderr[:500]}
    return {"image": image, "success": True}


async def pull_all_images(config) -> dict[str, Any]:
    """Pull all 4 configured NetBird images. Returns results per image."""
    images = [
        config.netbird_management_image,
        config.netbird_signal_image,
        config.netbird_relay_image,
        config.netbird_dashboard_image,
    ]
    results = await asyncio.gather(*[pull_image(img) for img in images])
    return {
        "results": {r["image"]: r for r in results},
        "all_success": all(r["success"] for r in results),
    }


def get_customer_container_image_status(container_prefix: str, config) -> dict[str, Any]:
    """Check which service containers are running outdated local images.

    Compares each running container's image ID against the locally stored image ID
    for the configured image tag. This is a local check — no network call.

    Returns:
        services: dict mapping service name to status info
        needs_update: True if any service has a different image ID than locally stored
    """
    service_images = {
        "management": config.netbird_management_image,
        "signal": config.netbird_signal_image,
        "relay": config.netbird_relay_image,
        "dashboard": config.netbird_dashboard_image,
    }
    services: dict[str, Any] = {}
    for svc, image in service_images.items():
        container_name = f"{container_prefix}-{svc}"
        container_id = get_container_image_id(container_name)
        local_id = get_local_image_id(image)
        if container_id and local_id:
            up_to_date = container_id == local_id
        else:
            up_to_date = None  # container not running or image not pulled
        services[svc] = {
            "container": container_name,
            "image": image,
            "up_to_date": up_to_date,
        }
    needs_update = any(s["up_to_date"] is False for s in services.values())
    return {"services": services, "needs_update": needs_update}


async def update_customer_containers(instance_dir: str, project_name: str) -> dict[str, Any]:
    """Recreate customer containers to pick up newly pulled images.

    Runs `docker compose up -d` in the customer's instance directory.
    Images must already be pulled. Bind-mounted data is preserved — no data loss.
    """
    compose_file = os.path.join(instance_dir, "docker-compose.yml")
    if not os.path.isfile(compose_file):
        return {"success": False, "error": f"docker-compose.yml not found at {compose_file}"}
    cmd = [
        "docker", "compose",
        "-f", compose_file,
        "-p", project_name,
        "up", "-d", "--remove-orphans",
    ]
    logger.info("Updating containers for %s", project_name)
    result = await _run_cmd(cmd, timeout=300)
    if result.returncode != 0:
        return {"success": False, "error": result.stderr[:1000]}
    return {"success": True}
