"""Nginx Proxy Manager API integration.

NPM uses JWT authentication — there are no static API tokens.
Every API session starts with a login (POST /api/tokens) using email + password,
which returns a short-lived JWT. That JWT is then used as Bearer token for all
subsequent requests.

Creates, updates, and deletes proxy host entries so each customer's NetBird
dashboard is accessible at ``{subdomain}.{base_domain}`` with automatic
Let's Encrypt SSL certificates.

Also manages NPM streams for STUN/TURN relay UDP ports.
"""

import logging
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# Timeout for NPM API calls (seconds)
NPM_TIMEOUT = 30


def _get_forward_host(npm_api_url: str) -> str:
    """Determine the IP/hostname to forward traffic to.

    The NPM proxy host must forward to the MSP appliance's host IP,
    NOT to a Docker container name, because the customer's Caddy
    container exposes its port on the host via Docker port mapping.

    We extract the host from the NPM API URL — if the admin configured
    ``http://10.0.0.5:81/api``, we forward to ``10.0.0.5``.
    If the admin configured ``http://npm:81/api`` (container name),
    we fall back to the Docker gateway IP ``172.17.0.1``.

    Args:
        npm_api_url: The NPM API base URL from system config.

    Returns:
        IP address or hostname to forward to.
    """
    parsed = urlparse(npm_api_url)
    host = parsed.hostname or "172.17.0.1"

    # If the host looks like a container name (no dots, not an IP), use Docker gateway
    if not any(c == "." for c in host) and not host.startswith("172.") and host != "localhost":
        logger.info("NPM URL host '%s' looks like a container name, using Docker gateway 172.17.0.1", host)
        return "172.17.0.1"

    return host


async def _npm_login(client: httpx.AsyncClient, api_url: str, email: str, password: str) -> str:
    """Authenticate with NPM and return a JWT token.

    NPM does NOT support static API keys. Auth is always:
    POST /api/tokens  with {"identity": "<email>", "secret": "<password>"}

    Args:
        client: httpx async client.
        api_url: NPM API base URL (e.g. ``http://npm:81/api``).
        email: NPM login email / identity.
        password: NPM login password / secret.

    Returns:
        JWT token string.

    Raises:
        RuntimeError: If login fails.
    """
    resp = await client.post(
        f"{api_url}/tokens",
        json={"identity": email, "secret": password},
    )
    if resp.status_code in (200, 201):
        data = resp.json()
        token = data.get("token")
        if token:
            logger.debug("NPM login successful for %s", email)
            return token
        raise RuntimeError("NPM login response did not contain a token.")
    raise RuntimeError(
        f"NPM login failed (HTTP {resp.status_code}): {resp.text[:300]}"
    )


async def test_npm_connection(api_url: str, email: str, password: str) -> dict[str, Any]:
    """Test connectivity to NPM by logging in and listing proxy hosts.

    Args:
        api_url: NPM API base URL.
        email: NPM login email.
        password: NPM login password.

    Returns:
        Dict with ``ok`` (bool) and ``message`` (str).
    """
    try:
        async with httpx.AsyncClient(timeout=NPM_TIMEOUT) as client:
            token = await _npm_login(client, api_url, email, password)
            headers = {"Authorization": f"Bearer {token}"}
            resp = await client.get(f"{api_url}/nginx/proxy-hosts", headers=headers)
            if resp.status_code == 200:
                count = len(resp.json())
                return {"ok": True, "message": f"Connected. Login OK. {count} proxy hosts found."}
            return {
                "ok": False,
                "message": f"Login OK but listing hosts returned {resp.status_code}: {resp.text[:200]}",
            }
    except RuntimeError as exc:
        return {"ok": False, "message": str(exc)}
    except httpx.ConnectError:
        return {"ok": False, "message": "Connection refused. Is NPM running and reachable?"}
    except httpx.TimeoutException:
        return {"ok": False, "message": "Connection timed out."}
    except Exception as exc:
        return {"ok": False, "message": f"Unexpected error: {exc}"}


