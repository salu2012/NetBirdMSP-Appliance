"""Customer CRUD API endpoints with automatic deployment on create."""

import asyncio
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import SessionLocal, get_db
from app.dependencies import get_current_user
from app.models import Customer, Deployment, DeploymentLog, User
from app.services import netbird_service
from app.utils.validators import CustomerCreate, CustomerUpdate

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_customer(
    payload: CustomerCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new customer and trigger auto-deployment.

    Validates that the subdomain is unique, creates the customer record,
    and launches deployment in the background.

    Args:
        payload: Customer creation data.
        background_tasks: FastAPI background task runner.

    Returns:
        Created customer dict with deployment status.
    """
    # Check subdomain uniqueness
    existing = db.query(Customer).filter(Customer.subdomain == payload.subdomain).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Subdomain '{payload.subdomain}' is already in use.",
        )

    customer = Customer(
        name=payload.name,
        company=payload.company,
        subdomain=payload.subdomain,
        email=payload.email,
        max_devices=payload.max_devices,
        notes=payload.notes,
        status="deploying",
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)

    logger.info("Customer %d (%s) created by %s.", customer.id, customer.subdomain, current_user.username)

    # Deploy in background so the HTTP response returns immediately.
    # We create a dedicated DB session for the background task because
    # the request session will be closed once the response is sent.
    async def _deploy_in_background(customer_id: int) -> None:
        bg_db = SessionLocal()
        try:
            await netbird_service.deploy_customer(bg_db, customer_id)
        except Exception:
            logger.exception("Background deployment failed for customer %d", customer_id)
        finally:
            bg_db.close()

    background_tasks.add_task(_deploy_in_background, customer.id)

    response = customer.to_dict()
    response["deployment"] = {"deployment_status": "deploying"}
    return response


@router.get("")
async def list_customers(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=25, ge=1, le=100),
    search: Optional[str] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List customers with pagination, search, and status filter.

    Args:
        page: Page number (1-indexed).
        per_page: Items per page.
        search: Search in name, subdomain, email.
        status_filter: Filter by status.

    Returns:
        Paginated customer list with metadata.
    """
    query = db.query(Customer)

    if search:
        like_term = f"%{search}%"
        query = query.filter(
            (Customer.name.ilike(like_term))
            | (Customer.subdomain.ilike(like_term))
            | (Customer.email.ilike(like_term))
            | (Customer.company.ilike(like_term))
        )

    if status_filter:
        query = query.filter(Customer.status == status_filter)

    total = query.count()
    customers = (
        query.order_by(Customer.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    items = []
    for c in customers:
        data = c.to_dict()
        if c.deployment:
            data["deployment"] = c.deployment.to_dict()
        else:
            data["deployment"] = None
        items.append(data)

    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page if total > 0 else 1,
    }


@router.get("/{customer_id}")
async def get_customer(
    customer_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get detailed customer information including deployment and logs.

    Args:
        customer_id: Customer ID.

    Returns:
        Customer dict with deployment info and recent logs.
    """
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer not found.",
        )

    data = customer.to_dict()
    data["deployment"] = customer.deployment.to_dict() if customer.deployment else None
    data["logs"] = [
        log.to_dict()
        for log in db.query(DeploymentLog)
        .filter(DeploymentLog.customer_id == customer_id)
        .order_by(DeploymentLog.created_at.desc())
        .limit(50)
        .all()
    ]
    return data


@router.put("/{customer_id}")
async def update_customer(
    customer_id: int,
    payload: CustomerUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update customer information.

    Args:
        customer_id: Customer ID.
        payload: Fields to update.

    Returns:
        Updated customer dict.
    """
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer not found.",
        )

    update_data = payload.model_dump(exclude_none=True)
    for field, value in update_data.items():
        if hasattr(customer, field):
            setattr(customer, field, value)

    customer.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(customer)

    logger.info("Customer %d updated by %s.", customer_id, current_user.username)
    return customer.to_dict()


@router.delete("/{customer_id}")
async def delete_customer(
    customer_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a customer and clean up all resources.

    Removes containers, NPM proxy, instance directory, and database records.

    Args:
        customer_id: Customer ID.

    Returns:
        Confirmation message.
    """
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer not found.",
        )

    # Undeploy first (containers, NPM, files)
    try:
        await netbird_service.undeploy_customer(db, customer_id)
    except Exception:
        logger.exception("Undeploy error for customer %d (continuing with delete)", customer_id)

    # Delete customer record (cascades to deployment + logs)
    db.delete(customer)
    db.commit()

    logger.info("Customer %d deleted by %s.", customer_id, current_user.username)
    return {"message": f"Customer {customer_id} deleted successfully."}
