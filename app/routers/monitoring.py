"""Monitoring API — system overview, customer statuses, host resources."""

import asyncio
import logging
import platform
import time
from typing import Any

import psutil
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import SessionLocal, get_db
from app.dependencies import get_current_user
from app.models import Customer, Deployment, SystemConfig, User
from app.services import docker_service, image_service, netbird_client_update_service
from app.utils.security import decrypt_value
from app.utils.validators import NetbirdClientAutoUpdatePayload

logger = logging.getLogger(__name__)
router = APIRouter()

# Short-lived cache for the local update-status badges. This endpoint is
# triggered on every customer-table render (i.e. every search keystroke), but
# the underlying data (which images are outdated) only changes after an image
# pull + container recreate, so a few seconds of staleness is harmless.
_update_status_cache: dict[str, Any] = {"data": None, "expires": 0.0}
_UPDATE_STATUS_TTL_SECONDS = 20


@router.get("/status")
async def system_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """System overview with aggregated customer statistics.

    Returns:
        Counts by status and total customers.
    """
    total = db.query(Customer).count()
    active = db.query(Customer).filter(Customer.status == "active").count()
    inactive = db.query(Customer).filter(Customer.status == "inactive").count()
    deploying = db.query(Customer).filter(Customer.status == "deploying").count()
    error = db.query(Customer).filter(Customer.status == "error").count()

    return {
        "total_customers": total,
        "active": active,
        "inactive": inactive,
        "deploying": deploying,
        "error": error,
    }


@router.get("/customers")
async def all_customers_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """Get deployment status for every customer.

    Returns:
        List of dicts with customer info and container statuses.
    """
    customers = (
        db.query(Customer)
        .order_by(Customer.id)
        .all()
    )

    async def _build_entry(c: Customer) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "id": c.id,
            "name": c.name,
            "subdomain": c.subdomain,
            "status": c.status,
        }
        if c.deployment:
            containers = await docker_service.get_container_status_async(c.deployment.container_prefix)
            entry["deployment_status"] = c.deployment.deployment_status
            entry["containers"] = containers
            entry["relay_udp_port"] = c.deployment.relay_udp_port
            entry["dashboard_port"] = c.deployment.dashboard_port
            entry["setup_url"] = c.deployment.setup_url
        else:
            entry["deployment_status"] = None
            entry["containers"] = []
        return entry

    # Fetch container status for all customers concurrently instead of one
    # blocking Docker SDK call at a time.
    return await asyncio.gather(*[_build_entry(c) for c in customers])


@router.get("/resources")
async def host_resources(
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Return host system resource usage.

    Returns:
        CPU, memory, disk, and network information.
    """
    cpu_percent = psutil.cpu_percent(interval=1)
    cpu_count = psutil.cpu_count()
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    return {
        "hostname": platform.node(),
        "os": f"{platform.system()} {platform.release()}",
        "cpu": {
            "percent": cpu_percent,
            "count": cpu_count,
        },
        "memory": {
            "total_gb": round(mem.total / (1024 ** 3), 1),
            "used_gb": round(mem.used / (1024 ** 3), 1),
            "available_gb": round(mem.available / (1024 ** 3), 1),
            "percent": mem.percent,
        },
        "disk": {
            "total_gb": round(disk.total / (1024 ** 3), 1),
            "used_gb": round(disk.used / (1024 ** 3), 1),
            "free_gb": round(disk.free / (1024 ** 3), 1),
            "percent": disk.percent,
        },
    }


@router.get("/images/check")
async def check_image_updates(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Check all configured NetBird images for available updates on Docker Hub.

    Compares local image digests against Docker Hub — no image is pulled.

    Returns:
        images: dict mapping image name to update status
        any_update_available: bool
        customer_status: list of per-customer container image status
    """
    config = db.query(SystemConfig).filter(SystemConfig.id == 1).first()
    if not config:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="System not configured.")

    hub_status = await image_service.check_all_images(config)

    # Per-customer local check (no network)
    deployments = db.query(Deployment).all()
    customer_status = []
    for dep in deployments:
        customer = dep.customer
        cs = image_service.get_customer_container_image_status(dep.container_prefix, config)
        customer_status.append({
            "customer_id": customer.id,
            "customer_name": customer.name,
            "subdomain": customer.subdomain,
            "container_prefix": dep.container_prefix,
            "needs_update": cs["needs_update"],
            "unknown": cs.get("unknown", False),
            "services": cs["services"],
        })

    return {**hub_status, "customer_status": customer_status}