async def create_proxy_host(
    api_url: str,
    npm_email: str,
    npm_password: str,
    domain: str,
    forward_host: str,
    forward_port: int = 80,
    admin_email: str = "",
) -> dict[str, Any]:
    """Create a proxy host entry in NPM with SSL for a customer.

    Forwards traffic to the host IP + dashboard_port where the customer's
    Caddy reverse proxy is listening. Caddy handles internal routing to
    management, signal, relay, and dashboard containers.

    Args:
        api_url: NPM API base URL.
        npm_email: NPM login email.
        npm_password: NPM login password.
        domain: Full domain (e.g. ``kunde1.example.com``).
        forward_host: IP/hostname to forward to (host IP, not container name).
        forward_port: Port to forward to (dashboard_port, e.g. 9001).
        admin_email: Email for Let's Encrypt.

    Returns:
        Dict with ``proxy_id`` on success or ``error`` on failure.
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
        "advanced_config": "",
        "meta": {
            "letsencrypt_agree": True,
            "letsencrypt_email": admin_email,
            "dns_challenge": False,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=NPM_TIMEOUT) as client:
            # Step 1: Login to NPM
            token = await _npm_login(client, api_url, npm_email, npm_password)
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }

            # Step 2: Create proxy host
            resp = await client.post(
                f"{api_url}/nginx/proxy-hosts", json=payload, headers=headers
            )
            if resp.status_code in (200, 201):
                data = resp.json()
                proxy_id = data.get("id")
                logger.info("Created NPM proxy host %s -> %s:%d (id=%s)",
                            domain, forward_host, forward_port, proxy_id)

                # Step 3: Request SSL certificate
                await _request_ssl(client, api_url, headers, proxy_id, domain, admin_email)

                return {"proxy_id": proxy_id}
            else:
                error_msg = f"NPM returned {resp.status_code}: {resp.text[:300]}"
                logger.error("Failed to create proxy host: %s", error_msg)
                return {"error": error_msg}
    except RuntimeError as exc:
        logger.error("NPM login failed: %s", exc)
        return {"error": f"NPM login failed: {exc}"}
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
        client: httpx client (already authenticated).
        api_url: NPM API base URL.
        headers: Auth headers with Bearer token.
        proxy_id: The proxy host ID.
        domain: The domain to certify.
        admin_email: Contact email for LE.
    """
    ssl_payload = {
        "domain_names": [domain],
        "provider": "letsencrypt",
        "nice_name": domain,
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
            logger.info("SSL certificate %s assigned to proxy host %s", cert_id, proxy_id)
        else:
            logger.warning("SSL request returned %s: %s", resp.status_code, resp.text[:200])
    except Exception as exc:
        logger.warning("SSL certificate request failed: %s", exc)


async def create_stream(
    api_url: str,
    npm_email: str,
    npm_password: str,
    incoming_port: int,
    forwarding_host: str,
    forwarding_port: int,
) -> dict[str, Any]:
    """Create a UDP stream in NPM for STUN/TURN relay forwarding.

    NPM streams forward raw TCP/UDP traffic (Layer 4) without HTTP processing.
    Used for the relay STUN port (UDP 3478+).

    Args:
        api_url: NPM API base URL.
        npm_email: NPM login email.
        npm_password: NPM login password.
        incoming_port: The public-facing port NPM listens on.
        forwarding_host: IP/hostname to forward to.
        forwarding_port: The port on the target host.

    Returns:
        Dict with ``stream_id`` on success or ``error`` on failure.
    """
    payload = {
        "incoming_port": incoming_port,
        "forwarding_host": forwarding_host,
        "forwarding_port": forwarding_port,
        "tcp_forwarding": False,
        "udp_forwarding": True,
        "meta": {},
    }

    try:
        async with httpx.AsyncClient(timeout=NPM_TIMEOUT) as client:
            token = await _npm_login(client, api_url, npm_email, npm_password)
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }

            resp = await client.post(
                f"{api_url}/nginx/streams", json=payload, headers=headers
            )
            if resp.status_code in (200, 201):
                data = resp.json()
                stream_id = data.get("id")
                logger.info(
                    "Created NPM stream: UDP :%d -> %s:%d (id=%s)",
                    incoming_port, forwarding_host, forwarding_port, stream_id,
                )
                return {"stream_id": stream_id}
            else:
                error_msg = f"NPM stream creation returned {resp.status_code}: {resp.text[:300]}"
                logger.error("Failed to create NPM stream: %s", error_msg)
                return {"error": error_msg}
    except RuntimeError as exc:
        logger.error("NPM login failed for stream creation: %s", exc)
        return {"error": f"NPM login failed: {exc}"}
    except Exception as exc:
        logger.error("NPM stream API error: %s", exc)
        return {"error": str(exc)}


async def delete_stream(
    api_url: str, npm_email: str, npm_password: str, stream_id: int
) -> bool:
    """Delete a stream from NPM.

    Args:
        api_url: NPM API base URL.
        npm_email: NPM login email.
        npm_password: NPM login password.
        stream_id: The stream ID to delete.

    Returns:
        True on success.
    """
    try:
        async with httpx.AsyncClient(timeout=NPM_TIMEOUT) as client:
            token = await _npm_login(client, api_url, npm_email, npm_password)
            headers = {"Authorization": f"Bearer {token}"}
            resp = await client.delete(
                f"{api_url}/nginx/streams/{stream_id}", headers=headers
            )
            if resp.status_code in (200, 204):
                logger.info("Deleted NPM stream %d", stream_id)
                return True
            logger.warning(
                "Failed to delete stream %d: %s %s",
                stream_id, resp.status_code, resp.text[:200],
            )
            return False
    except Exception as exc:
        logger.error("NPM stream delete error: %s", exc)
        return False


async def delete_proxy_host(
    api_url: str, npm_email: str, npm_password: str, proxy_id: int
) -> bool:
    """Delete a proxy host from NPM.

    Logs in first to get a fresh JWT, then deletes the proxy host.

    Args:
        api_url: NPM API base URL.
        npm_email: NPM login email.
        npm_password: NPM login password.
        proxy_id: The proxy host ID to delete.

    Returns:
        True on success.
    """
    try:
        async with httpx.AsyncClient(timeout=NPM_TIMEOUT) as client:
            token = await _npm_login(client, api_url, npm_email, npm_password)
            headers = {"Authorization": f"Bearer {token}"}
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
