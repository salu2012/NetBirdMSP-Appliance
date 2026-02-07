"""Deployment management API — start, stop, restart, logs, health for customers."""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import Customer, Deployment, User
from app.services import docker_service, netbird_service

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/{customer_id}/deploy")
async def manual_deploy(
    customer_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Manually trigger deployment for a customer.

    Use this to re-deploy a customer whose previous deployment failed.

    Args:
        customer_id: Customer ID.

    Returns:
        Deployment result dict.
    """
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found.")

    # Remove existing deployment if present
    existing = db.query(Deployment).filter(Deployment.customer_id == customer_id).first()
    if existing:
        await netbird_service.undeploy_customer(db, customer_id)

    result = await netbird_service.deploy_customer(db, customer_id)
    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.get("error", "Deployment failed."),
        )
    return result


@router.post("/{customer_id}/start")
async def start_customer(
    customer_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Start containers for a customer.

    Args:
        customer_id: Customer ID.

    Returns:
        Result dict.
    """
    _require_customer(db, customer_id)
    result = netbird_service.start_customer(db, customer_id)
    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.get("error", "Failed to start containers."),
        )
    return result


@router.post("/{customer_id}/stop")
async def stop_customer(
    customer_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Stop containers for a customer.

    Args:
        customer_id: Customer ID.

    Returns:
        Result dict.
    """
    _require_customer(db, customer_id)
    result = netbird_service.stop_customer(db, customer_id)
    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.get("error", "Failed to stop containers."),
        )
    return result


@router.post("/{customer_id}/restart")
async def restart_customer(
    customer_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Restart containers for a customer.

    Args:
        customer_id: Customer ID.

    Returns:
        Result dict.
    """
    _require_customer(db, customer_id)
    result = netbird_service.restart_customer(db, customer_id)
    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.get("error", "Failed to restart containers."),
        )
    return result


@router.get("/{customer_id}/logs")
async def get_customer_logs(
    customer_id: int,
    tail: int = 200,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get container logs for a customer.

    Args:
        customer_id: Customer ID.
        tail: Number of log lines per container.

    Returns:
        Dict mapping container name to log text.
    """
    _require_customer(db, customer_id)
    deployment = db.query(Deployment).filter(Deployment.customer_id == customer_id).first()
    if not deployment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No deployment found for this customer.",
        )

    logs = docker_service.get_all_container_logs(deployment.container_prefix, tail=tail)
    return {"logs": logs}


@router.get("/{customer_id}/health")
async def check_customer_health(
    customer_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Run a health check on a customer's deployment.

    Args:
        customer_id: Customer ID.

    Returns:
        Health check results.
    """
    _require_customer(db, customer_id)
    return netbird_service.get_customer_health(db, customer_id)


def _require_customer(db: Session, customer_id: int) -> Customer:
    """Helper to fetch a customer or raise 404.

    Args:
        db: Database session.
        customer_id: Customer ID.

    Returns:
        Customer ORM object.

    Raises:
        HTTPException: If customer not found.
    """
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found.")
    return customer
