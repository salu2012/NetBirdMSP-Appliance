"""Monitoring API — system overview, customer statuses, host resources."""

import logging
import platform
from typing import Any

import psutil
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import SessionLocal, get_db
from app.dependencies import get_current_user
from app.models import Customer, Deployment, SystemConfig, User
from app.services import docker_service, image_service

logger = logging.getLogger(__name__)
router = APIRouter()


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

    results: list[dict[str, Any]] = []
    for c in customers:
        entry: dict[str, Any] = {
            "id": c.id,
            "name": c.name,
            "subdomain": c.subdomain,
            "status": c.status,
        }
        if c.deployment:
            containers = docker_service.get_container_status(c.deployment.container_prefix)
            entry["deployment_status"] = c.deployment.deployment_status
            entry["containers"] = containers
            entry["relay_udp_port"] = c.deployment.relay_udp_port
            entry["dashboard_port"] = c.deployment.dashboard_port
            entry["setup_url"] = c.deployment.setup_url
        else:
            entry["deployment_status"] = None
            entry["containers"] = []
        results.append(entry)

    return results


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


@router.post("/customers/update-all")
async def update_all_customers(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Recreate containers for all customers that have outdated images.

    Only customers where at least one container runs an outdated image are updated.
    Images must already be pulled. Data is preserved (bind mounts).
    """
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only.")

    config = db.query(SystemConfig).filter(SystemConfig.id == 1).first()
    if not config:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="System not configured.")

    # Collect customers that need updating
    deployments = db.query(Deployment).all()
    to_update = []
    for dep in deployments:
        cs = image_service.get_customer_container_image_status(dep.container_prefix, config)
        if cs["needs_update"]:
            customer = dep.customer
            instance_dir = str(dep.container_prefix).replace(
                "netbird-", "", 1
            )  # subdomain
            to_update.append({
                "instance_dir": f"{config.data_dir}/{customer.subdomain}",
                "project_name": dep.container_prefix,
                "customer_name": customer.name,
            })

    if not to_update:
        return {"message": "All customers are already up to date.", "updated": 0}

    async def _update_all_bg() -> None:
        for entry in to_update:
            try:
                await image_service.update_customer_containers(
                    entry["instance_dir"], entry["project_name"]
                )
                logger.info("Updated containers for %s", entry["project_name"])
            except Exception:
                logger.exception("Failed to update %s", entry["project_name"])

    background_tasks.add_task(_update_all_bg)
    names = [e["customer_name"] for e in to_update]
    return {
        "message": f"Updating {len(to_update)} customer(s) in background.",
        "customers": names,
    }
