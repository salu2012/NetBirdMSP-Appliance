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


async def renew_token(container_prefix: str, token: str) -> dict[str, Any]:
    """Mint a fresh 365-day Personal Access Token using the current one.

    The old token is left in place (it naturally expires and NetBird gives no
    reliable way to identify "our" token among a user's other PATs by content
    alone, only by name — which isn't safe to assume is unique). One
    harmless unused token lingering until its own expiry is an acceptable
    trade-off for not risking deleting a token that turns out to be in use.
    """
    base_url = _base_url(container_prefix)
    headers = {"Authorization": f"Token {token}"}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(f"{base_url}/api/users", headers=headers)
            if resp.status_code != 200:
                return {"ok": False, "error": f"GET /api/users -> HTTP {resp.status_code}"}
            users = resp.json()
            me = next((u for u in users if u.get("is_current")), None)
            if not me:
                return {"ok": False, "error": "Could not identify current user from /api/users."}

            create_resp = await client.post(
                f"{base_url}/api/users/{me['id']}/tokens",
                headers={**headers, "Content-Type": "application/json"},
                content=json.dumps({"name": "MSP Central Management", "expires_in": 365}),
            )
            if create_resp.status_code not in (200, 201):
                return {"ok": False, "error": f"POST tokens -> HTTP {create_resp.status_code}: {create_resp.text[:200]}"}
            new_token = create_resp.json().get("plain_token")
            if not new_token:
                return {"ok": False, "error": "Token creation response had no plain_token."}

            verify_resp = await client.get(f"{base_url}/api/accounts", headers={"Authorization": f"Token {new_token}"})
            if verify_resp.status_code != 200:
                return {"ok": False, "error": "New token failed verification."}

            return {"ok": True, "token": new_token}
    except Exception as exc:
        logger.warning("Failed to renew NetBird API token for %s: %s", container_prefix, exc)
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
