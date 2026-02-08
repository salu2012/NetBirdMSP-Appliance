"""NetBird deployment orchestration service.

Coordinates the full customer deployment lifecycle:
1. Validate inputs
2. Allocate ports
3. Generate configs from Jinja2 templates
4. Create instance directory and write files
5. Start Docker containers
6. Create NPM proxy hosts (production only)
7. Update database

Uses NetBird's embedded IdP (built-in since v0.62) — no external
identity provider (Zitadel, Keycloak, etc.) required.

Includes comprehensive rollback on failure.
"""

import json
import logging
import os
import secrets
import shutil
import time
import urllib.request
import urllib.error
from datetime import datetime
from typing import Any

from jinja2 import Environment, FileSystemLoader
from sqlalchemy.orm import Session

from app.models import Customer, Deployment, DeploymentLog
from app.services import docker_service, npm_service, port_manager
from app.utils.config import get_system_config
from app.utils.security import encrypt_value, generate_datastore_encryption_key, generate_relay_secret

logger = logging.getLogger(__name__)

# Path to Jinja2 templates
TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates")


def _get_jinja_env() -> Environment:
    """Create a Jinja2 environment for template rendering."""
    return Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        keep_trailing_newline=True,
    )


def _is_local_domain(base_domain: str) -> bool:
    """Check if the base domain is a local/test domain."""
    local_suffixes = (".local", ".test", ".localhost", ".internal", ".example")
    return base_domain == "localhost" or any(base_domain.endswith(s) for s in local_suffixes)


def _log_action(
    db: Session, customer_id: int, action: str, status: str, message: str, details: str = ""
) -> None:
    """Write a deployment log entry."""
    log = DeploymentLog(
        customer_id=customer_id,
        action=action,
        status=status,
        message=message,
        details=details,
    )
    db.add(log)
    db.commit()


def _render_template(jinja_env: Environment, template_name: str, output_path: str, **vars) -> None:
    """Render a Jinja2 template and write the output to a file."""
    template = jinja_env.get_template(template_name)
    content = template.render(**vars)
    with open(output_path, "w") as f:
        f.write(content)


