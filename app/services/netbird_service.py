"""NetBird deployment orchestration service.

Coordinates the full customer deployment lifecycle:
1. Validate inputs
2. Allocate ports
3. Generate configs from Jinja2 templates
4. Create instance directory and write files
5. Start Docker containers
6. Wait for health checks
7. Create NPM proxy hosts
8. Update database

Includes comprehensive rollback on failure.
"""

import logging
import os
import shutil
from datetime import datetime
from typing import Any

from jinja2 import Environment, FileSystemLoader
from sqlalchemy.orm import Session

from app.models import Customer, Deployment, DeploymentLog, SystemConfig
from app.services import docker_service, npm_service, port_manager
from app.utils.config import get_system_config
from app.utils.security import encrypt_value, generate_relay_secret

logger = logging.getLogger(__name__)

# Path to Jinja2 templates
TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates")


def _get_jinja_env() -> Environment:
    """Create a Jinja2 environment for template rendering."""
    return Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        keep_trailing_newline=True,
    )


def _log_action(
    db: Session, customer_id: int, action: str, status: str, message: str, details: str = ""
) -> None:
    """Write a deployment log entry.

    Args:
        db: Active session.
        customer_id: The customer this log belongs to.
        action: Action name (e.g. ``deploy``, ``stop``).
        status: ``success``, ``error``, or ``info``.
        message: Human-readable message.
        details: Additional details (optional).
    """
    log = DeploymentLog(
        customer_id=customer_id,
        action=action,
        status=status,
        message=message,
        details=details,
    )
    db.add(log)
    db.commit()


