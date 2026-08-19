"""Deployment management API — start, stop, restart, logs, health for customers."""

import logging
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import SessionLocal, get_db
from app.dependencies import get_current_user
from app.models import Customer, Deployment, SystemConfig, User
from app.services import docker_service, image_service, netbird_client_update_service, netbird_service
from app.utils.security import decrypt_value, encrypt_value
from app.utils.validators import NetbirdApiTokenPayload, NetbirdClientAutoUpdatePayload

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/{customer_id}/deploy")
async def manual_deploy(
    customer_id: int,
    background_tasks: BackgroundTasks,
    keep_data: bool = Query(
        False,
        description=(
            "If True, preserve existing NetBird data (database, keys, peers). "
            "Containers are recreated without wiping the instance directory. "
            "If False (default), the instance is fully removed and redeployed from scratch."
        ),
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Manually trigger deployment for a customer.

    Use this to re-deploy a customer whose previous deployment failed.
    Runs in background and returns immediately.

    Args:
        customer_id: Customer ID.
        keep_data: Whether to preserve existing NetBird data.

    Returns:
        Acknowledgement dict.
    """
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found.")

    customer.status = "deploying"
    db.commit()

    async def _deploy_bg(cid: int, keep: bool) -> None:
        bg_db = SessionLocal()
        try:
            existing = bg_db.query(Deployment).filter(Deployment.customer_id == cid).first()
            if existing and not keep:
                # Full redeploy: remove everything first
                await netbird_service.undeploy_customer(bg_db, cid)
            await netbird_service.deploy_customer(bg_db, cid)
        except Exception:
            logger.exception("Background re-deploy failed for customer %d", cid)
        finally:
            bg_db.close()

    background_tasks.add_task(_deploy_bg, customer_id, keep_data)
    return {"message": "Deployment started in background.", "status": "deploying"}


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
    result = await netbird_service.start_customer(db, customer_id)
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
    result = await netbird_service.stop_customer(db, customer_id)
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
    result = await netbird_service.restart_customer(db, customer_id)
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


@router.get("/{customer_id}/credentials")
async def get_customer_credentials(
    customer_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get the NetBird admin credentials for a customer's deployment.

    Args:
        customer_id: Customer ID.

    Returns:
        Dict with email and password.
    """
    _require_customer(db, customer_id)
    deployment = db.query(Deployment).filter(Deployment.customer_id == customer_id).first()
    if not deployment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No deployment found for this customer.",
        )
    if not deployment.netbird_admin_email or not deployment.netbird_admin_password:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No credentials available. Admin must complete setup manually.",
        )
    return {
        "email": decrypt_value(deployment.netbird_admin_email),
        "password": decrypt_value(deployment.netbird_admin_password),
    }


@router.post("/{customer_id}/update-images")
async def update_customer_images(
    customer_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Recreate a customer's containers to pick up newly pulled images.

    Images must already be pulled via POST /monitoring/images/pull.
    Bind-mounted data is preserved — no data loss.
    """
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only.")

    customer = _require_customer(db, customer_id)
    deployment = db.query(Deployment).filter(Deployment.customer_id == customer_id).first()
    if not deployment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No deployment found for this customer.",
        )

    config = db.query(SystemConfig).filter(SystemConfig.id == 1).first()
    if not config:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="System not configured."
        )

    instance_dir = f"{config.data_dir}/{customer.subdomain}"
    result = await image_service.update_customer_containers(instance_dir, deployment.container_prefix)

    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.get("error", "Failed to update containers."),
        )

    logger.info(
        "Containers updated for customer '%s' (prefix: %s) by '%s'.",
        customer.name, deployment.container_prefix, current_user.username,
    )
    return {"message": f"Containers updated for '{customer.name}'."}


@router.get("/{customer_id}/netbird-updates")
async def get_customer_netbird_updates(
    customer_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Fetch a customer's *live* NetBird client automatic-updates setting.

    Reads directly from the customer's NetBird Management API — always
    reflects reality, including changes made manually in their own dashboard.
    """
    _require_customer(db, customer_id)
    deployment = db.query(Deployment).filter(Deployment.customer_id == customer_id).first()
    if not deployment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No deployment found for this customer.")
    if not deployment.netbird_api_token_encrypted:
        return {"has_token": False, "version": None, "always": None}

    token = decrypt_value(deployment.netbird_api_token_encrypted)
    result = await netbird_client_update_service.get_current_settings(deployment.container_prefix, token)
    if not result["ok"]:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=result["error"])

    settings = result["settings"]
    return {
        "has_token": True,
        "version": settings.get("auto_update_version", "disabled"),
        "always": bool(settings.get("auto_update_always", False)),
    }


@router.put("/{customer_id}/netbird-updates")
async def set_customer_netbird_updates(
    customer_id: int,
    payload: NetbirdClientAutoUpdatePayload,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Push a client automatic-updates version/mode to a single customer.

    Use this to override the master default for one customer specifically —
    e.g. a customer on a legacy client that must not jump straight to latest.
    """
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only.")

    _require_customer(db, customer_id)
    deployment = db.query(Deployment).filter(Deployment.customer_id == customer_id).first()
    if not deployment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No deployment found for this customer.")
    if not deployment.netbird_api_token_encrypted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No NetBird API token registered for this customer. Paste one via PUT .../netbird-api-token first.",
        )

    token = decrypt_value(deployment.netbird_api_token_encrypted)
    result = await netbird_client_update_service.push_auto_update_settings(
        deployment.container_prefix, token, payload.version, payload.always
    )
    if not result["ok"]:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=result["error"])

    logger.info(
        "NetBird client auto-update set for customer %d (%s): version=%s always=%s by %s",
        customer_id, deployment.container_prefix, payload.version, payload.always, current_user.username,
    )
    return {"ok": True}


@router.put("/{customer_id}/netbird-api-token")
async def set_customer_netbird_api_token(
    customer_id: int,
    payload: NetbirdApiTokenPayload,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Manually register a NetBird Personal Access Token for a customer.

    Needed for customers deployed before automatic PAT capture — create a
    PAT once in that customer's dashboard (Settings > Service Users /
    Personal Access Tokens) and paste it here. New deployments capture one
    automatically during setup.
    """
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only.")

    _require_customer(db, customer_id)
    deployment = db.query(Deployment).filter(Deployment.customer_id == customer_id).first()
    if not deployment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No deployment found for this customer.")

    # Validate the token actually works before storing it.
    result = await netbird_client_update_service.get_current_settings(deployment.container_prefix, payload.token)
    if not result["ok"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Token could not be verified against this customer's NetBird instance: {result['error']}",
        )

    deployment.netbird_api_token_encrypted = encrypt_value(payload.token)
    deployment.netbird_api_token_renewed_at = datetime.utcnow()
    db.commit()
    logger.info("NetBird API token registered for customer %d by %s.", customer_id, current_user.username)
    return {"ok": True}


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