async def deploy_customer(db: Session, customer_id: int) -> dict[str, Any]:
    """Execute the full deployment workflow for a customer.

    Uses NetBird's embedded IdP — no external identity provider needed.
    After deployment, the admin opens the dashboard URL and completes
    the initial setup wizard (/setup) to create the first user.
    """
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        return {"success": False, "error": "Customer not found."}

    config = get_system_config(db)
    if not config:
        return {"success": False, "error": "System not configured. Please set up system settings first."}

    customer.status = "deploying"
    db.commit()

    _log_action(db, customer_id, "deploy", "info", "Deployment started.")

    allocated_port = None
    instance_dir = None
    container_prefix = f"netbird-kunde{customer_id}"
    local_mode = _is_local_domain(config.base_domain)

    try:
        # Step 1: Allocate relay UDP port
        allocated_port = port_manager.allocate_port(db, config.relay_base_port)
        _log_action(db, customer_id, "deploy", "info", f"Allocated UDP port {allocated_port}.")

        # Step 2: Generate secrets
        relay_secret = generate_relay_secret()
        datastore_key = generate_datastore_encryption_key()

        # Step 3: Compute dashboard port and URLs
        dashboard_port = config.dashboard_base_port + customer_id
        netbird_domain = f"{customer.subdomain}.{config.base_domain}"

        if local_mode:
            external_url = f"http://localhost:{dashboard_port}"
            netbird_protocol = "http"
            netbird_port = str(dashboard_port)
        else:
            external_url = f"https://{netbird_domain}"
            netbird_protocol = "https"
            netbird_port = "443"

        # Step 4: Create instance directory
        instance_dir = os.path.join(config.data_dir, f"kunde{customer_id}")
        os.makedirs(instance_dir, exist_ok=True)
        os.makedirs(os.path.join(instance_dir, "data", "management"), exist_ok=True)
        os.makedirs(os.path.join(instance_dir, "data", "signal"), exist_ok=True)
        _log_action(db, customer_id, "deploy", "info", f"Created directory {instance_dir}.")

        # Step 5: Render all config files
        jinja_env = _get_jinja_env()
        template_vars = {
            "customer_id": customer_id,
            "subdomain": customer.subdomain,
            "base_domain": config.base_domain,
            "netbird_domain": netbird_domain,
            "instance_dir": instance_dir,
            "relay_udp_port": allocated_port,
            "relay_secret": relay_secret,
            "dashboard_port": dashboard_port,
            "external_url": external_url,
            "netbird_protocol": netbird_protocol,
            "netbird_port": netbird_port,
            "netbird_management_image": config.netbird_management_image,
            "netbird_signal_image": config.netbird_signal_image,
            "netbird_relay_image": config.netbird_relay_image,
            "netbird_dashboard_image": config.netbird_dashboard_image,
            "docker_network": config.docker_network,
            "datastore_encryption_key": datastore_key,
        }

        _render_template(jinja_env, "docker-compose.yml.j2",
                         os.path.join(instance_dir, "docker-compose.yml"), **template_vars)
        _render_template(jinja_env, "management.json.j2",
                         os.path.join(instance_dir, "management.json"), **template_vars)
        _render_template(jinja_env, "relay.env.j2",
                         os.path.join(instance_dir, "relay.env"), **template_vars)
        _render_template(jinja_env, "Caddyfile.j2",
                         os.path.join(instance_dir, "Caddyfile"), **template_vars)
        _render_template(jinja_env, "dashboard.env.j2",
                         os.path.join(instance_dir, "dashboard.env"), **template_vars)

        _log_action(db, customer_id, "deploy", "info", "Configuration files generated.")

        # Step 6: Start all Docker containers
        docker_service.compose_up(instance_dir, container_prefix, timeout=120)
        _log_action(db, customer_id, "deploy", "info", "Docker containers started.")

        # Step 7: Wait for containers to be healthy
        healthy = docker_service.wait_for_healthy(container_prefix, timeout=90)
        if not healthy:
            _log_action(
                db, customer_id, "deploy", "info",
                "Not all containers healthy within 90s — may still be starting."
            )

        # Step 8: Auto-create admin user via NetBird setup API
        admin_email = customer.email
        admin_password = secrets.token_urlsafe(16)
        management_container = f"netbird-kunde{customer_id}-management"
        setup_api_url = f"http://{management_container}:80/api/setup"
        setup_payload = json.dumps({
            "name": customer.name,
            "email": admin_email,
            "password": admin_password,
        }).encode("utf-8")

        setup_ok = False
        for attempt in range(10):
            try:
                req = urllib.request.Request(
                    setup_api_url,
                    data=setup_payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    if resp.status in (200, 201):
                        setup_ok = True
                        _log_action(db, customer_id, "deploy", "info",
                                    f"Admin user created: {admin_email}")
                        break
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", errors="replace")
                if e.code == 409 or "already" in body.lower():
                    _log_action(db, customer_id, "deploy", "info",
                                "Instance already set up — skipping admin creation.")
                    setup_ok = True
                    break
                logger.info("Setup attempt %d failed (HTTP %d): %s", attempt + 1, e.code, body)
            except Exception as e:
                logger.info("Setup attempt %d failed: %s", attempt + 1, e)
            time.sleep(5)

        if not setup_ok:
            _log_action(db, customer_id, "deploy", "info",
                        "Auto-setup failed — admin must complete setup manually.")

        # Step 9: Create NPM proxy host (production only)
        npm_proxy_id = None
        if not local_mode:
            caddy_container = f"netbird-kunde{customer_id}-caddy"
            npm_result = await npm_service.create_proxy_host(
                api_url=config.npm_api_url,
                npm_email=config.npm_api_email,
                npm_password=config.npm_api_password,
                domain=netbird_domain,
                forward_host=caddy_container,
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

        # Step 9: Create deployment record
        setup_url = external_url

        deployment = Deployment(
            customer_id=customer_id,
            container_prefix=container_prefix,
            relay_udp_port=allocated_port,
            dashboard_port=dashboard_port,
            npm_proxy_id=npm_proxy_id,
            relay_secret=encrypt_value(relay_secret),
            setup_url=setup_url,
            netbird_admin_email=encrypt_value(admin_email) if setup_ok else None,
            netbird_admin_password=encrypt_value(admin_password) if setup_ok else None,
            deployment_status="running",
            deployed_at=datetime.utcnow(),
        )
        db.add(deployment)

        customer.status = "active"
        db.commit()

        _log_action(db, customer_id, "deploy", "success",
                    f"Deployment complete. Open {setup_url} to complete initial setup.")

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
    """Remove all resources for a customer deployment."""
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
    """Stop containers for a customer."""
    deployment = db.query(Deployment).filter(Deployment.customer_id == customer_id).first()
    config = get_system_config(db)
    if not deployment or not config:
        return {"success": False, "error": "Deployment or config not found."}

    instance_dir = os.path.join(config.data_dir, f"kunde{customer_id}")
    ok = docker_service.compose_stop(instance_dir, deployment.container_prefix)
    if ok:
        deployment.deployment_status = "stopped"
        customer = db.query(Customer).filter(Customer.id == customer_id).first()
        if customer:
            customer.status = "inactive"
        db.commit()
        _log_action(db, customer_id, "stop", "success", "Containers stopped.")
    else:
        _log_action(db, customer_id, "stop", "error", "Failed to stop containers.")
    return {"success": ok}


def start_customer(db: Session, customer_id: int) -> dict[str, Any]:
    """Start containers for a customer."""
    deployment = db.query(Deployment).filter(Deployment.customer_id == customer_id).first()
    config = get_system_config(db)
    if not deployment or not config:
        return {"success": False, "error": "Deployment or config not found."}

    instance_dir = os.path.join(config.data_dir, f"kunde{customer_id}")
    ok = docker_service.compose_start(instance_dir, deployment.container_prefix)
    if ok:
        deployment.deployment_status = "running"
        customer = db.query(Customer).filter(Customer.id == customer_id).first()
        if customer:
            customer.status = "active"
        db.commit()
        _log_action(db, customer_id, "start", "success", "Containers started.")
    else:
        _log_action(db, customer_id, "start", "error", "Failed to start containers.")
    return {"success": ok}


def restart_customer(db: Session, customer_id: int) -> dict[str, Any]:
    """Restart containers for a customer."""
    deployment = db.query(Deployment).filter(Deployment.customer_id == customer_id).first()
    config = get_system_config(db)
    if not deployment or not config:
        return {"success": False, "error": "Deployment or config not found."}

    instance_dir = os.path.join(config.data_dir, f"kunde{customer_id}")
    ok = docker_service.compose_restart(instance_dir, deployment.container_prefix)
    if ok:
        deployment.deployment_status = "running"
        customer = db.query(Customer).filter(Customer.id == customer_id).first()
        if customer:
            customer.status = "active"
        db.commit()
        _log_action(db, customer_id, "restart", "success", "Containers restarted.")
    else:
        _log_action(db, customer_id, "restart", "error", "Failed to restart containers.")
    return {"success": ok}


def get_customer_health(db: Session, customer_id: int) -> dict[str, Any]:
    """Check health of a customer's deployment."""
    deployment = db.query(Deployment).filter(Deployment.customer_id == customer_id).first()
    if not deployment:
        return {"healthy": False, "error": "No deployment found.", "containers": []}

    containers = docker_service.get_container_status(deployment.container_prefix)
    all_running = all(c["status"] == "running" for c in containers) if containers else False

    deployment.last_health_check = datetime.utcnow()
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if all_running:
        deployment.deployment_status = "running"
        if customer:
            customer.status = "active"
    elif containers:
        deployment.deployment_status = "failed"
        if customer:
            customer.status = "error"
    db.commit()

    return {
        "healthy": all_running,
        "containers": containers,
        "deployment_status": deployment.deployment_status,
        "last_check": deployment.last_health_check.isoformat(),
    }