async def deploy_customer(db: Session, customer_id: int) -> dict[str, Any]:
    """Execute the full deployment workflow for a customer.

    Args:
        db: Active session.
        customer_id: Customer to deploy.

    Returns:
        Dict with ``success``, ``setup_url``, or ``error``.
    """
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        return {"success": False, "error": "Customer not found."}

    config = get_system_config(db)
    if not config:
        return {"success": False, "error": "System not configured. Please set up system settings first."}

    # Update status to deploying
    customer.status = "deploying"
    db.commit()

    _log_action(db, customer_id, "deploy", "info", "Deployment started.")

    allocated_port = None
    instance_dir = None
    container_prefix = f"netbird-kunde{customer_id}"

    try:
        # Step 1: Allocate relay UDP port
        allocated_port = port_manager.allocate_port(db, config.relay_base_port)
        _log_action(db, customer_id, "deploy", "info", f"Allocated UDP port {allocated_port}.")

        # Step 2: Generate relay secret
        relay_secret = generate_relay_secret()

        # Step 3: Create instance directory
        instance_dir = os.path.join(config.data_dir, f"kunde{customer_id}")
        os.makedirs(instance_dir, exist_ok=True)
        os.makedirs(os.path.join(instance_dir, "data", "management"), exist_ok=True)
        os.makedirs(os.path.join(instance_dir, "data", "signal"), exist_ok=True)
        _log_action(db, customer_id, "deploy", "info", f"Created directory {instance_dir}.")

        # Step 4: Render templates
        jinja_env = _get_jinja_env()
        template_vars = {
            "customer_id": customer_id,
            "subdomain": customer.subdomain,
            "base_domain": config.base_domain,
            "instance_dir": instance_dir,
            "relay_udp_port": allocated_port,
            "relay_secret": relay_secret,
            "netbird_management_image": config.netbird_management_image,
            "netbird_signal_image": config.netbird_signal_image,
            "netbird_relay_image": config.netbird_relay_image,
            "netbird_dashboard_image": config.netbird_dashboard_image,
            "docker_network": config.docker_network,
        }

        # docker-compose.yml
        dc_template = jinja_env.get_template("docker-compose.yml.j2")
        dc_content = dc_template.render(**template_vars)
        with open(os.path.join(instance_dir, "docker-compose.yml"), "w") as f:
            f.write(dc_content)

        # management.json
        mgmt_template = jinja_env.get_template("management.json.j2")
        mgmt_content = mgmt_template.render(**template_vars)
        with open(os.path.join(instance_dir, "management.json"), "w") as f:
            f.write(mgmt_content)

        # relay.env
        relay_template = jinja_env.get_template("relay.env.j2")
        relay_content = relay_template.render(**template_vars)
        with open(os.path.join(instance_dir, "relay.env"), "w") as f:
            f.write(relay_content)

        _log_action(db, customer_id, "deploy", "info", "Configuration files generated.")

        # Step 5: Start Docker containers
        docker_service.compose_up(instance_dir, container_prefix)
        _log_action(db, customer_id, "deploy", "info", "Docker containers started.")

        # Step 6: Wait for containers to be healthy
        healthy = docker_service.wait_for_healthy(container_prefix, timeout=60)
        if not healthy:
            _log_action(
                db, customer_id, "deploy", "error",
                "Containers did not become healthy within 60 seconds."
            )
            # Don't fail completely — containers might still come up

        # Step 7: Create NPM proxy host
        domain = f"{customer.subdomain}.{config.base_domain}"
        dashboard_container = f"netbird-kunde{customer_id}-dashboard"
        npm_result = await npm_service.create_proxy_host(
            api_url=config.npm_api_url,
            npm_email=config.npm_api_email,
            npm_password=config.npm_api_password,
            domain=domain,
            forward_host=dashboard_container,
            forward_port=80,
            admin_email=config.admin_email,
            subdomain=customer.subdomain,
            customer_id=customer_id,
        )

        npm_proxy_id = npm_result.get("proxy_id")
        if npm_result.get("error"):
            _log_action(
                db, customer_id, "deploy", "error",
                f"NPM proxy creation failed: {npm_result['error']}",
            )
            # Continue — deployment works without NPM, admin can fix later

        # Step 8: Create deployment record
        setup_url = f"https://{domain}"
        deployment = Deployment(
            customer_id=customer_id,
            container_prefix=container_prefix,
            relay_udp_port=allocated_port,
            npm_proxy_id=npm_proxy_id,
            relay_secret=encrypt_value(relay_secret),
            setup_url=setup_url,
            deployment_status="running",
            deployed_at=datetime.utcnow(),
        )
        db.add(deployment)

        customer.status = "active"
        db.commit()

        _log_action(db, customer_id, "deploy", "success", f"Deployment complete. URL: {setup_url}")

        return {"success": True, "setup_url": setup_url}

    except Exception as exc:
        logger.exception("Deployment failed for customer %d", customer_id)

        # Rollback: stop containers if they were started
        try:
            docker_service.compose_down(
                instance_dir or os.path.join(config.data_dir, f"kunde{customer_id}"),
                container_prefix,
                remove_volumes=True,
            )
        except Exception:
            pass

        # Rollback: remove instance directory
        if instance_dir and os.path.isdir(instance_dir):
            try:
                shutil.rmtree(instance_dir)
            except Exception:
                pass

        customer.status = "error"
        db.commit()

        _log_action(
            db, customer_id, "deploy", "error",
            f"Deployment failed: {exc}",
            details=str(exc),
        )

        return {"success": False, "error": str(exc)}


async def undeploy_customer(db: Session, customer_id: int) -> dict[str, Any]:
    """Remove all resources for a customer deployment.

    Args:
        db: Active session.
        customer_id: Customer to undeploy.

    Returns:
        Dict with ``success`` bool.
    """
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        return {"success": False, "error": "Customer not found."}

    deployment = db.query(Deployment).filter(Deployment.customer_id == customer_id).first()
    config = get_system_config(db)

    if deployment and config:
        instance_dir = os.path.join(config.data_dir, f"kunde{customer_id}")

        # Stop and remove containers
        try:
            docker_service.compose_down(instance_dir, deployment.container_prefix, remove_volumes=True)
            _log_action(db, customer_id, "undeploy", "info", "Containers removed.")
        except Exception as exc:
            _log_action(db, customer_id, "undeploy", "error", f"Container removal error: {exc}")

        # Remove NPM proxy host
        if deployment.npm_proxy_id and config.npm_api_email:
            try:
                await npm_service.delete_proxy_host(
                    config.npm_api_url, config.npm_api_email, config.npm_api_password,
                    deployment.npm_proxy_id,
                )
                _log_action(db, customer_id, "undeploy", "info", "NPM proxy host removed.")
            except Exception as exc:
                _log_action(db, customer_id, "undeploy", "error", f"NPM removal error: {exc}")

        # Remove instance directory
        if os.path.isdir(instance_dir):
            try:
                shutil.rmtree(instance_dir)
                _log_action(db, customer_id, "undeploy", "info", "Instance directory removed.")
            except Exception as exc:
                _log_action(db, customer_id, "undeploy", "error", f"Directory removal error: {exc}")

        # Remove deployment record
        db.delete(deployment)
        db.commit()

    _log_action(db, customer_id, "undeploy", "success", "Undeployment complete.")
    return {"success": True}