@router.post("/images/pull")
async def pull_all_netbird_images(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Pull all configured NetBird images from Docker Hub.

    Runs in the background — returns immediately. After pulling, re-check
    customer status via GET /images/check to see which customers need updating.
    """
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only.")

    config = db.query(SystemConfig).filter(SystemConfig.id == 1).first()
    if not config:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="System not configured.")

    # Snapshot image list before background task starts
    images = [
        config.netbird_management_image,
        config.netbird_signal_image,
        config.netbird_relay_image,
        config.netbird_dashboard_image,
    ]

    async def _pull_bg() -> None:
        bg_db = SessionLocal()
        try:
            cfg = bg_db.query(SystemConfig).filter(SystemConfig.id == 1).first()
            if cfg:
                await image_service.pull_all_images(cfg)
        except Exception:
            logger.exception("Background image pull failed")
        finally:
            bg_db.close()

    background_tasks.add_task(_pull_bg)
    return {"message": "Image pull started in background.", "images": images}


@router.get("/customers/local-update-status")
async def customers_local_update_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """Fast local-only check for outdated customer containers.

    Compares running container image IDs against locally stored images.
    No network call — safe to call on every dashboard load.

    Results are cached for a few seconds since this is triggered on every
    customer-table render (including every search keystroke) but the
    underlying data rarely changes.
    """
    now = time.monotonic()
    if _update_status_cache["data"] is not None and now < _update_status_cache["expires"]:
        return _update_status_cache["data"]

    config = db.query(SystemConfig).filter(SystemConfig.id == 1).first()
    if not config:
        return []
    deployments = db.query(Deployment).all()

    async def _check(dep: Deployment) -> dict[str, Any]:
        cs = await image_service.get_customer_container_image_status_async(dep.container_prefix, config)
        return {"customer_id": dep.customer_id, "needs_update": cs["needs_update"], "unknown": cs.get("unknown", False)}

    results = await asyncio.gather(*[_check(dep) for dep in deployments])
    results = list(results)
    _update_status_cache["data"] = results
    _update_status_cache["expires"] = now + _UPDATE_STATUS_TTL_SECONDS
    return results


@router.post("/netbird-updates/apply-all")
async def apply_netbird_client_updates_to_all(
    payload: NetbirdClientAutoUpdatePayload,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Push a NetBird client automatic-updates version/mode to every customer.

    Skips (and reports) customers without a registered API token — they need
    a token pasted in via the per-customer endpoint first (older deployments
    predating automatic token capture).
    """
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only.")

    deployments = db.query(Deployment).all()
    results = []
    for dep in deployments:
        customer = dep.customer
        if not dep.netbird_api_token_encrypted:
            results.append({
                "customer_id": customer.id, "customer_name": customer.name,
                "success": False, "error": "No API token registered.",
            })
            continue
        token = decrypt_value(dep.netbird_api_token_encrypted)
        res = await netbird_client_update_service.push_auto_update_settings(
            dep.container_prefix, token, payload.version, payload.always
        )
        results.append({
            "customer_id": customer.id, "customer_name": customer.name,
            "success": res["ok"], "error": res.get("error"),
        })

    success_count = sum(1 for r in results if r["success"])
    return {
        "message": f"Applied to {success_count} of {len(results)} customer(s).",
        "updated": success_count,
        "results": results,
    }


@router.post("/customers/update-all")
async def update_all_customers(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Recreate containers for all customers with outdated images — sequential, synchronous.

    Updates customers one at a time so a failing customer does not block others.
    Images must already be pulled. Data is preserved (bind mounts).
    Returns detailed per-customer results.
    """
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only.")

    config = db.query(SystemConfig).filter(SystemConfig.id == 1).first()
    if not config:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="System not configured.")

    deployments = db.query(Deployment).all()
    to_update = []
    for dep in deployments:
        cs = image_service.get_customer_container_image_status(dep.container_prefix, config)
        if cs["needs_update"]:
            customer = dep.customer
            to_update.append({
                "instance_dir": f"{config.data_dir}/{customer.subdomain}",
                "project_name": dep.container_prefix,
                "customer_name": customer.name,
                "customer_id": customer.id,
            })

    if not to_update:
        return {"message": "All customers are already up to date.", "updated": 0, "results": []}

    # Update customers sequentially — one at a time. A failure for one
    # customer (e.g. a hung docker compose call) must not abort the rest of
    # the batch, otherwise later customers silently never get updated.
    update_results = []
    for entry in to_update:
        try:
            res = await image_service.update_customer_containers(
                entry["instance_dir"], entry["project_name"]
            )
            ok = res["success"]
            error = res.get("error")
        except Exception as exc:
            logger.exception("Unexpected error updating %s", entry["project_name"])
            ok = False
            error = str(exc)
        logger.info("Updated %s: %s", entry["project_name"], "OK" if ok else error)
        update_results.append({
            "customer_name": entry["customer_name"],
            "customer_id": entry["customer_id"],
            "success": ok,
            "error": error,
        })

    success_count = sum(1 for r in update_results if r["success"])
    return {
        "message": f"Updated {success_count} of {len(update_results)} customer(s).",
        "updated": success_count,
        "results": update_results,
    }
