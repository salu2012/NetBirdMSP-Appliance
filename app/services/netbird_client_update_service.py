"""Central control of the NetBird *client* (peer) Automatic Updates feature.

This is the "Settings > Clients > Automatic Updates" toggle inside each
customer's own NetBird dashboard (netbirdio/netbird, added in v0.61.0) — not
to be confused with updating the NetBird Docker images themselves
(app/services/image_service.py).

Talked to over the customer's NetBird Management REST API, authenticated
with a Personal Access Token captured during initial deployment (see
netbird_service.deploy_customer) or pasted in manually for customers
deployed before this feature existed. Requests go over the internal Docker
network directly to the customer's management container — never through
their public dashboard URL.
"""

import json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = 10


def _base_url(container_prefix: str) -> str:
    return f"http://{container_prefix}-management:80"


async def get_current_settings(container_prefix: str, token: str) -> dict[str, Any]:
    """Fetch the customer's current account settings.

    Returns:
        {"ok": True, "account_id": ..., "settings": {...}} on success, or
        {"ok": False, "error": "..."} on failure.
    """
    base_url = _base_url(container_prefix)
    headers = {"Authorization": f"Token {token}"}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(f"{base_url}/api/accounts", headers=headers)
            if resp.status_code != 200:
                return {"ok": False, "error": f"GET /api/accounts -> HTTP {resp.status_code}: {resp.text[:300]}"}
            accounts = resp.json()
            if not accounts:
                return {"ok": False, "error": "No account returned by /api/accounts."}
            account = accounts[0]
            return {"ok": True, "account_id": account["id"], "settings": account.get("settings", {})}
    except Exception as exc:
        logger.warning("Failed to fetch NetBird account settings for %s: %s", container_prefix, exc)
        return {"ok": False, "error": str(exc)}


async def push_auto_update_settings(
    container_prefix: str, token: str, version: str, always: bool
) -> dict[str, Any]:
    """Set the client automatic-updates version/mode for one customer.

    NetBird's account PUT endpoint expects the *entire* settings object, not
    a partial patch, so this fetches current settings first and only
    overwrites the two auto-update fields.
    """
    current = await get_current_settings(container_prefix, token)
    if not current["ok"]:
        return current

    settings = dict(current["settings"])
    settings["auto_update_version"] = version
    settings["auto_update_always"] = always

    base_url = _base_url(container_prefix)
    account_id = current["account_id"]
    headers = {"Authorization": f"Token {token}", "Content-Type": "application/json"}
    body = {"settings": settings}

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.put(
                f"{base_url}/api/accounts/{account_id}", headers=headers, content=json.dumps(body)
            )
            if resp.status_code != 200:
                return {"ok": False, "error": f"PUT /api/accounts/{account_id} -> HTTP {resp.status_code}: {resp.text[:300]}"}
            return {"ok": True}
    except Exception as exc:
        logger.warning("Failed to push NetBird auto-update settings for %s: %s", container_prefix, exc)
        return {"ok": False, "error": str(exc)}