def stop_customer(db: Session, customer_id: int) -> dict[str, Any]:
    """Stop containers for a customer.

    Args:
        db: Active session.
        customer_id: Customer whose containers to stop.

    Returns:
        Dict with ``success`` bool.
    """
    deployment = db.query(Deployment).filter(Deployment.customer_id == customer_id).first()
    config = get_system_config(db)
    if not deployment or not config:
        return {"success": False, "error": "Deployment or config not found."}

    instance_dir = os.path.join(config.data_dir, f"kunde{customer_id}")
    ok = docker_service.compose_stop(instance_dir, deployment.container_prefix)
    if ok:
        deployment.deployment_status = "stopped"
        db.commit()
        _log_action(db, customer_id, "stop", "success", "Containers stopped.")
    else:
        _log_action(db, customer_id, "stop", "error", "Failed to stop containers.")
    return {"success": ok}


def start_customer(db: Session, customer_id: int) -> dict[str, Any]:
    """Start containers for a customer.

    Args:
        db: Active session.
        customer_id: Customer whose containers to start.

    Returns:
        Dict with ``success`` bool.
    """
    deployment = db.query(Deployment).filter(Deployment.customer_id == customer_id).first()
    config = get_system_config(db)
    if not deployment or not config:
        return {"success": False, "error": "Deployment or config not found."}

    instance_dir = os.path.join(config.data_dir, f"kunde{customer_id}")
    ok = docker_service.compose_start(instance_dir, deployment.container_prefix)
    if ok:
        deployment.deployment_status = "running"
        db.commit()
        _log_action(db, customer_id, "start", "success", "Containers started.")
    else:
        _log_action(db, customer_id, "start", "error", "Failed to start containers.")
    return {"success": ok}


def restart_customer(db: Session, customer_id: int) -> dict[str, Any]:
    """Restart containers for a customer.

    Args:
        db: Active session.
        customer_id: Customer whose containers to restart.

    Returns:
        Dict with ``success`` bool.
    """
    deployment = db.query(Deployment).filter(Deployment.customer_id == customer_id).first()
    config = get_system_config(db)
    if not deployment or not config:
        return {"success": False, "error": "Deployment or config not found."}

    instance_dir = os.path.join(config.data_dir, f"kunde{customer_id}")
    ok = docker_service.compose_restart(instance_dir, deployment.container_prefix)
    if ok:
        deployment.deployment_status = "running"
        db.commit()
        _log_action(db, customer_id, "restart", "success", "Containers restarted.")
    else:
        _log_action(db, customer_id, "restart", "error", "Failed to restart containers.")
    return {"success": ok}


def get_customer_health(db: Session, customer_id: int) -> dict[str, Any]:
    """Check health of a customer's deployment.

    Args:
        db: Active session.
        customer_id: Customer ID.

    Returns:
        Dict with container statuses and overall health.
    """
    deployment = db.query(Deployment).filter(Deployment.customer_id == customer_id).first()
    if not deployment:
        return {"healthy": False, "error": "No deployment found.", "containers": []}

    containers = docker_service.get_container_status(deployment.container_prefix)
    all_running = all(c["status"] == "running" for c in containers) if containers else False

    # Update last health check time
    deployment.last_health_check = datetime.utcnow()
    if all_running:
        deployment.deployment_status = "running"
    elif containers:
        deployment.deployment_status = "failed"
    db.commit()

    return {
        "healthy": all_running,
        "containers": containers,
        "deployment_status": deployment.deployment_status,
        "last_check": deployment.last_health_check.isoformat(),
    }
