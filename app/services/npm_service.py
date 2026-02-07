"""Nginx Proxy Manager API integration.

Creates, updates, and deletes proxy host entries so each customer's NetBird
dashboard is accessible at ``{subdomain}.{base_domain}`` with automatic
Let's Encrypt SSL certificates.
"""

import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

# Timeout for NPM API calls (seconds)
NPM_TIMEOUT = 30


async def test_npm_connection(api_url: str, api_token: str) -> dict[str, Any]:
    """Test connectivity to the Nginx Proxy Manager API.

    Args:
        api_url: NPM API base URL (e.g. ``http://npm:81/api``).
        api_token: Bearer token for authentication.

    Returns:
        Dict with ``ok`` (bool) and ``message`` (str).
    """
    headers = {"Authorization": f"Bearer {api_token}"}
    try:
        async with httpx.AsyncClient(timeout=NPM_TIMEOUT) as client:
            resp = await client.get(f"{api_url}/nginx/proxy-hosts", headers=headers)
            if resp.status_code == 200:
                count = len(resp.json())
                return {"ok": True, "message": f"Connected. {count} proxy hosts found."}
            return {
                "ok": False,
                "message": f"NPM returned status {resp.status_code}: {resp.text[:200]}",
            }
    except httpx.ConnectError:
        return {"ok": False, "message": "Connection refused. Is NPM running?"}
    except httpx.TimeoutException:
        return {"ok": False, "message": "Connection timed out."}
    except Exception as exc:
        return {"ok": False, "message": f"Unexpected error: {exc}"}


async def create_proxy_host(
    api_url: str,
    api_token: str,
    domain: str,
    forward_host: str,
    forward_port: int = 80,
    admin_email: str = "",
    subdomain: str = "",
    customer_id: int = 0,
) -> dict[str, Any]:
    """Create a proxy host entry in NPM with SSL for a customer.

    The proxy routes traffic as follows:
    - ``/``            -> dashboard container (port 80)
    - ``/api``         -> management container (port 80)
    - ``/signalexchange.*`` -> signal container (port 80)
    - ``/relay``       -> relay container (port 80)

    Args:
        api_url: NPM API base URL.
        api_token: Bearer token.
        domain: Full domain (e.g. ``kunde1.example.com``).
        forward_host: Container name for the dashboard.
        forward_port: Port to forward to (default 80).
        admin_email: Email for Let's Encrypt.
        subdomain: Customer subdomain for building container names.
        customer_id: Customer ID for building container names.

    Returns:
        Dict with ``proxy_id`` on success or ``error`` on failure.
    """
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }

    # Build advanced Nginx config to route sub-paths to different containers
    mgmt_container = f"netbird-kunde{customer_id}-management"
    signal_container = f"netbird-kunde{customer_id}-signal"
    relay_container = f"netbird-kunde{customer_id}-relay"

    advanced_config = f"""
# NetBird Management API
location /api {{
    proxy_pass http://{mgmt_container}:80;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}}

# NetBird Signal (gRPC-Web)
location /signalexchange. {{
    grpc_pass grpc://{signal_container}:80;
    grpc_set_header Host $host;
}}

# NetBird Relay (WebSocket)
location /relay {{
    proxy_pass http://{relay_container}:80;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
}}
"""

    payload = {
        "domain_names": [domain],
        "forward_scheme": "http",
        "forward_host": forward_host,
        "forward_port": forward_port,
        "certificate_id": 0,
        "ssl_forced": True,
        "hsts_enabled": True,
        "hsts_subdomains": False,
        "http2_support": True,
        "block_exploits": True,
        "allow_websocket_upgrade": True,
        "access_list_id": 0,
        "advanced_config": advanced_config.strip(),
        "meta": {
            "letsencrypt_agree": True,
            "letsencrypt_email": admin_email,
            "dns_challenge": False,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=NPM_TIMEOUT) as client:
            resp = await client.post(
                f"{api_url}/nginx/proxy-hosts", json=payload, headers=headers
            )
            if resp.status_code in (200, 201):
                data = resp.json()
                proxy_id = data.get("id")
                logger.info("Created NPM proxy host %s (id=%s)", domain, proxy_id)

                # Request SSL certificate
                await _request_ssl(client, api_url, headers, proxy_id, domain, admin_email)

                return {"proxy_id": proxy_id}
            else:
                error_msg = f"NPM returned {resp.status_code}: {resp.text[:300]}"
                logger.error("Failed to create proxy host: %s", error_msg)
                return {"error": error_msg}
    except Exception as exc:
        logger.error("NPM API error: %s", exc)
        return {"error": str(exc)}


async def _request_ssl(
    client: httpx.AsyncClient,
    api_url: str,
    headers: dict,
    proxy_id: int,
    domain: str,
    admin_email: str,
) -> None:
    """Request a Let's Encrypt SSL certificate for a proxy host.

    Args:
        client: httpx client.
        api_url: NPM API base URL.
        headers: Auth headers.
        proxy_id: The proxy host ID.
        domain: The domain to certify.
        admin_email: Contact email for LE.
    """
    ssl_payload = {
        "domain_names": [domain],
        "meta": {
            "letsencrypt_agree": True,
            "letsencrypt_email": admin_email,
            "dns_challenge": False,
        },
    }
    try:
        resp = await client.post(
            f"{api_url}/nginx/certificates", json=ssl_payload, headers=headers
        )
        if resp.status_code in (200, 201):
            cert_id = resp.json().get("id")
            # Assign certificate to proxy host
            await client.put(
                f"{api_url}/nginx/proxy-hosts/{proxy_id}",
                json={"certificate_id": cert_id},
                headers=headers,
            )
            logger.info("SSL certificate assigned to proxy host %s", proxy_id)
        else:
            logger.warning("SSL request returned %s: %s", resp.status_code, resp.text[:200])
    except Exception as exc:
        logger.warning("SSL certificate request failed: %s", exc)


async def delete_proxy_host(
    api_url: str, api_token: str, proxy_id: int
) -> bool:
    """Delete a proxy host from NPM.

    Args:
        api_url: NPM API base URL.
        api_token: Bearer token.
        proxy_id: The proxy host ID to delete.

    Returns:
        True on success.
    """
    headers = {"Authorization": f"Bearer {api_token}"}
    try:
        async with httpx.AsyncClient(timeout=NPM_TIMEOUT) as client:
            resp = await client.delete(
                f"{api_url}/nginx/proxy-hosts/{proxy_id}", headers=headers
            )
            if resp.status_code in (200, 204):
                logger.info("Deleted NPM proxy host %d", proxy_id)
                return True
            logger.warning(
                "Failed to delete proxy host %d: %s %s",
                proxy_id, resp.status_code, resp.text[:200],
            )
            return False
    except Exception as exc:
        logger.error("NPM delete error: %s", exc)
        return False
