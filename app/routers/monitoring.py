"""Monitoring API — system overview, customer statuses, host resources."""

import logging
import platform
from typing import Any

import psutil
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import Customer, Deployment, User
from app.services import docker_service

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
